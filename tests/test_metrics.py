import pandas as pd
import pytest

from src.metrics.calculator import MetricsCalculator
from src.risk.manager import TradeRecord


class TestMetricsCalculator:
    @pytest.fixture
    def calculator(self) -> MetricsCalculator:
        return MetricsCalculator(initial_capital=100_000.0)

    def test_empty_trades_returns_zero_metrics(self, calculator: MetricsCalculator) -> None:
        eq = pd.Series([100_000, 100_000], index=pd.date_range("2023-01-01", periods=2, freq="D"))
        metrics = calculator.compute(eq, [])
        assert metrics["total_trades"] == 0
        assert metrics["win_rate_pct"] == 0.0

    def test_profitable_trades(self, calculator: MetricsCalculator) -> None:
        eq = pd.Series([100_000, 105_000, 110_000], index=pd.date_range("2023-01-01", periods=3, freq="D"))
        trades = [
            TradeRecord(100, 105, pd.Timestamp("2023-01-01"), pd.Timestamp("2023-01-02"), 100, 500, 0.05, "TP"),
            TradeRecord(105, 110, pd.Timestamp("2023-01-02"), pd.Timestamp("2023-01-03"), 100, 500, 0.05, "TP"),
        ]
        metrics = calculator.compute(eq, trades)
        assert metrics["total_return"] > 0
        assert metrics["win_rate_pct"] == 100.0
        assert metrics["total_trades"] == 2

    def test_mixed_trades(self, calculator: MetricsCalculator) -> None:
        eq = pd.Series([100_000, 99_000, 101_000], index=pd.date_range("2023-01-01", periods=3, freq="D"))
        trades = [
            TradeRecord(100, 98, pd.Timestamp("2023-01-01"), pd.Timestamp("2023-01-02"), 100, -200, -0.02, "SL"),
            TradeRecord(98, 103, pd.Timestamp("2023-01-02"), pd.Timestamp("2023-01-03"), 100, 500, 0.05, "TP"),
        ]
        metrics = calculator.compute(eq, trades)
        assert metrics["total_trades"] == 2
        assert 0 < metrics["win_rate_pct"] < 100

    def test_sharpe_ratio_positive_for_good_returns(self, calculator: MetricsCalculator) -> None:
        eq = pd.Series(
            [100_000, 101_000, 102_000, 103_000, 104_000],
            index=pd.date_range("2023-01-01", periods=5, freq="D"),
        )
        metrics = calculator.compute(eq, [])
        assert metrics["sharpe_ratio"] > 0
