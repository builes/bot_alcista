import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env_float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)))


def _env_int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))


def _env_str(key: str, default: str) -> str:
    return os.getenv(key, default)


def _env_list(key: str, default: str) -> List[str]:
    raw = os.getenv(key, default)
    return [s.strip() for s in raw.split(",") if s.strip()]


@dataclass(frozen=True)
class CapitalConfig:
    initial: float = _env_float("INITIAL_CAPITAL", 100_000.0)


@dataclass(frozen=True)
class RiskConfig:
    per_trade: float = _env_float("RISK_PER_TRADE", 0.01)
    max_drawdown: float = _env_float("MAX_DRAWDOWN", 0.20)
    max_concurrent: int = _env_int("MAX_CONCURRENT_POSITIONS", 3)
    min_interval_days: int = _env_int("MIN_TRADE_INTERVAL_DAYS", 3)


@dataclass(frozen=True)
class StopConfig:
    loss_pct: float = _env_float("STOP_LOSS_PCT", 0.02)
    take_profit_pct: float = _env_float("TAKE_PROFIT_PCT", 0.06)
    break_even_trigger: float = _env_float("BREAK_EVEN_TRIGGER_PCT", 0.01)
    trailing_activation: float = _env_float("TRAILING_ACTIVATION_PCT", 0.015)
    trailing_distance: float = _env_float("TRAILING_DISTANCE_PCT", 0.015)


@dataclass(frozen=True)
class StrategyConfig:
    ema_fast: int = _env_int("EMA_FAST", 50)
    ema_slow: int = _env_int("EMA_SLOW", 200)
    adx_period: int = _env_int("ADX_PERIOD", 14)
    adx_threshold: float = _env_float("ADX_THRESHOLD", 25.0)
    volume_window: int = _env_int("VOLUME_WINDOW", 20)
    volume_threshold: float = _env_float("VOLUME_THRESHOLD", 1.0)
    pullback_tolerance: float = _env_float("PULLBACK_TOLERANCE", 0.01)


@dataclass(frozen=True)
class ScreenerConfig:
    min_volume_usd: float = _env_float("MIN_VOLUME_USD", 1_000_000)
    max_candidates: int = _env_int("MAX_CANDIDATES", 100)
    max_results: int = _env_int("MAX_RESULTS", 10)
    trend_ema_fast: int = _env_int("TREND_EMA_FAST", 50)
    trend_ema_slow: int = _env_int("TREND_EMA_SLOW", 200)
    trend_adx: float = _env_float("TREND_ADX_THRESHOLD", 20.0)


@dataclass(frozen=True)
class ExchangeConfig:
    name: str = _env_str("EXCHANGE_NAME", "binance")
    api_key: str = _env_str("EXCHANGE_API_KEY", "")
    api_secret: str = _env_str("EXCHANGE_API_SECRET", "")
    symbols: List[str] = field(default_factory=lambda: _env_list("SYMBOLS", "BTC/USDT,ETH/USDT"))
    timeframe: str = _env_str("TIMEFRAME", "4h")


@dataclass(frozen=True)
class Settings:
    capital: CapitalConfig = field(default_factory=CapitalConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    stops: StopConfig = field(default_factory=StopConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    screener: ScreenerConfig = field(default_factory=ScreenerConfig)
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)

    @property
    def data_dir(self) -> Path:
        return BASE_DIR / "data"

    @property
    def logs_dir(self) -> Path:
        return BASE_DIR / "logs"


SETTINGS = Settings()
