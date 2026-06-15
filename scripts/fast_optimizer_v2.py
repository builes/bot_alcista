"""Optimización rápida v2: métricas corregidas (sin compounding ficticio)."""
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

all_data = {}
for f in sorted(DATA_DIR.glob("*_4h_2y.csv")):
    try:
        sym = f.stem.replace("_4h_2y", "").replace("_4h", "").replace("_", "/", 1)
        if "/" not in sym: sym = sym.replace("_", "/")
        df = load_ohlcv_csv(f)
        if len(df) >= 4000: all_data[sym] = df
    except Exception: pass
print(f"Cargados {len(all_data)} pares", flush=True)


def evaluate(params: tuple) -> dict:
    ef, es, adx, rp, sp, tp = params
    cfg = {"ema_fast": ef, "ema_slow": es, "adx_threshold": adx, "volume_threshold": 1.0, "pullback_mode": False}

    pair_metrics = []
    for sym, df in all_data.items():
        try:
            strat = AggressiveTrendStrategy(cfg)
            sig = strat.generate_signals(df)
            # Per-trade fixed risk (no compounding)
            cap_cfg = CapitalConfig(initial=CAPITAL)
            ris_cfg = RiskConfig(per_trade=rp, max_drawdown=1.0, max_concurrent=1, min_interval_days=0)
            stp_cfg = StopConfig(loss_pct=sp, take_profit_pct=tp, break_even_trigger=0.01, trailing_activation=0.03, trailing_distance=0.02)
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

            trades = rm.trades
            if not trades: continue

            ret_pct = (rm.equity - CAPITAL) / CAPITAL * 100
            n_trades = len(trades)
            wins = sum(1 for t in trades if t.pnl > 0)
            losses = sum(1 for t in trades if t.pnl <= 0)
            wr = wins / n_trades * 100 if n_trades > 0 else 0
            avg_win = np.mean([t.pnl_pct for t in trades if t.pnl > 0]) if wins > 0 else 0
            avg_loss = np.mean([t.pnl_pct for t in trades if t.pnl <= 0]) if losses > 0 else 0
            expectancy = (wr/100 * avg_win + (1-wr/100) * avg_loss) if avg_loss else 0

            pair_metrics.append({
                "ret": ret_pct, "dd": max_dd, "trades": n_trades,
                "wr": wr, "avg_win": avg_win, "avg_loss": avg_loss,
                "expectancy": expectancy,
            })
        except Exception: continue

    if len(pair_metrics) < 10: return None

    avg_ret = np.mean([p["ret"] for p in pair_metrics])
    avg_dd = np.mean([p["dd"] for p in pair_metrics])
    avg_wr = np.mean([p["wr"] for p in pair_metrics])
    total_trades = sum(p["trades"] for p in pair_metrics)
    profitable = sum(1 for p in pair_metrics if p["ret"] > 0)
    avg_expectancy = np.mean([p["expectancy"] for p in pair_metrics])
    sharpe_like = (avg_ret / avg_dd * 100) if avg_dd > 0.1 else 0

    # Score: maximize return per DD, weighted by pair WR
    score = avg_ret * (profitable / len(pair_metrics)) / max(avg_dd, 0.1)

    return {
        "ef": ef, "es": es, "adx": adx,
        "rp": rp, "sp": sp, "tp": tp,
        "ret": round(avg_ret, 2), "dd": round(avg_dd, 2),
        "score": round(score, 2), "sharpe": round(sharpe_like, 2),
        "trades": total_trades, "wr": round(avg_wr, 1),
        "pwr": round(profitable / len(pair_metrics) * 100, 1),
        "expectancy": round(avg_expectancy, 4),
        "prof": profitable, "npairs": len(pair_metrics),
    }


def run_stage(grid, label):
    print(f"\n{label}: {len(grid)} combos", flush=True)
    results = []
    with ProcessPoolExecutor(max_workers=6) as pool:
        fut_map = {pool.submit(evaluate, p): p for p in grid}
        done = 0
        for f in as_completed(fut_map):
            done += 1
            r = f.result()
            if r: results.append(r)
            if done % 20 == 0: print(f"  {done}/{len(grid)}", flush=True)
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def print_table(results, title):
    print(f"\n{'='*75}")
    print(f"  {title} — {len(all_data)} pares")
    print(f"{'='*75}")
    hdr = f"{'Score':<8} {'EMAs':<9} {'Risk':<7} {'SL':<7} {'TP':<7} {'Ret%':<8} {'DD%':<8} {'WR%':<6} {'Exp':<9} {'Trds':<6}"
    print(hdr)
    print("-" * 75)
    for r in results[:15]:
        print(f"{r['score']:<8.1f} {str(r['ef'])+'/'+str(r['es']):<9s} {r['rp']:<7.0%} {r['sp']:<7.0%} {r['tp']:<7.0%} {r['ret']:<+8.2f} {r['dd']:<8.2f} {r['wr']:<6.1f} {r['expectancy']:<+9.4f} {r['trades']:<6d}")


def main():
    # Stage 1: optimize risk mgmt with EMA 5/20
    g1 = list(product([5], [20], [20],
                       [0.01, 0.02, 0.03, 0.04],
                       [0.01, 0.015, 0.02],
                       [0.04, 0.06, 0.08, 0.10]))
    r1 = run_stage(g1, "Etapa 1 — Risk params (EMA 5/20)")
    print_table(r1, "TOP RISK PARAMS")

    best_r = r1[0]
    # Stage 2: optimize EMAs with best risk params
    g2 = list(product([3, 5, 8, 10, 12], [10, 15, 20, 30], [20],
                       [best_r["rp"]], [best_r["sp"]], [best_r["tp"]]))
    r2 = run_stage(g2, "Etapa 2 — EMA params")
    print_table(r2, "TOP EMA PARAMS")

    all_r = sorted(r1 + r2, key=lambda x: x["score"], reverse=True)
    b = all_r[0]

    print(f"\n{'='*75}")
    print(f"  MEJOR GLOBAL:")
    print(f"  EMA {b['ef']}/{b['es']}, ADX {b['adx']}, Risk {b['rp']:.0%}, SL {b['sp']:.0%}, TP {b['tp']:.0%}")
    print(f"  Ret: {b['ret']:+.2f}% | DD: {b['dd']:.2f}% | Sharpe: {b['sharpe']:.2f} | Score: {b['score']:.1f}")
    print(f"  Win Rate: {b['wr']:.1f}% | Expectancy: {b['expectancy']:+.4f}% | Pair WR: {b['pwr']:.1f}% ({b['prof']}/{b['npairs']})")
    print(f"{'='*75}")

    out = SETTINGS.data_dir.parent / "results" / "optimization_v2.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "stage1_count": len(r1), "stage2_count": len(r2),
        "best": b, "top_10": all_r[:10],
    }, indent=2))
    print(f"\nGuardado en {out}")


if __name__ == "__main__":
    main()
