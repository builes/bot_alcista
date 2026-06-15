import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from config.settings import Settings, CapitalConfig, RiskConfig, StopConfig
from src.backtesting.engine import BacktestEngine


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=300, freq="D")
    trend = np.linspace(100, 150, 300) + np.random.normal(0, 2, 300)
    df = pd.DataFrame(
        {
            "timestamp": dates,
            "open": trend + np.random.uniform(-1, 1, 300),
            "high": trend + np.random.uniform(0, 2, 300),
            "low": trend - np.random.uniform(0, 2, 300),
            "close": trend,
            "volume": np.random.uniform(1000, 5000, 300),
        }
    )
    path = tmp_path / "test_data.csv"
    df.to_csv(path, index=False)
    return path


@pytest.fixture
def settings() -> Settings:
    return Settings(
        capital=CapitalConfig(initial=100_000.0),
        risk=RiskConfig(per_trade=0.01, max_drawdown=0.20, max_concurrent=3, min_interval_days=0),
        stops=StopConfig(loss_pct=0.02, take_profit_pct=0.06, break_even_trigger=0.01,
                         trailing_activation=0.015, trailing_distance=0.015),
    )


class TestBacktestEngine:
    def test_backtest_runs_and_returns_metrics(self, settings: Settings, sample_csv: Path) -> None:
        engine = BacktestEngine(settings)
        result = engine.run(sample_csv)
        assert result.metrics is not None
        assert "total_return" in result.metrics
        assert "sharpe_ratio" in result.metrics
        assert "profit_factor" in result.metrics
        assert "total_trades" in result.metrics

    def test_backtest_returns_trades(self, settings: Settings, sample_csv: Path) -> None:
        engine = BacktestEngine(settings)
        result = engine.run(sample_csv)
        assert isinstance(result.trades, list)
