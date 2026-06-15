"""Descarga datos 4h de los top 80 pares USDT desde Binance."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from config.settings import SETTINGS
from src.exchange.binance_exchange import BinanceExchange
from src.utils.logger import setup_logger

logger = setup_logger("download", SETTINGS.logs_dir)
DATA_DIR = SETTINGS.data_dir
DATA_DIR.mkdir(parents=True, exist_ok=True)


def download_pair(exchange: BinanceExchange, symbol: str, limit: int = 1000) -> bool:
    fname = symbol.replace("/", "_") + "_4h.csv"
    path = DATA_DIR / fname
    if path.exists():
        logger.info("SKIP %s — ya existe", symbol)
        return True
    try:
        time.sleep(0.3)
        df = exchange.fetch_ohlcv(symbol, timeframe="4h", limit=limit)
        if df is None or df.empty:
            logger.warning("VACÍO %s", symbol)
            return False
        df.reset_index().to_csv(path, index=False)
        logger.info("OK %s → %d velas", symbol, len(df))
        return True
    except Exception as e:
        logger.error("ERROR %s: %s", symbol, e)
        return False


def main() -> None:
    ex = BinanceExchange(testnet=False)
    logger.info("Obteniendo top 80 pares USDT por volumen...")
    top = ex.fetch_top_usdt_pairs(n=80, min_volume_usd=500_000)
    logger.info("Total pares a descargar: %d", len(top))

    ok = 0
    fail = 0
    with ThreadPoolExecutor(max_workers=5) as pool:
        fut = {pool.submit(download_pair, ex, s): s for s in top}
        for f in as_completed(fut):
            if f.result():
                ok += 1
            else:
                fail += 1
    logger.info("Completado: %d OK, %d FAIL", ok, fail)


if __name__ == "__main__":
    main()
