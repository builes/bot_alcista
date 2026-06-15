from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config.settings import Settings
from src.data.loader import load_ohlcv_csv, resample
from src.metrics.calculator import MetricsCalculator
from src.portfolio.manager import PortfolioManager
from src.screener.market_screener import MarketScreener
from src.strategies.aggressive_trend import AggressiveTrendStrategy
from src.utils.logger import setup_logger

logger = setup_logger("multi_backtest", Path("logs"))


@dataclass
class MultiBacktestResult:
    metrics: dict
    trades: List = field(default_factory=list)
    equity_curve: Optional[pd.Series] = None
    pair_results: Dict[str, dict] = field(default_factory=dict)


class MultiPairBacktestEngine:
    def __init__(
        self,
        settings: Settings,
        strategy_params: Optional[dict] = None,
        max_pairs: int = 10,
        min_volume_usd: float = 1_000_000,
        screen_ema_fast: int = 20,
        screen_ema_slow: int = 50,
    ) -> None:
        self._settings = settings
        self._strategy_params = strategy_params or {}
        self._max_pairs = max_pairs
        self._min_volume = min_volume_usd
        self._screen_ema_fast = screen_ema_fast
        self._screen_ema_slow = screen_ema_slow

    def run(self, data_dir: Path) -> MultiBacktestResult:
        csv_files = sorted(data_dir.glob("*_4h.csv"))
        if not csv_files:
            raise FileNotFoundError(f"No se encontraron archivos *_4h.csv en {data_dir}")

        logger.info("Cargando %d pares para backtest multi-par", len(csv_files))
        all_data: Dict[str, pd.DataFrame] = {}
        for csv_file in csv_files:
            try:
                sym = csv_file.stem.replace("_4h", "").replace("_", "/", 1)
                if "/" not in sym:
                    sym = sym.replace("_", "/")
                df = load_ohlcv_csv(csv_file)
                all_data[sym] = df
            except Exception as e:
                logger.warning("Error cargando %s: %s", csv_file.name, e)

        starts = {s: df.index[0] for s, df in all_data.items()}
        ends = {s: df.index[-1] for s, df in all_data.items()}
        start = max(starts.values())
        end = min(ends.values())

        outliers = {s for s, v in all_data.items() if v.index[0] > end or v.index[-1] < start}
        if outliers:
            logger.info("Excluyendo %d pares con rangos fuera del común", len(outliers))
            for s in outliers:
                del all_data[s]

        start = max(df.index[0] for df in all_data.values())
        end = min(df.index[-1] for df in all_data.values())
        logger.info("Rango combinado: %s → %s (%d velas)", start, end, len(pd.date_range(start=start, end=end, freq="4h")))
        combined_idx = pd.date_range(start=start, end=end, freq="4h")
        if len(combined_idx) < 50:
            logger.warning("Pocos timestamps (%d) — backtest puede ser irrelevante", len(combined_idx))

        portfolio = PortfolioManager(
            total_capital=self._settings.capital.initial,
            risk_per_trade_pct=self._settings.risk.per_trade,
            max_drawdown=self._settings.risk.max_drawdown,
            max_concurrent_pairs=self._max_pairs,
            stop_loss_pct=self._settings.stops.loss_pct,
            take_profit_pct=self._settings.stops.take_profit_pct,
            break_even_trigger=self._settings.stops.break_even_trigger,
            trailing_activation=self._settings.stops.trailing_activation,
            trailing_distance=self._settings.stops.trailing_distance,
        )

        strategies: Dict[str, AggressiveTrendStrategy] = {}

        equity_curve: List[Tuple[pd.Timestamp, float]] = []
        scan_interval = 6

        for i, ts in enumerate(combined_idx):
            if i % scan_interval == 0:
                active_symbols = self._screen_pairs(all_data, ts)
                portfolio.update_screened_pairs(active_symbols)

            for sym, df in all_data.items():
                if ts not in df.index:
                    continue

                row = df.loc[ts]
                closed = portfolio.update_positions(ts, sym, row["high"], row["low"])

                if sym not in strategies:
                    strategies[sym] = AggressiveTrendStrategy(self._strategy_params)

                alloc = portfolio.get_allocation(sym)
                if alloc is None:
                    continue

                has_position = len(alloc.risk_mgr.positions) > 0

                df_up_to = df.loc[:ts]
                signals = strategies[sym].generate_signals(df_up_to)
                last_sig = signals.iloc[-1]

                if not has_position and last_sig["buy_signal"] == 1:
                    if alloc.risk_mgr.can_trade(ts):
                        pos = portfolio.open_position(sym, ts, row["close"])
                        if pos:
                            logger.debug("%s BUY @ %.2f", sym, row["close"])

                if has_position and last_sig["exit_signal"] == 1:
                    portfolio.close_pair_positions(sym, row["close"], ts)

            equity_curve.append((ts, portfolio.equity))

        eq_series = pd.Series(
            data=[e for _, e in equity_curve],
            index=[t for t, _ in equity_curve],
        )

        trades = portfolio.all_trades
        calculator = MetricsCalculator(initial_capital=self._settings.capital.initial)
        metrics = calculator.compute(eq_series, trades)

        logger.info("Multi-backtest: %d trades | Return: %.2f%% | Sharpe: %.2f",
                     len(trades), metrics.get("total_return_pct", 0), metrics.get("sharpe_ratio", 0))

        return MultiBacktestResult(metrics=metrics, trades=trades, equity_curve=eq_series)

    def _screen_pairs(self, all_data: Dict[str, pd.DataFrame], ts: pd.Timestamp) -> List:
        from src.screener.market_screener import ScreenedPair

        results = []
        for sym, df in all_data.items():
            df_before = df.loc[:ts]
            min_required = max(self._screen_ema_slow + 20, 100)
            if len(df_before) < min_required:
                continue

            close = df_before["close"]
            ema_fast = close.ewm(span=self._screen_ema_fast, adjust=False).mean()
            ema_slow = close.ewm(span=self._screen_ema_slow, adjust=False).mean()
            last_fast = float(ema_fast.iloc[-1])
            last_slow = float(ema_slow.iloc[-1])
            last_close = float(close.iloc[-1])

            high = df_before["high"]
            low = df_before["low"]
            prev_close = close.shift(1)
            tr = pd.concat([
                (high - low).abs(),
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ], axis=1).max(axis=1)
            up_move = high - high.shift(1)
            down_move = low.shift(1) - low
            plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
            minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)
            tr_s = tr.ewm(span=14, adjust=False).mean()
            p_s = plus_dm.ewm(span=14, adjust=False).mean()
            m_s = minus_dm.ewm(span=14, adjust=False).mean()
            di_plus = 100.0 * p_s / tr_s.replace(0, np.nan)
            di_minus = 100.0 * m_s / tr_s.replace(0, np.nan)
            dx = 100.0 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
            adx = dx.ewm(span=14, adjust=False).mean()

            is_bull = (
                last_fast > last_slow
                and float(adx.iloc[-1]) >= 20
                and float(di_plus.iloc[-1]) > float(di_minus.iloc[-1])
                and last_close > last_slow
            )
            if is_bull:
                score = (last_fast / last_slow - 1.0) * 100.0
                results.append(ScreenedPair(
                    symbol=sym, close_price=last_close, volume_24h_usd=1e9,
                    trend_score=score, adx=float(adx.iloc[-1]),
                    di_plus=float(di_plus.iloc[-1]), di_minus=float(di_minus.iloc[-1]),
                    ema_fast=last_fast, ema_slow=last_slow, is_bull=True,
                ))

        results.sort(key=lambda x: x.trend_score, reverse=True)
        return results[:self._max_pairs]
