"""Multi-backtest realista con capital compartido y screener periódico."""
import sys
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from config.settings import SETTINGS
from src.data.loader import load_ohlcv_csv
from src.risk.manager import RiskManager, CapitalConfig, RiskConfig, StopConfig, Position, TradeRecord
from src.strategies.aggressive_trend import AggressiveTrendStrategy
from src.metrics.calculator import MetricsCalculator
from src.utils.logger import setup_logger

logger = setup_logger("realistic_multi", SETTINGS.logs_dir)

TOTAL_CAPITAL = SETTINGS.capital.initial
MAX_PAIRS = 10
SCREEN_INTERVAL = 6  # every 6 candles (24h at 4h)
SCREEN_EMA_FAST = 20
SCREEN_EMA_SLOW = 50


def screen_pairs(
    all_data: Dict[str, pd.DataFrame], ts: pd.Timestamp,
) -> List[str]:
    results = []
    for sym, df in all_data.items():
        df_before = df.loc[:ts]
        if len(df_before) < SCREEN_EMA_SLOW + 20:
            continue
        close = df_before["close"].astype(float)
        ema_fast = close.ewm(span=SCREEN_EMA_FAST, adjust=False).mean()
        ema_slow = close.ewm(span=SCREEN_EMA_SLOW, adjust=False).mean()
        high = df_before["high"].astype(float)
        low = df_before["low"].astype(float)
        prev_close = close.shift(1)
        tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        up = high - high.shift(1)
        down = low.shift(1) - low
        plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=high.index)
        minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=high.index)
        tr_s = tr.ewm(span=14, adjust=False).mean().replace(0, np.nan)
        p_s = plus_dm.ewm(span=14, adjust=False).mean()
        m_s = minus_dm.ewm(span=14, adjust=False).mean()
        di_plus = 100.0 * p_s / tr_s
        di_minus = 100.0 * m_s / tr_s
        dx = 100.0 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
        adx = dx.ewm(span=14, adjust=False).mean()
        l = -1
        if (ema_fast.iloc[l] > ema_slow.iloc[l]
            and float(adx.iloc[l]) >= 20
            and float(di_plus.iloc[l]) > float(di_minus.iloc[l])
            and float(close.iloc[l]) > float(ema_slow.iloc[l])):
            results.append(sym)
    return results[:MAX_PAIRS]


def main():
    data_dir = SETTINGS.data_dir
    csv_files = sorted(data_dir.glob("*_4h_2y.csv")) + sorted(data_dir.glob("*_4h.csv"))
    seen = set()
    unique = []
    for f in csv_files:
        stem = f.stem.replace("_4h_2y", "").replace("_4h", "")
        if stem not in seen:
            seen.add(stem)
            unique.append(f)

    logger.info("Cargando %d pares...", len(unique))
    all_data: Dict[str, pd.DataFrame] = {}
    for f in unique:
        try:
            sym = f.stem.replace("_4h_2y", "").replace("_4h", "").replace("_", "/", 1)
            if "/" not in sym:
                sym = sym.replace("_", "/")
            all_data[sym] = load_ohlcv_csv(f)
        except Exception as e:
            logger.warning("Error %s: %s", f.name, e)

    min_candles = 4000
    short = {s for s, df in all_data.items() if len(df) < min_candles}
    if short:
        logger.info("Excluyendo %d pares con < %d velas: %s", len(short), min_candles, sorted(short))
        for s in short:
            del all_data[s]

    start = max(df.index[0] for df in all_data.values())
    end = min(df.index[-1] for df in all_data.values())
    combined_idx = pd.date_range(start=start, end=end, freq="4h")
    logger.info("Rango: %s → %s (%d velas, %d pares)", start, end, len(combined_idx), len(all_data))

    strategies: Dict[str, AggressiveTrendStrategy] = {}
    for sym in all_data:
        strategies[sym] = AggressiveTrendStrategy({
            "ema_fast": 5, "ema_slow": 20, "adx_threshold": 20,
            "volume_threshold": 1.0, "pullback_mode": False,
        })

    active_pairs: set = set()
    risk_managers: Dict[str, RiskManager] = {}
    equity_curve: List[Tuple[pd.Timestamp, float]] = []

    for i, ts in enumerate(combined_idx):
        if i % SCREEN_INTERVAL == 0:
            active_pairs = set(screen_pairs(all_data, ts))
            n = len(active_pairs) or 1
            cap_per_pair = TOTAL_CAPITAL / n
            for sym in active_pairs:
                if sym not in risk_managers:
                    risk_managers[sym] = RiskManager(
                        CapitalConfig(initial=cap_per_pair),
                        RiskConfig(per_trade=SETTINGS.risk.per_trade, max_drawdown=SETTINGS.risk.max_drawdown, max_concurrent=1, min_interval_days=0),
                        StopConfig(loss_pct=SETTINGS.stops.loss_pct, take_profit_pct=SETTINGS.stops.take_profit_pct, break_even_trigger=SETTINGS.stops.break_even_trigger, trailing_activation=SETTINGS.stops.trailing_activation, trailing_distance=SETTINGS.stops.trailing_distance),
                    )
            for sym in list(risk_managers.keys()):
                if sym not in active_pairs and len(risk_managers[sym].positions) == 0:
                    del risk_managers[sym]

        for sym in list(risk_managers.keys()):
            df = all_data.get(sym)
            if df is None or ts not in df.index:
                continue
            row = df.loc[ts]
            high, low, close = float(row["high"]), float(row["low"]), float(row["close"])
            risk_managers[sym].update_positions(ts, high, low)
            signals = strategies[sym].generate_signals(df.loc[:ts])
            sig = signals.iloc[-1]
            has_pos = len(risk_managers[sym].positions) > 0

            if not has_pos and sig["buy_signal"] == 1 and sym in active_pairs:
                risk_managers[sym].open_position(ts, close)
            elif has_pos and sig["exit_signal"] == 1:
                risk_managers[sym].close_all_positions(ts, close)

        total_eq = sum(rm.equity for rm in risk_managers.values())
        idle_capital = TOTAL_CAPITAL - sum(
            TOTAL_CAPITAL / max(len(risk_managers), 1) for _ in risk_managers
        ) if risk_managers else TOTAL_CAPITAL
        equity_curve.append((ts, total_eq + max(0.0, idle_capital)))

    eq_series = pd.Series(data=[e for _, e in equity_curve], index=[t for t, _ in equity_curve])
    all_trades = []
    for sym, rm in risk_managers.items():
        for t in rm.trades:
            all_trades.append(t)

    calculator = MetricsCalculator(initial_capital=TOTAL_CAPITAL)
    metrics = calculator.compute(eq_series, all_trades)

    days = (combined_idx[-1] - combined_idx[0]).total_seconds() / 86400
    months = days / 30.44
    monthly = metrics.get("total_return_pct", 0) / months if months > 0 else 0

    print(f"\n{'='*60}")
    print(f"  MULTI-BACKTEST REALISTA")
    print(f"{'='*60}")
    print(f"  Capital inicial:  ${TOTAL_CAPITAL:,.2f}")
    print(f"  Período:          {start.date()} → {end.date()} ({months:.1f} meses)")
    print(f"  Pares evaluados:  {len(all_data)}")
    print(f"  Pares simultáneos: {MAX_PAIRS}")
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    print(f"  Retorno mensual:  {monthly:+.2f}%")
    print(f"  Trades totales:   {len(all_trades)}")
    print(f"{'='*60}\n")

    out = SETTINGS.data_dir.parent / "results" / "realistic_multi.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "period": {"start": str(start.date()), "end": str(end.date()), "months": round(months, 1)},
        "pairs_total": len(all_data),
        "max_concurrent": MAX_PAIRS,
        "metrics": {k: round(v, 4) if isinstance(v, float) else v for k, v in metrics.items()},
        "monthly_return_pct": round(monthly, 2),
        "total_trades": len(all_trades),
    }, indent=2))


if __name__ == "__main__":
    main()
