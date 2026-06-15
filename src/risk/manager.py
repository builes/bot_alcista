from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from config.settings import RiskConfig, StopConfig, CapitalConfig


@dataclass
class Position:
    entry_price: float
    entry_time: pd.Timestamp
    size: float
    capital_risk: float
    stop_loss: float
    take_profit: Optional[float] = None
    trailing_stop: Optional[float] = None
    trailing_activated: bool = False
    break_even_activated: bool = False
    highest_price: float = 0.0


@dataclass
class TradeRecord:
    entry_price: float
    exit_price: float
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    size: float
    pnl: float
    pnl_pct: float
    exit_reason: str  # "SL" | "TP" | "TRAILING" | "BREAK_EVEN" | "SIGNAL"


class RiskManager:
    def __init__(
        self,
        capital_cfg: CapitalConfig,
        risk_cfg: RiskConfig,
        stop_cfg: StopConfig,
    ) -> None:
        self._capital_cfg = capital_cfg
        self._risk_cfg = risk_cfg
        self._stop_cfg = stop_cfg
        self._equity = capital_cfg.initial
        self._peak_equity = capital_cfg.initial
        self._positions: list[Position] = []
        self._trades: list[TradeRecord] = []
        self._last_trade_time: Optional[pd.Timestamp] = None

    @property
    def equity(self) -> float:
        return self._equity

    @property
    def peak_equity(self) -> float:
        return self._peak_equity

    @property
    def positions(self) -> list[Position]:
        return list(self._positions)

    @property
    def trades(self) -> list[TradeRecord]:
        return list(self._trades)

    @property
    def drawdown(self) -> float:
        if self._peak_equity == 0:
            return 0.0
        return (self._peak_equity - self._equity) / self._peak_equity

    def can_trade(self, current_time: pd.Timestamp) -> bool:
        if self.drawdown >= self._risk_cfg.max_drawdown:
            return False
        if len(self._positions) >= self._risk_cfg.max_concurrent:
            return False
        if self._last_trade_time is not None:
            delta = (current_time - self._last_trade_time).days
            if delta < self._risk_cfg.min_interval_days:
                return False
        return True

    def compute_position_size(self, entry_price: float, stop_loss: float) -> float:
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit == 0:
            return 0.0
        capital_at_risk = self._equity * self._risk_cfg.per_trade
        size = capital_at_risk / risk_per_unit
        max_size_by_capital = self._equity / entry_price
        if size * entry_price > self._equity:
            size = max_size_by_capital
        return size

    def open_position(
        self,
        entry_time: pd.Timestamp,
        entry_price: float,
        stop_loss_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
    ) -> Optional[Position]:
        sl_price = stop_loss_price if stop_loss_price is not None else (
            entry_price * (1.0 - self._stop_cfg.loss_pct)
        )
        tp_price = take_profit_price if take_profit_price is not None else (
            entry_price * (1.0 + self._stop_cfg.take_profit_pct)
        )
        size = self.compute_position_size(entry_price, sl_price)

        if size <= 0:
            return None

        capital_risk = self._equity * self._risk_cfg.per_trade
        pos = Position(
            entry_price=entry_price,
            entry_time=entry_time,
            size=size,
            capital_risk=capital_risk,
            stop_loss=sl_price,
            take_profit=tp_price,
            highest_price=entry_price,
        )
        self._positions.append(pos)
        return pos

    def update_positions(self, current_time: pd.Timestamp, high: float, low: float) -> list[TradeRecord]:
        closed: list[TradeRecord] = []
        remaining: list[Position] = []

        for pos in self._positions:
            pos.highest_price = max(pos.highest_price, high)
            exit_reason = self._check_exits(pos, high, low)

            if exit_reason is not None:
                exit_price = self._compute_exit_price(pos, exit_reason, high, low)
                pnl_pct = (exit_price - pos.entry_price) / pos.entry_price
                pnl = pnl_pct * pos.size * pos.entry_price

                self._equity += pnl
                self._peak_equity = max(self._peak_equity, self._equity)

                record = TradeRecord(
                    entry_price=pos.entry_price,
                    exit_price=exit_price,
                    entry_time=pos.entry_time,
                    exit_time=current_time,
                    size=pos.size,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    exit_reason=exit_reason,
                )
                closed.append(record)
                self._trades.append(record)
                self._last_trade_time = current_time
            else:
                remaining.append(pos)

        self._positions = remaining
        return closed

    def close_all_positions(self, current_time: pd.Timestamp, price: float) -> list[TradeRecord]:
        closed: list[TradeRecord] = []
        for pos in self._positions:
            pnl_pct = (price - pos.entry_price) / pos.entry_price
            pnl = pnl_pct * pos.size * pos.entry_price
            self._equity += pnl
            record = TradeRecord(
                entry_price=pos.entry_price,
                exit_price=price,
                entry_time=pos.entry_time,
                exit_time=current_time,
                size=pos.size,
                pnl=pnl,
                pnl_pct=pnl_pct,
                exit_reason="SIGNAL",
            )
            closed.append(record)
            self._trades.append(record)
        self._positions.clear()
        self._last_trade_time = current_time
        return closed

    def _check_exits(self, pos: Position, high: float, low: float) -> Optional[str]:
        self._update_trailing(pos)

        if low <= pos.stop_loss:
            return "TRAILING" if pos.trailing_activated else "SL"

        if pos.take_profit is not None and high >= pos.take_profit:
            return "TP"

        return None

    def _compute_exit_price(self, pos: Position, reason: str, high: float, low: float) -> float:
        if reason in ("SL", "TRAILING", "BREAK_EVEN"):
            return pos.stop_loss
        if reason == "TP" and pos.take_profit is not None:
            return pos.take_profit
        return (high + low) / 2

    def _update_trailing(self, pos: Position) -> None:
        if pos.highest_price <= 0:
            return

        pct_from_entry = (pos.highest_price - pos.entry_price) / pos.entry_price

        if not pos.break_even_activated and pct_from_entry >= self._stop_cfg.break_even_trigger:
            pos.stop_loss = min(pos.stop_loss, pos.entry_price)
            pos.break_even_activated = True

        if not pos.trailing_activated and pct_from_entry >= self._stop_cfg.trailing_activation:
            pos.trailing_activated = True

        if pos.trailing_activated:
            if pct_from_entry >= 0.10:
                trail_dist = 0.001
            elif pct_from_entry >= 0.07:
                trail_dist = 0.0025
            elif pct_from_entry >= 0.05:
                trail_dist = 0.005
            elif pct_from_entry >= 0.03:
                trail_dist = 0.0075
            elif pct_from_entry >= 0.02:
                trail_dist = 0.01
            else:
                trail_dist = 0.015
            trail = pos.highest_price * (1.0 - trail_dist)
            pos.stop_loss = max(pos.stop_loss, trail)
