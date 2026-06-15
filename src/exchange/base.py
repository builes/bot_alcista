from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd


@dataclass
class Order:
    symbol: str
    side: str  # "buy" | "sell"
    order_type: str  # "market" | "limit"
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None


@dataclass
class Balance:
    asset: str
    free: float
    locked: float


class BaseExchange(ABC):
    @abstractmethod
    def fetch_ohlcv(
        self, symbol: str, timeframe: str, limit: int = 500,
    ) -> pd.DataFrame:
        ...

    @abstractmethod
    def create_order(self, order: Order) -> str:
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        ...

    @abstractmethod
    def fetch_balance(self) -> List[Balance]:
        ...

    @abstractmethod
    def fetch_open_orders(self, symbol: str) -> List[Order]:
        ...
