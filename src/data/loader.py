from pathlib import Path
from typing import Optional

import pandas as pd

from src.utils.logger import setup_logger

logger = setup_logger("data_loader", Path("logs"))


REQUIRED_COLUMNS = {"timestamp", "open", "high", "low", "close", "volume"}


def load_ohlcv_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")

    df = pd.read_csv(path)

    missing = REQUIRED_COLUMNS - set(df.columns.str.lower())
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df.columns = df.columns.str.lower()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df.set_index("timestamp", inplace=True)
    df.sort_index(inplace=True)

    df = df.astype({
        "open": "float64",
        "high": "float64",
        "low": "float64",
        "close": "float64",
        "volume": "float64",
    })

    _validate_data(df)

    logger.info(
        "Loaded %d rows from %s | %s → %s",
        len(df), path.name, df.index[0], df.index[-1],
    )
    return df


def _validate_data(df: pd.DataFrame) -> None:
    if df.isnull().any().any():
        logger.warning("Data contains NaN values — forward-filling")
        df.fillna(method="ffill", inplace=True)

    if (df["low"] > df["high"]).any():
        raise ValueError("Low > High detected in data")

    if (df["close"] <= 0).any():
        raise ValueError("Non-positive close prices detected")


def resample(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    return df.resample(timeframe).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
