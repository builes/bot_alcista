import numpy as np
import pandas as pd

from src.strategies.base import BaseStrategy, Signal


class AggressiveTrendStrategy(BaseStrategy):
    def __init__(self, params: dict) -> None:
        defaults = {
            "ema_fast": 10,
            "ema_slow": 30,
            "adx_period": 14,
            "adx_threshold": 20.0,
            "volume_window": 20,
            "volume_threshold": 0.8,
            "pullback_mode": True,
            "pullback_tolerance": 0.03,
        }
        defaults.update(params)
        super().__init__(defaults)

    def _filter_bull_market(self, df: pd.DataFrame) -> pd.Series:
        bull_ma = self.params.get("bull_market_ma", 0)
        if bull_ma <= 0:
            return pd.Series(True, index=df.index)
        ma = self._ema(df["close"], bull_ma)
        return df["close"] > ma

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()

        out["ema_fast"] = self._ema(out["close"], self.params["ema_fast"])
        out["ema_slow"] = self._ema(out["close"], self.params["ema_slow"])

        adx_series, di_plus, di_minus = self._adx(
            out["high"], out["low"], out["close"], self.params["adx_period"],
        )
        out["adx"] = adx_series
        out["di_plus"] = di_plus
        out["di_minus"] = di_minus

        vol_window = self.params["volume_window"]
        out["volume_sma"] = out["volume"].rolling(window=vol_window).mean()
        out["volume_ratio"] = out["volume"] / out["volume_sma"].replace(0, np.nan)

        return out

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self.calculate_indicators(df)
        p = self.params

        df["signal"] = 0

        bull_trend = (df["ema_fast"] > df["ema_slow"]) & (df["adx"] > p["adx_threshold"])
        bullish_momentum = df["di_plus"] > df["di_minus"]
        above_slow = df["close"] > df["ema_slow"]
        volume_ok = df["volume_ratio"] >= p["volume_threshold"]

        if p.get("pullback_mode", True):
            near_ema = df["low"] <= df["ema_fast"] * (1 + p["pullback_tolerance"])
            bounce = (
                (df["close"] > df["open"])
                & (df["low"] <= df["ema_fast"])
                & (df["close"] > df["ema_fast"])
            )
            entry_ok = near_ema & bounce
        else:
            entry_ok = pd.Series(True, index=df.index)

        bull_filter = self._filter_bull_market(df)

        df["buy_signal"] = (
            bull_trend
            & bullish_momentum
            & above_slow
            & volume_ok
            & entry_ok
            & bull_filter
        ).astype(int)

        df["exit_signal"] = (
            (df["ema_fast"] < df["ema_slow"])
            | (df["di_plus"] < df["di_minus"])
        ).astype(int)

        return df

    def _ema(self, series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    def _adx(
        self, high: pd.Series, low: pd.Series, close: pd.Series, period: int,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        prev_close = close.shift(1)

        tr = pd.concat([
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)

        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        plus_dm = pd.Series(
            np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
            index=high.index,
        )
        minus_dm = pd.Series(
            np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
            index=high.index,
        )

        tr_smooth = self._ema(tr, period)
        plus_smooth = self._ema(plus_dm, period)
        minus_smooth = self._ema(minus_dm, period)

        di_plus = 100.0 * plus_smooth / tr_smooth.replace(0, np.nan)
        di_minus = 100.0 * minus_smooth / tr_smooth.replace(0, np.nan)

        dx = 100.0 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
        adx = self._ema(dx, period)

        return adx, di_plus, di_minus
