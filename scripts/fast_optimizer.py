"""Optimización rápida: barrido de parámetros sobre todos los pares."""
import sys, json
from pathlib import Path
from itertools import product
from concurrent.futures import ProcessPoolExecutor, as_completed
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from config.settings import SETTINGS
from src.data.loader import load_ohlcv_csv
from src.risk.manager import RiskManager, CapitalConfig, RiskConfig, StopConfig
from src.strategies.aggressive_trend import AggressiveTrendStrategy

CAPITAL = 100_000.0
DATA_DIR = SETTINGS.data_dir

# Load all pairs with >=4000 candles
all_data = {}
for f in sorted(DATA_DIR.glob("*_4h_2y.csv")):
    try:
        sym = f.stem.replace("_4h_2y", "").replace("_4h", "").replace("_", "/", 1)
        if "/" not in sym:
            sym = sym.replace("_", "/")
        df = load_ohlcv_csv(f)
        if len(df) >= 4000:
            all_data[sym] = df
    except Exception:
        pass

print(f"Cargados {len(all_data)} pares", flush=True)

def evaluate(params: tuple) -> dict:
    ef, es, adx, rp, sp, tp = params
    cfg = {"ema_fast": ef, "ema_slow": es, "adx_threshold": adx, "volume_threshold": 1.0, "pullback_mode": False}
    cap_cfg = CapitalConfig(initial=CAPITAL)
    ris_cfg = RiskConfig(per_trade=rp, max_drawdown=1.0, max_concurrent=1, min_interval_days=0)
    stp_cfg = StopConfig(loss_pct=sp, take_profit_pct=tp, break_even_trigger=0.01, trailing_activation=0.03, trailing_distance=0.02)

    returns, dds, trades = [], [], []
    for sym, df in all_data.items():
        try:
            strat = AggressiveTrendStrategy(cfg)
            sig = strat.generate_signals(df)
            rm = RiskManager(cap_cfg, ris_cfg, stp_cfg)
            peak = CAPITAL
            max_dd = 0.0
            for i in range(len(df)):
                ts = df.index[i]
                h, l, c = float(df.iloc[i]["high"]), float(df.iloc[i]["low"]), float(df.iloc[i]["close"])
                rm.update_positions(ts, h, l)
                if len(rm.positions) == 0 and sig.iloc[i]["buy_signal"]:
                    rm.open_position(ts, c)
                elif len(rm.positions) > 0 and sig.iloc[i]["exit_signal"]:
                    rm.close_all_positions(ts, c)
                peak = max(peak, rm.equity)
                dd = (peak - rm.equity) / peak * 100 if peak > 0 else 0
                max_dd = max(max_dd, dd)
            returns.append((rm.equity - CAPITAL) / CAPITAL * 100)
            dds.append(max_dd)
            trades.extend(rm.trades)
        except Exception:
            continue

    if not returns:
        return None

    avg_ret = float(np.mean(returns))
    avg_dd = float(np.mean(dds))
    n_trades = len(trades)
    wins = sum(1 for t in trades if t.pnl > 0) if trades else 0
    wr = wins / n_trades * 100 if n_trades > 0 else 0
    profitable = sum(1 for r in returns if r > 0)

    return {
        "ef": ef, "es": es, "adx": adx,
        "rp": rp, "sp": sp, "tp": tp,
        "ret": round(avg_ret, 2), "dd": round(avg_dd, 2),
        "score": round(avg_ret - avg_dd * 0.5, 2),
        "trades": n_trades, "wr": round(wr, 1),
        "pwr": round(profitable / len(returns) * 100, 1),
        "prof": profitable, "npairs": len(returns),
    }


def stage1_risk():
    """Optimize risk params with fixed EMA 5/20, ADX 20."""
    grid = list(product([5], [20], [20], [0.01, 0.02, 0.03, 0.04, 0.05], [0.01, 0.015, 0.02], [0.04, 0.06, 0.08, 0.10]))
    print(f"Etapa 1 (risk): {len(grid)} combos", flush=True)
    results = []
    with ProcessPoolExecutor(max_workers=6) as pool:
        for f in as_completed({pool.submit(evaluate, p): p for p in grid}):
            r = f.result()
            if r:
                results.append(r)
    results.sort(key=lambda x: x["score"], reverse=True)
    return results

def stage2_ema(best_risk: dict):
    """With best SL/TP/risk, optimize EMA params."""
    grid = list(product([3, 5, 8, 10, 12], [10, 15, 20, 30], [20],
                         [best_risk["rp"]], [best_risk["sp"]], [best_risk["tp"]]))
    print(f"Etapa 2 (EMA): {len(grid)} combos", flush=True)
    results = []
    with ProcessPoolExecutor(max_workers=6) as pool:
        for f in as_completed({pool.submit(evaluate, p): p for p in grid}):
            r = f.result()
            if r:
                results.append(r)
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def print_table(results, title):
    print(f"\n{'='*70}")
    print(f"  {title} — {len(all_data)} pares")
    print(f"{'='*70}")
    print(f"{'Score':<7} {'EMAs':<9} {'Risk':<7} {'SL':<7} {'TP':<7} {'Ret%':<8} {'DD%':<8} {'WR%':<6} {'Trds':<6}")
    print("-" * 70)
    for r in results[:15]:
        print(f"{r['score']:<7.1f} {str(r['ef'])+'/'+str(r['es']):<9s} {r['rp']:<7.0%} {r['sp']:<7.0%} {r['tp']:<7.0%} {r['ret']:<+8.2f} {r['dd']:<8.2f} {r['wr']:<6.1f} {r['trades']:<6d}")
    print("-" * 70)
    b = results[0]
    print(f"  MEJOR: EMA {b['ef']}/{b['es']}, Risk {b['rp']:.0%}, SL {b['sp']:.0%}, TP {b['tp']:.0%} | "
          f"Ret {b['ret']:+.2f}%, DD {b['dd']:.2f}%, WR {b['wr']:.1f}%, PairWR {b['pwr']:.1f}%")


def main():
    r1 = stage1_risk()
    print_table(r1, "TOP — ETAPA 1 (risk params)")

    best = r1[0]
    r2 = stage2_ema(best)
    print_table(r2, "TOP — ETAPA 2 (EMA params)")

    # Use best from both stages
    all_results = r1 + r2
    all_results.sort(key=lambda x: x["score"], reverse=True)
    b = all_results[0]

    print(f"\n  MEJOR GLOBAL:")
    print(f"    EMA {b['ef']}/{b['es']}, ADX {b['adx']}, Risk {b['rp']:.0%}, SL {b['sp']:.0%}, TP {b['tp']:.0%}")
    print(f"    Ret: {b['ret']:+.2f}%, DD: {b['dd']:.2f}%, WR: {b['wr']:.1f}%, PairWR: {b['pwr']:.1f}%")

    out = SETTINGS.data_dir.parent / "results" / "optimization_results.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "stage1": {"count": len(r1), "top": r1[:10]},
        "stage2": {"count": len(r2), "top": r2[:10]},
        "best": b,
    }, indent=2))
    print(f"\nGuardado en {out}")


if __name__ == "__main__":
    main()
