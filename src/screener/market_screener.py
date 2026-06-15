from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

from src.exchange.binance_exchange import BinanceExchange
from src.utils.logger import setup_logger

logger = setup_logger("screener", Path("logs"))


@dataclass
class ScreenedPair:
    symbol: str
    close_price: float
    volume_24h_usd: float
    trend_score: float
    adx: float
    di_plus: float
    di_minus: float
    ema_fast: float
    ema_slow: float
    is_bull: bool


class MarketScreener:
    def __init__(
        self,
        exchange: BinanceExchange,
        min_volume_usd: float = 1_000_000,
        max_candidates: int = 100,
        max_results: int = 10,
        ema_fast: int = 50,
        ema_slow: int = 200,
        adx_threshold: float = 20.0,
    ) -> None:
        self._exchange = exchange
        self._min_volume = min_volume_usd
        self._max_candidates = max_candidates
        self._max_results = max_results
        self._ema_fast = ema_fast
        self._ema_slow = ema_slow
        self._adx_threshold = adx_threshold

    def scan(self) -> List[ScreenedPair]:
        tickers = self._exchange.fetch_tickers()
        usdt_pairs = [(s, t) for s, t in tickers.items()
                      if s.endswith("/USDT") and isinstance(t, dict)]

        usdt_pairs.sort(key=lambda x: float(x[1].get("quoteVolume", 0) or 0), reverse=True)
        top_candidates = usdt_pairs[:self._max_candidates]

        results: List[ScreenedPair] = []
        for symbol, ticker in top_candidates:
            volume = float(ticker.get("quoteVolume", 0) or 0)
            price = float(ticker.get("last", 0) or 0)
            if volume < self._min_volume:
                continue

            pair_info = self._check_trend(symbol)
            if pair_info is None:
                continue

            results.append(pair_info)

        results.sort(key=lambda x: x.trend_score, reverse=True)
        logger.info("Screener: %d/%d pares en tendencia alcista", len(results), len(top_candidates))
        return results[:self._max_results]

    def _check_trend(self, symbol: str) -> Optional[ScreenedPair]:
        try:
            df = self._exchange.fetch_ohlcv(symbol, "1d", limit=self._ema_slow + 20)
            if df is None or len(df) < self._ema_slow + 1:
                return None
        except Exception:
            return None

        ema_fast = self._ema(df["close"], self._ema_fast)
        ema_slow = self._ema(df["close"], self._ema_slow)
        adx, di_plus, di_minus = self._adx(df["high"], df["low"], df["close"], 14)

        last_fast = float(ema_fast.iloc[-1])
        last_slow = float(ema_slow.iloc[-1])
        last_adx = float(adx.iloc[-1])
        last_di_plus = float(di_plus.iloc[-1])
        last_di_minus = float(di_minus.iloc[-1])
        last_close = float(df["close"].iloc[-1])

        is_bull = (
            last_fast > last_slow
            and last_adx >= self._adx_threshold
            and last_di_plus > last_di_minus
            and last_close > last_slow
        )

        score = 0.0
        if is_bull:
            score += (last_fast / last_slow - 1.0) * 100.0
            score += (last_adx - self._adx_threshold) * 0.1
            score += (last_di_plus - last_di_minus) * 0.05

        price = float(df["close"].iloc[-1])
        volume = float(self._exchange.fetch_tickers().get(symbol, {}).get("quoteVolume", 0) or 0)

        return ScreenedPair(
            symbol=symbol,
            close_price=price,
            volume_24h_usd=volume,
            trend_score=max(0.0, score),
            adx=last_adx,
            di_plus=last_di_plus,
            di_minus=last_di_minus,
            ema_fast=last_fast,
            ema_slow=last_slow,
            is_bull=is_bull,
        )

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
