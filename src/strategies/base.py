from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class Signal:
    timestamp: pd.Timestamp
    action: str  # "BUY" | "SELL" | "HOLD"
    price: float
    confidence: float = 1.0
    metadata: Optional[dict] = None


class BaseStrategy(ABC):
    def __init__(self, params: dict) -> None:
        self.params = params
        self._signals: list[Signal] = []

    @abstractmethod
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        ...

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        ...

    def get_signals(self) -> list[Signal]:
        return self._signals

    def reset(self) -> None:
        self._signals.clear()
