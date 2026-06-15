from pathlib import Path
from typing import Dict, List, Optional

import ccxt
import pandas as pd

from config.settings import SETTINGS
from src.exchange.base import BaseExchange, Balance, Order
from src.utils.logger import setup_logger

logger = setup_logger("binance", Path("logs"))


class BinanceExchange(BaseExchange):
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        testnet: bool = False,
    ) -> None:
        self._api_key = api_key or SETTINGS.exchange.api_key
        self._api_secret = api_secret or SETTINGS.exchange.api_secret

        config = {
            "apiKey": self._api_key,
            "secret": self._api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }

        if testnet:
            config["urls"] = {
                "api": {
                    "public": "https://testnet.binance.vision/api/v3",
                    "private": "https://testnet.binance.vision/api/v3",
                }
            }

        self._client = ccxt.binance(config)
        self._testnet = testnet

        try:
            self._client.load_markets()
            logger.info(
                "Conectado a Binance %s | %d mercados cargados",
                "TESTNET" if testnet else "LIVE",
                len(self._client.markets),
            )
        except Exception as e:
            logger.error("Error conectando a Binance: %s", e)
            raise

    def fetch_ohlcv(
        self, symbol: str, timeframe: str = "1h", limit: int = 500,
    ) -> pd.DataFrame:
        logger.info("Fetching %d %s candles for %s", limit, timeframe, symbol)
        raw = self._client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

        df = pd.DataFrame(
            raw,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df

    def fetch_ohlcv_range(
        self, symbol: str, timeframe: str = "4h", since: Optional[str] = None,
    ) -> pd.DataFrame:
        """Fetch OHLCV with pagination to get data from `since` to now."""
        from datetime import datetime, timezone

        tf_ms = {"4h": 4 * 3600 * 1000, "1h": 3600 * 1000, "1d": 86400 * 1000}
        step = tf_ms.get(timeframe, 4 * 3600 * 1000) * 1000

        if since is None:
            since_dt = datetime.now(timezone.utc).replace(
                year=datetime.now(timezone.utc).year - 2,
            )
        else:
            since_dt = pd.Timestamp(since).to_pydatetime()

        since_ms = int(since_dt.timestamp() * 1000)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        all_dfs: List[pd.DataFrame] = []
        total = 0
        while since_ms < now_ms:
            try:
                raw = self._client.fetch_ohlcv(
                    symbol, timeframe=timeframe, since=since_ms, limit=1000,
                )
            except Exception as e:
                logger.warning("Error fetching %s at %s: %s", symbol, since_ms, e)
                break
            if not raw:
                break
            df = pd.DataFrame(
                raw,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            all_dfs.append(df)
            total += len(df)
            since_ms = raw[-1][0] + 1
            if len(raw) < 1000:
                break

        if not all_dfs:
            return pd.DataFrame()

        result = pd.concat(all_dfs)
        result = result[~result.index.duplicated(keep="first")]
        result.sort_index(inplace=True)
        logger.info("Fetched %d %s candles for %s (%s → %s)",
                     total, timeframe, symbol, result.index[0], result.index[-1])
        return result

    def create_order(self, order: Order) -> str:
        params = {
            "symbol": order.symbol,
            "type": order.order_type,
            "side": order.side,
            "amount": order.quantity,
        }
        if order.order_type == "limit" and order.price is not None:
            params["price"] = order.price

        logger.info("Creando orden: %s", params)
        result = self._client.create_order(**params)
        order_id = result.get("id", "")
        logger.info("Orden creada: %s", result.get("status", "unknown"))
        return order_id

    def create_stop_loss_order(
        self, symbol: str, quantity: float, stop_price: float,
    ) -> str:
        return self._client.create_order(
            symbol=symbol,
            type="STOP_LOSS_LIMIT",
            side="sell",
            amount=quantity,
            price=stop_price,
            params={"stopPrice": stop_price},
        )

    def create_trailing_stop_order(
        self, symbol: str, quantity: float, activation_price: float, callback_rate: float,
    ) -> str:
        return self._client.create_order(
            symbol=symbol,
            type="TRAILING_STOP_MARKET",
            side="sell",
            amount=quantity,
            params={
                "activationPrice": activation_price,
                "callbackRate": callback_rate,
            },
        )

    def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:
        try:
            self._client.cancel_order(id=order_id, symbol=symbol)
            return True
        except Exception as e:
            logger.error("Error cancelando orden %s: %s", order_id, e)
            return False

    def fetch_balance(self) -> List[Balance]:
        raw = self._client.fetch_balance()
        balances = []
        for asset, data in raw.get("free", {}).items():
            free = data if isinstance(data, (int, float)) else 0.0
            locked = raw.get("used", {}).get(asset, 0.0)
            if free > 0 or locked > 0:
                balances.append(Balance(asset=asset, free=float(free), locked=float(locked)))
        return balances

    def fetch_open_orders(self, symbol: str) -> List[Order]:
        raw = self._client.fetch_open_orders(symbol=symbol)
        orders = []
        for o in raw:
            orders.append(
                Order(
                    symbol=o.get("symbol", symbol),
                    side=o.get("side", "buy"),
                    order_type=o.get("type", "limit"),
                    quantity=float(o.get("amount", 0)),
                    price=float(o.get("price", 0)) if o.get("price") else None,
                )
            )
        return orders

    def get_ticker(self, symbol: str) -> dict:
        return self._client.fetch_ticker(symbol)

    def fetch_tickers(self) -> Dict[str, dict]:
        return self._client.fetch_tickers()

    def fetch_all_usdt_pairs(self) -> List[str]:
        tickers = self.fetch_tickers()
        return [s for s in tickers if s.endswith("/USDT")]

    def fetch_24h_volume(self, symbol: str) -> float:
        ticker = self.get_ticker(symbol)
        return float(ticker.get("quoteVolume", 0) or 0)

    def fetch_top_usdt_pairs(
        self, n: int = 100, min_volume_usd: float = 1_000_000,
    ) -> List[str]:
        tickers = self.fetch_tickers()
        usdt = [(s, float(t.get("quoteVolume", 0) or 0))
                for s, t in tickers.items() if s.endswith("/USDT") and float(t.get("quoteVolume", 0) or 0) >= min_volume_usd]
        usdt.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in usdt[:n]]

    def fetch_multiple_ohlcv(
        self, symbols: List[str], timeframe: str = "4h", limit: int = 220,
    ) -> Dict[str, pd.DataFrame]:
        import concurrent.futures
        results: Dict[str, pd.DataFrame] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            fut = {s: pool.submit(self.fetch_ohlcv, s, timeframe, limit) for s in symbols}
            for s, f in fut.items():
                try:
                    results[s] = f.result(timeout=30)
                except Exception as e:
                    logger.error("Error fetching %s: %s", s, e)
        return results

    @property
    def is_testnet(self) -> bool:
        return self._testnet
