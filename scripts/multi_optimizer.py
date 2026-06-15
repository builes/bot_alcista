"""Optimización multi-par: busca parámetros que maximicen retorno mensual y minimicen DD."""
import sys
import json
from pathlib import Path
from itertools import product
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np

from config.settings import SETTINGS
from src.data.loader import load_ohlcv_csv
from src.risk.manager import RiskManager, CapitalConfig, RiskConfig, StopConfig
from src.strategies.aggressive_trend import AggressiveTrendStrategy
from src.utils.logger import setup_logger

logger = setup_logger("optimizer_multi", SETTINGS.logs_dir)
CAPITAL = 100_000.0

DATA_DIR = SETTINGS.data_dir
csv_files = sorted(DATA_DIR.glob("*_4h_2y.csv"))
all_data = {}
for f in csv_files:
    try:
        sym = f.stem.replace("_4h_2y", "").replace("_4h", "").replace("_", "/", 1)
        if "/" not in sym:
            sym = sym.replace("_", "/")
        df = load_ohlcv_csv(f)
        if len(df) >= 4000:
            all_data[sym] = df
    except Exception:
        pass

logger.info("Cargados %d pares con >= 4000 velas", len(all_data))


def run_config(ema_fast: int, ema_slow: int, adx: int, risk_pct: float, sl_pct: float, tp_pct: float) -> dict:
    capital_cfg = CapitalConfig(initial=CAPITAL)
    risk_cfg = RiskConfig(per_trade=risk_pct, max_drawdown=1.0, max_concurrent=1, min_interval_days=0)
    stop_cfg = StopConfig(loss_pct=sl_pct, take_profit_pct=tp_pct, break_even_trigger=0.01, trailing_activation=0.03, trailing_distance=0.02)

    total_returns = []
    total_drawdowns = []
    all_trades = []

    for sym, df in all_data.items():
        try:
            rm = RiskManager(capital_cfg, risk_cfg, stop_cfg)
            strategy = AggressiveTrendStrategy({"ema_fast": ema_fast, "ema_slow": ema_slow, "adx_threshold": adx, "volume_threshold": 1.0, "pullback_mode": False})
            signals = strategy.generate_signals(df)
            peak = CAPITAL
            max_dd = 0.0
            for i in range(len(df)):
                ts = df.index[i]
                row = df.iloc[i]
                h, l, c = float(row["high"]), float(row["low"]), float(row["close"])
                rm.update_positions(ts, h, l)
                sig = signals.iloc[i]
                if len(rm.positions) == 0 and sig["buy_signal"] == 1:
                    rm.open_position(ts, c)
                elif len(rm.positions) > 0 and sig["exit_signal"] == 1:
                    rm.close_all_positions(ts, c)
                eq = rm.equity
                peak = max(peak, eq)
                dd = (peak - eq) / peak * 100 if peak > 0 else 0
                max_dd = max(max_dd, dd)
            ret_pct = (rm.equity - CAPITAL) / CAPITAL * 100
            total_returns.append(ret_pct)
            total_drawdowns.append(max_dd)
            all_trades.extend(rm.trades)
        except Exception:
            continue

    if not total_returns:
        return {"error": True}

    avg_ret = np.mean(total_returns)
    avg_dd = np.mean(total_drawdowns)
    n_trades = len(all_trades)
    wins = sum(1 for t in all_trades if t.pnl > 0) if all_trades else 0
    wr = wins / n_trades * 100 if n_trades > 0 else 0

    n_pairs = len(total_returns)
    profitable = sum(1 for r in total_returns if r > 0)
    pair_wr = profitable / n_pairs * 100 if n_pairs > 0 else 0

    score = avg_ret - avg_dd * 0.5

    return {
        "ema_fast": ema_fast, "ema_slow": ema_slow, "adx": adx,
        "risk_pct": risk_pct, "sl_pct": sl_pct, "tp_pct": tp_pct,
        "avg_return_pct": round(avg_ret, 2),
        "avg_drawdown_pct": round(avg_dd, 2),
        "score": round(score, 2),
        "total_trades": n_trades,
        "win_rate_pct": round(wr, 1),
        "pair_win_rate_pct": round(pair_wr, 1),
        "profitable_pairs": profitable,
        "total_pairs": n_pairs,
    }


def main():
    param_grid = {
        "ema_fast": [3, 5, 8],
        "ema_slow": [15, 20, 30],
        "adx": [15, 20],
        "risk_pct": [0.02, 0.03, 0.04],
        "sl_pct": [0.01, 0.015, 0.02],
        "tp_pct": [0.04, 0.06, 0.08, 0.10],
    }

    keys = list(param_grid.keys())
    values = list(param_grid.values())
    total = 3 * 3 * 2 * 3 * 3 * 4  # 648 combos
    logger.info("Total combinaciones: %d", total)

    results = []
    done = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        fut_map = {}
        for combo in product(*values):
            params = dict(zip(keys, combo))
            fut = pool.submit(run_config, **params)
            fut_map[fut] = params
        for f in as_completed(fut_map):
            done += 1
            r = f.result()
            if r and "error" not in r:
                results.append(r)
            if done % 50 == 0:
                logger.info("Progreso: %d/%d", done, total)

    results.sort(key=lambda x: x["score"], reverse=True)

    print(f"\n{'='*70}")
    print(f"  OPTIMIZACIÓN MULTI-PAR ({len(all_data)} pares, {len(results)} completados)")
    print(f"{'='*70}")
    print(f"{'Score':<8} {'EMAs':<10} {'ADX':<5} {'Risk':<8} {'SL':<8} {'TP':<8} {'Ret%':<8} {'DD%':<8} {'WR%':<6} {'Trades':<8}")
    print("-" * 70)
    for r in results[:20]:
        ema = f"{r['ema_fast']}/{r['ema_slow']}"
        print(f"{r['score']:<8.1f} {ema:<10s} {r['adx']:<5d} {r['risk_pct']:<8.0%} {r['sl_pct']:<8.0%} {r['tp_pct']:<8.0%} {r['avg_return_pct']:<8.2f} {r['avg_drawdown_pct']:<8.2f} {r['win_rate_pct']:<6.1f} {r['total_trades']:<8d}")
    print("-" * 70)

    best = results[0]
    print(f"\n  MEJOR CONFIGURACIÓN:")
    print(f"    EMA fast/slow: {best['ema_fast']}/{best['ema_slow']}")
    print(f"    ADX: {best['adx']}, Risk: {best['risk_pct']:.0%}, SL: {best['sl_pct']:.0%}, TP: {best['tp_pct']:.0%}")
    print(f"    Retorno promedio: {best['avg_return_pct']:+.2f}%, DD: {best['avg_drawdown_pct']:.2f}%")
    print(f"    Win Rate: {best['win_rate_pct']:.1f}%, Pair WR: {best['pair_win_rate_pct']:.1f}%")
    print(f"    Trades totales: {best['total_trades']}")

    out = SETTINGS.data_dir.parent / "results" / "optimization_results.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "total_combinations": total,
        "completed": len(results),
        "best": best,
        "top_20": results[:20],
    }, indent=2, default=str))
    logger.info("Resultados guardados en %s", out)


if __name__ == "__main__":
    main()
