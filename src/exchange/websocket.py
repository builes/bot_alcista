import asyncio
import json
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

import pandas as pd

from src.utils.logger import setup_logger

logger = setup_logger("websocket", Path("logs"))


class BinanceWebSocket:
    def __init__(self, symbols: List[str], timeframe: str = "4h") -> None:
        self._timeframe = self._normalize_timeframe(timeframe)
        streams = [f"{s.lower().replace('/', '')}@kline_{self._timeframe}" for s in symbols]
        url = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
        self._url = url
        self._symbols = symbols
        self._candles: Dict[str, Dict] = {}
        self._callbacks: List[Callable] = []
        self._running = False
        self._max_symbols = 1024

    def _normalize_timeframe(self, tf: str) -> str:
        mapping = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
                   "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h",
                   "8h": "8h", "12h": "12h", "1d": "1d"}
        return mapping.get(tf, "4h")

    def on_candle(self, callback: Callable) -> None:
        self._callbacks.append(callback)

    async def start(self) -> None:
        import websockets
        self._running = True
        logger.info("WebSocket conectando a Binance (%d streams)", len(self._symbols))

        async for ws in websockets.connect(self._url, ping_interval=20):
            try:
                async for raw in ws:
                    if not self._running:
                        break
                    data = json.loads(raw)
                    self._process_message(data)
            except Exception as e:
                logger.warning("WebSocket error: %s — reconectando...", e)
                await asyncio.sleep(5)

    def stop(self) -> None:
        self._running = False

    def get_latest_candle(self, symbol: str) -> Optional[pd.Series]:
        raw = self._candles.get(symbol)
        if raw is None:
            return None
        return pd.Series({
            "timestamp": pd.Timestamp(raw["t"], unit="ms"),
            "open": float(raw["o"]),
            "high": float(raw["h"]),
            "low": float(raw["l"]),
            "close": float(raw["c"]),
            "volume": float(raw["v"]),
        })

    def _process_message(self, data: dict) -> None:
        if "data" not in data:
            return
        d = data["data"]
        if d.get("e") != "kline":
            return
        k = d["k"]
        symbol = d["s"]
        if k.get("x", False):
            self._candles[symbol] = k
            candle_series = pd.Series({
                "timestamp": pd.Timestamp(k["t"], unit="ms"),
                "open": float(k["o"]),
                "high": float(k["h"]),
                "low": float(k["l"]),
                "close": float(k["c"]),
                "volume": float(k["v"]),
            })
            for cb in self._callbacks:
                try:
                    cb(symbol, candle_series)
                except Exception as e:
                    logger.error("WebSocket callback error: %s", e)
