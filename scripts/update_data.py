"""Actualiza datos 4h de top 80 pares USDT hasta el día de hoy."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from config.settings import SETTINGS
from src.exchange.binance_exchange import BinanceExchange
from src.utils.logger import setup_logger

logger = setup_logger("update_data", SETTINGS.logs_dir)
DATA_DIR = SETTINGS.data_dir
DATA_DIR.mkdir(parents=True, exist_ok=True)


def update_pair(exchange: BinanceExchange, symbol: str) -> bool:
    fname = symbol.replace("/", "_") + "_4h_2y.csv"
    path = DATA_DIR / fname

    if path.exists():
        try:
            existing = pd.read_csv(path, parse_dates=["timestamp"])
            last_ts = existing["timestamp"].iloc[-1]
            since_str = last_ts.strftime("%Y-%m-%d %H:%M:%S")
            logger.info("Actualizando %s desde %s", symbol, since_str)
        except Exception as e:
            logger.warning("Error leyendo %s: %s, redescargando...", fname, e)
            since_str = None
    else:
        since_str = None

    try:
        time.sleep(0.3)
        df = exchange.fetch_ohlcv_range(symbol, timeframe="4h", since=since_str)
        if df is None or df.empty:
            logger.warning("VACÍO %s", symbol)
            return False

        if path.exists() and since_str is not None:
            combined = pd.concat([existing.set_index("timestamp"), df])
            combined = combined[~combined.index.duplicated(keep="last")]
            combined.sort_index(inplace=True)
            combined.reset_index().to_csv(path, index=False)
        else:
            df.reset_index().to_csv(path, index=False)

        logger.info("OK %s → %d velas totales", symbol, len(pd.read_csv(path)))
        return True
    except Exception as e:
        logger.error("ERROR %s: %s", symbol, e)
        return False


def main() -> None:
    ex = BinanceExchange(testnet=False)
    logger.info("Conectado a Binance LIVE. Actualizando datos hasta %s",
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    # Collect all symbols from existing files + top 80
    existing_symbols = set()
    for f in DATA_DIR.glob("*_4h_2y.csv"):
        sym = f.stem.replace("_4h_2y", "").replace("_", "/", 1)
        if "/" not in sym:
            sym = sym.replace("_", "/")
        existing_symbols.add(sym)

    logger.info("Pares existentes: %d", len(existing_symbols))

    # Also get top 80 to ensure we have the latest pairs
    try:
        top = ex.fetch_top_usdt_pairs(n=80, min_volume_usd=500_000)
        logger.info("Top 80 pares actuales obtenidos")
    except Exception as e:
        logger.warning("Error obteniendo top 80: %s, usando existentes", e)
        top = list(existing_symbols)

    all_symbols = sorted(set(top) | existing_symbols)
    logger.info("Total pares a procesar: %d", len(all_symbols))

    ok = fail = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        fut = {pool.submit(update_pair, ex, s): s for s in all_symbols}
        for f in as_completed(fut):
            if f.result():
                ok += 1
            else:
                fail += 1

    logger.info("Completado: %d OK, %d FAIL", ok, fail)

    # Verify: check latest timestamp across files
    newest = datetime.min.replace(tzinfo=timezone.utc)
    oldest = datetime.now(timezone.utc)
    for f in DATA_DIR.glob("*_4h_2y.csv"):
        try:
            df = pd.read_csv(f, parse_dates=["timestamp"])
            if len(df) > 0:
                t = df["timestamp"].iloc[-1]
                if pd.api.types.is_datetime64_any_dtype(t):
                    t = t.to_pydatetime()
                if hasattr(t, 'tzinfo') and t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                newest = max(newest, t)
                t0 = df["timestamp"].iloc[0]
                if hasattr(t0, 'tzinfo') and t0.tzinfo is None:
                    t0 = t0.replace(tzinfo=timezone.utc)
                oldest = min(oldest, t0)
        except Exception:
            pass

    logger.info("Rango de datos: %s → %s", oldest, newest)


if __name__ == "__main__":
    main()
