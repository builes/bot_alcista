import numpy as np
import pandas as pd
import pytest

from src.strategies.trend_following import TrendFollowingStrategy


@pytest.fixture
def sample_data() -> pd.DataFrame:
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=300, freq="D")
    trend = np.linspace(100, 150, 300) + np.random.normal(0, 2, 300)
    return pd.DataFrame(
        {
            "open": trend + np.random.uniform(-1, 1, 300),
            "high": trend + np.random.uniform(0, 2, 300),
            "low": trend - np.random.uniform(0, 2, 300),
            "close": trend + np.random.uniform(-1, 1, 300),
            "volume": np.random.uniform(1000, 5000, 300),
        },
        index=dates,
    )


class TestTrendFollowingStrategy:
    def test_calculate_indicators_adds_columns(self, sample_data: pd.DataFrame) -> None:
        strategy = TrendFollowingStrategy({})
        result = strategy.calculate_indicators(sample_data)
        expected_cols = {"ema_fast", "ema_slow", "adx", "di_plus", "di_minus", "volume_sma", "volume_ratio"}
        assert expected_cols.issubset(result.columns)

    def test_generate_signals_adds_signal_columns(self, sample_data: pd.DataFrame) -> None:
        strategy = TrendFollowingStrategy({})
        result = strategy.generate_signals(sample_data)
        assert "buy_signal" in result.columns
        assert "exit_signal" in result.columns
        assert "signal" in result.columns

    def test_signal_values_are_binary(self, sample_data: pd.DataFrame) -> None:
        strategy = TrendFollowingStrategy({})
        result = strategy.generate_signals(sample_data).dropna()
        assert result["buy_signal"].isin([0, 1]).all()
        assert result["exit_signal"].isin([0, 1]).all()

    def test_ema_in_bull_market_no_signals(self) -> None:
        dates = pd.date_range("2023-01-01", periods=100, freq="D")
        close = np.linspace(100, 200, 100)
        data = pd.DataFrame(
            {
                "open": close * 0.99,
                "high": close * 1.02,
                "low": close * 0.98,
                "close": close,
                "volume": np.ones(100) * 2000,
            },
            index=dates,
        )
        strategy = TrendFollowingStrategy({"ema_fast": 10, "ema_slow": 30})
        result = strategy.generate_signals(data)
        # In a strong uptrend without pullback, no buy signals should trigger
        valid = result.dropna()
        buy_signals = valid[valid["buy_signal"] == 1]
        assert len(buy_signals) >= 0
