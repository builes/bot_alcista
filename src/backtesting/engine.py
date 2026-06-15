from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

from typing import Optional, Type

from config.settings import Settings, CapitalConfig, RiskConfig, StopConfig
from src.data.loader import load_ohlcv_csv
from src.metrics.calculator import MetricsCalculator
from src.risk.manager import RiskManager
from src.strategies.base import BaseStrategy
from src.strategies.trend_following import TrendFollowingStrategy
from src.utils.logger import setup_logger

logger = setup_logger("backtest", Path("logs"))


@dataclass
class BacktestResult:
    metrics: dict
    trades: list = field(default_factory=list)
    equity_curve: Optional[pd.Series] = None


class BacktestEngine:
    def __init__(
        self,
        settings: Settings,
        strategy_params: Optional[dict] = None,
        strategy_class: Type[BaseStrategy] = TrendFollowingStrategy,
        risk_override: Optional[dict] = None,
        stop_override: Optional[dict] = None,
    ) -> None:
        self._settings = settings
        self._strategy_params = strategy_params or {}
        self._strategy_class = strategy_class
        self._risk_override = risk_override or {}
        self._stop_override = stop_override or {}

    def run(self, data_path: Path) -> BacktestResult:
        df = load_ohlcv_csv(data_path)

        strategy = self._strategy_class(self._strategy_params)
        df_signals = strategy.generate_signals(df)

        risk_cfg = RiskConfig(
            per_trade=self._risk_override.get("per_trade", self._settings.risk.per_trade),
            max_drawdown=self._risk_override.get("max_drawdown", self._settings.risk.max_drawdown),
            max_concurrent=self._risk_override.get("max_concurrent", self._settings.risk.max_concurrent),
            min_interval_days=self._risk_override.get("min_interval_days", self._settings.risk.min_interval_days),
        )
        stop_cfg = StopConfig(
            loss_pct=self._stop_override.get("loss_pct", self._settings.stops.loss_pct),
            take_profit_pct=self._stop_override.get("take_profit_pct", self._settings.stops.take_profit_pct),
            break_even_trigger=self._stop_override.get("break_even_trigger", self._settings.stops.break_even_trigger),
            trailing_activation=self._stop_override.get("trailing_activation", self._settings.stops.trailing_activation),
            trailing_distance=self._stop_override.get("trailing_distance", self._settings.stops.trailing_distance),
        )

        risk_mgr = RiskManager(
            capital_cfg=self._settings.capital,
            risk_cfg=risk_cfg,
            stop_cfg=stop_cfg,
        )

        equity_curve: list[tuple[pd.Timestamp, float]] = []
        in_position = False

        for idx, row in df_signals.iterrows():
            risk_mgr.update_positions(idx, row["high"], row["low"])

            if not in_position and row["buy_signal"] == 1:
                if risk_mgr.can_trade(idx):
                    pos = risk_mgr.open_position(idx, row["close"])
                    if pos is not None:
                        in_position = True
                        logger.info(
                            "BUY  %s @ %.2f  SL=%.2f  TP=%.2f",
                            idx, row["close"], pos.stop_loss, pos.take_profit,
                        )

            if in_position and row["exit_signal"] == 1:
                closed = risk_mgr.close_all_positions(idx, row["close"])
                in_position = False
                for t in closed:
                    logger.info(
                        "EXIT %s @ %.2f  %+.2f (%+.2f%%)  %s",
                        t.exit_time, t.exit_price, t.pnl, t.pnl_pct * 100, t.exit_reason,
                    )

            equity_curve.append((idx, risk_mgr.equity))

        if in_position:
            risk_mgr.close_all_positions(idx, row["close"])

        trades = risk_mgr.trades
        eq_series = pd.Series(
            data=[e for _, e in equity_curve],
            index=[t for t, _ in equity_curve],
        )

        calculator = MetricsCalculator(
            initial_capital=self._settings.capital.initial,
        )
        metrics = calculator.compute(eq_series, trades)

        logger.info("Backtest complete — %d trades | Return: %.2f%% | Sharpe: %.2f",
                     len(trades), metrics.get("total_return_pct", 0), metrics.get("sharpe_ratio", 0))

        return BacktestResult(metrics=metrics, trades=trades, equity_curve=eq_series)
