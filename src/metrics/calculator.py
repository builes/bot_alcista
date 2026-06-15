import math
from typing import List

import numpy as np
import pandas as pd

from src.risk.manager import TradeRecord


class MetricsCalculator:
    def __init__(self, initial_capital: float, risk_free_rate: float = 0.05) -> None:
        self._initial_capital = initial_capital
        self._risk_free_rate = risk_free_rate

    def compute(self, equity_curve: pd.Series, trades: List[TradeRecord]) -> dict:
        total_return = equity_curve.iloc[-1] - self._initial_capital
        total_return_pct = total_return / self._initial_capital * 100.0

        peak = equity_curve.cummax()
        dd = (peak - equity_curve) / peak
        max_dd = dd.max() * 100.0

        daily_returns = equity_curve.pct_change().dropna()

        if len(daily_returns) > 1:
            sharpe = self._sharpe_ratio(daily_returns)
        else:
            sharpe = 0.0

        win_rate, profit_factor, expectancy, avg_win, avg_loss = self._trade_stats(trades)

        return {
            "total_return": round(total_return, 2),
            "total_return_pct": round(total_return_pct, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 4),
            "profit_factor": round(profit_factor, 4),
            "win_rate_pct": round(win_rate * 100.0, 2),
            "expectancy": round(expectancy, 4),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "total_trades": len(trades),
            "final_equity": round(equity_curve.iloc[-1], 2),
        }

    def _sharpe_ratio(self, returns: pd.Series) -> float:
        excess = returns - self._risk_free_rate / 252
        if excess.std() == 0:
            return 0.0
        return float(np.sqrt(252) * excess.mean() / excess.std())

    def _trade_stats(self, trades: List[TradeRecord]) -> tuple:
        if not trades:
            return 0.0, 0.0, 0.0, 0.0, 0.0

        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]

        win_rate = len(wins) / len(trades) if trades else 0.0

        gross_profit = sum(t.pnl for t in wins) if wins else 0.0
        gross_loss = abs(sum(t.pnl for t in losses)) if losses else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        avg_win = (sum(t.pnl_pct for t in wins) / len(wins) * 100) if wins else 0.0
        avg_loss = (sum(t.pnl_pct for t in losses) / len(losses) * 100) if losses else 0.0

        expectancy = win_rate * (avg_win / 100) - (1 - win_rate) * (abs(avg_loss) / 100)

        return win_rate, profit_factor, expectancy, avg_win, avg_loss
