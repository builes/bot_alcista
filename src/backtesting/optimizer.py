import itertools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Type

from config.settings import Settings
from src.backtesting.engine import BacktestEngine, BacktestResult
from src.strategies.base import BaseStrategy
from src.strategies.trend_following import TrendFollowingStrategy
from src.utils.logger import setup_logger

logger = setup_logger("optimizer", Path("logs"))


@dataclass
class OptimizerConfig:
    param_grid: Dict[str, List[float]] = field(default_factory=dict)
    maximize: str = "sharpe_ratio"
    min_trades: int = 10
    max_drawdown_limit: float = 30.0


class Optimizer:
    def __init__(
        self,
        settings: Settings,
        config: OptimizerConfig,
        strategy_class: Type[BaseStrategy] = TrendFollowingStrategy,
        risk_override: Optional[dict] = None,
        stop_override: Optional[dict] = None,
    ) -> None:
        self._settings = settings
        self._config = config
        self._strategy_class = strategy_class
        self._risk_override = risk_override or {}
        self._stop_override = stop_override or {}

    def optimize(self, data_path: Path) -> Tuple[Dict, BacktestResult]:
        keys = list(self._config.param_grid.keys())
        values = list(self._config.param_grid.values())
        combinations = list(itertools.product(*values))

        best_score = float("-inf")
        best_params = {}
        best_result = None
        total = len(combinations)

        logger.info("Starting optimization over %d parameter combinations", total)

        for i, combo in enumerate(combinations, 1):
            params = dict(zip(keys, combo))
            try:
                engine = BacktestEngine(
                    self._settings,
                    strategy_params=params,
                    strategy_class=self._strategy_class,
                    risk_override=self._risk_override,
                    stop_override=self._stop_override,
                )
                result = engine.run(data_path)
                score = result.metrics.get(self._config.maximize, float("-inf"))
                trades = result.metrics.get("total_trades", 0)
                dd = result.metrics.get("max_drawdown_pct", 0)

                if (
                    score > best_score
                    and trades >= self._config.min_trades
                    and dd <= self._config.max_drawdown_limit
                ):
                    best_score = score
                    best_params = params
                    best_result = result
            except Exception as e:
                logger.warning("Params %s failed: %s", params, e)

            if i % 10 == 0 or i == total:
                logger.info("Progress: %d/%d (%.1f%%)", i, total, i / total * 100)

        logger.info(
            "Optimization complete — best %s=%.4f with params=%s",
            self._config.maximize, best_score, best_params,
        )
        return best_params, best_result
