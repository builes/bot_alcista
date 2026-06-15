from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from src.risk.manager import Position, RiskManager, TradeRecord
from src.screener.market_screener import ScreenedPair
from src.utils.logger import setup_logger

logger = setup_logger("portfolio", Path("logs"))


@dataclass
class PairAllocation:
    symbol: str
    capital: float
    risk_per_trade_pct: float
    risk_mgr: RiskManager
    positions: List[Position] = field(default_factory=list)
    trades: List[TradeRecord] = field(default_factory=list)


class PortfolioManager:
    def __init__(
        self,
        total_capital: float,
        risk_per_trade_pct: float = 0.03,
        max_drawdown: float = 0.30,
        max_concurrent_pairs: int = 5,
        stop_loss_pct: float = 0.015,
        take_profit_pct: float = 0.06,
        break_even_trigger: float = 0.01,
        trailing_activation: float = 0.02,
        trailing_distance: float = 0.015,
    ) -> None:
        self._total_capital = total_capital
        self._risk_pt = risk_per_trade_pct
        self._max_dd = max_drawdown
        self._max_pairs = max_concurrent_pairs
        self._sl_pct = stop_loss_pct
        self._tp_pct = take_profit_pct
        self._be_trigger = break_even_trigger
        self._trail_act = trailing_activation
        self._trail_dist = trailing_distance
        self._peak_capital = total_capital
        self._allocations: Dict[str, PairAllocation] = {}
        self._screener_cache: List[ScreenedPair] = []

    @property
    def equity(self) -> float:
        total = 0.0
        for alloc in self._allocations.values():
            total += alloc.risk_mgr.equity
        return total

    @property
    def drawdown(self) -> float:
        eq = self.equity
        self._peak_capital = max(self._peak_capital, eq)
        if self._peak_capital == 0:
            return 0.0
        return (self._peak_capital - eq) / self._peak_capital

    @property
    def all_trades(self) -> List[TradeRecord]:
        trades = []
        for alloc in self._allocations.values():
            trades.extend(alloc.risk_mgr.trades)
        return trades

    def can_trade(self) -> bool:
        return self.drawdown < self._max_dd

    def update_screened_pairs(self, pairs: List[ScreenedPair]) -> None:
        self._screener_cache = pairs
        bull_pairs = [p for p in pairs if p.is_bull][:self._max_pairs]
        current_symbols = set(self._allocations.keys())
        selected_symbols = {p.symbol for p in bull_pairs}

        to_remove = current_symbols - selected_symbols
        to_add = selected_symbols - current_symbols

        for sym in to_remove:
            logger.info("Portfolio: removiendo %s (salió de tendencia)", sym)
            del self._allocations[sym]

        n = len(selected_symbols) or 1
        capital_per_pair = self._total_capital / n

        for sym in to_add:
            alloc = PairAllocation(
                symbol=sym,
                capital=capital_per_pair,
                risk_per_trade_pct=self._risk_pt,
                risk_mgr=RiskManager.__new__(RiskManager),
            )
            RiskManager.__init__(
                alloc.risk_mgr,
                capital_cfg=type("CC", (), {"initial": capital_per_pair})(),
                risk_cfg=type("RC", (), {
                    "per_trade": self._risk_pt,
                    "max_drawdown": self._max_dd,
                    "max_concurrent": 1,
                    "min_interval_days": 0,
                })(),
                stop_cfg=type("SC", (), {
                    "loss_pct": self._sl_pct,
                    "take_profit_pct": self._tp_pct,
                    "break_even_trigger": self._be_trigger,
                    "trailing_activation": self._trail_act,
                    "trailing_distance": self._trail_dist,
                })(),
            )
            self._allocations[sym] = alloc
            logger.info("Portfolio: añadiendo %s (capital=%.0f)", sym, capital_per_pair)

    def get_allocation(self, symbol: str) -> Optional[PairAllocation]:
        return self._allocations.get(symbol)

    def update_positions(self, current_time: pd.Timestamp, symbol: str, high: float, low: float) -> List[TradeRecord]:
        alloc = self._allocations.get(symbol)
        if alloc is None:
            return []
        closed = alloc.risk_mgr.update_positions(current_time, high, low)
        alloc.trades.extend(closed)
        return closed

    def close_pair_positions(self, symbol: str, price: float, current_time: pd.Timestamp) -> List[TradeRecord]:
        alloc = self._allocations.get(symbol)
        if alloc is None:
            return []
        closed = alloc.risk_mgr.close_all_positions(current_time, price)
        alloc.trades.extend(closed)
        return closed

    def open_position(self, symbol: str, entry_time: pd.Timestamp, entry_price: float) -> Optional[Position]:
        if not self.can_trade():
            return None
        alloc = self._allocations.get(symbol)
        if alloc is None:
            return None
        return alloc.risk_mgr.open_position(entry_time, entry_price)
