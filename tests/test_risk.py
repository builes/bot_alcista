import pandas as pd
import pytest

from config.settings import CapitalConfig, RiskConfig, StopConfig
from src.risk.manager import RiskManager


@pytest.fixture
def risk_mgr() -> RiskManager:
    return RiskManager(
        capital_cfg=CapitalConfig(initial=100_000.0),
        risk_cfg=RiskConfig(per_trade=0.01, max_drawdown=0.20, max_concurrent=3, min_interval_days=0),
        stop_cfg=StopConfig(loss_pct=0.02, take_profit_pct=0.06, break_even_trigger=0.01,
                            trailing_activation=0.015, trailing_distance=0.015),
    )


class TestRiskManager:
    def test_initial_equity(self, risk_mgr: RiskManager) -> None:
        assert risk_mgr.equity == 100_000.0

    def test_can_trade_initially(self, risk_mgr: RiskManager) -> None:
        assert risk_mgr.can_trade(pd.Timestamp("2023-01-01")) is True

    def test_position_size_calculation(self, risk_mgr: RiskManager) -> None:
        size = risk_mgr.compute_position_size(100.0, 98.0)
        expected = (100_000 * 0.01) / 2.0
        assert size == pytest.approx(expected)

    def test_open_position_returns_position(self, risk_mgr: RiskManager) -> None:
        pos = risk_mgr.open_position(pd.Timestamp("2023-01-01"), 100.0)
        assert pos is not None
        assert pos.entry_price == 100.0
        assert pos.stop_loss == 98.0

    def test_stop_loss_hit(self, risk_mgr: RiskManager) -> None:
        pos = risk_mgr.open_position(pd.Timestamp("2023-01-01"), 100.0)
        assert pos is not None
        closed = risk_mgr.update_positions(pd.Timestamp("2023-01-02"), high=101.0, low=97.0)
        assert len(closed) == 1
        assert closed[0].exit_reason == "SL"

    def test_take_profit_or_trailing_hit(self, risk_mgr: RiskManager) -> None:
        pos = risk_mgr.open_position(pd.Timestamp("2023-01-01"), 100.0)
        assert pos is not None
        closed = risk_mgr.update_positions(pd.Timestamp("2023-01-02"), high=107.0, low=105.0)
        assert len(closed) == 1
        # Con trailing progresivo, la ganancia > 5% ajusta el stop a 0.5%
        # y la salida es TRAILING con mejor precio que TP
        assert closed[0].exit_reason in ("TP", "TRAILING")
        assert closed[0].exit_price > pos.take_profit  # trailing > TP

    def test_max_concurrent_positions(self, risk_mgr: RiskManager) -> None:
        risk_mgr._risk_cfg = RiskConfig(per_trade=0.01, max_drawdown=0.20, max_concurrent=1, min_interval_days=0)
        pos1 = risk_mgr.open_position(pd.Timestamp("2023-01-01"), 100.0)
        assert pos1 is not None
        risk_mgr.update_positions(pd.Timestamp("2023-01-01"), high=100.0, low=100.0)
        assert risk_mgr.can_trade(pd.Timestamp("2023-01-02")) is False

    def test_drawdown_prevents_trading(self, risk_mgr: RiskManager) -> None:
        risk_mgr._risk_cfg = RiskConfig(per_trade=1.0, max_drawdown=0.01, max_concurrent=3, min_interval_days=0)
        pos = risk_mgr.open_position(pd.Timestamp("2023-01-01"), 100.0)
        assert pos is not None
        risk_mgr.update_positions(pd.Timestamp("2023-01-02"), high=100.0, low=90.0)
        assert risk_mgr.drawdown > 0.0
        assert risk_mgr.can_trade(pd.Timestamp("2023-01-03")) is False

    def test_close_all_positions(self, risk_mgr: RiskManager) -> None:
        risk_mgr.open_position(pd.Timestamp("2023-01-01"), 100.0)
        risk_mgr.open_position(pd.Timestamp("2023-01-01"), 200.0)
        closed = risk_mgr.close_all_positions(pd.Timestamp("2023-01-02"), 105.0)
        assert len(closed) == 2
        assert len(risk_mgr.positions) == 0
