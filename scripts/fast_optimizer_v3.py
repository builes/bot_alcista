"""Optimización basada en métricas por trade (sin compounding)."""
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

    per_pair_ret, per_pair_dd, per_pair_trades = [], [], []
    all_pnl_pct = []
    all_max_dd = []
    all_trades_count = 0
    n_profitable = 0

    for sym, df in all_data.items():
        try:
            strat = AggressiveTrendStrategy(cfg)
            sig = strat.generate_signals(df)

            cap_cfg = CapitalConfig(initial=CAPITAL)
            ris_cfg = RiskConfig(per_trade=rp, max_drawdown=1.0, max_concurrent=1, min_interval_days=0)
            stp_cfg = StopConfig(loss_pct=sp, take_profit_pct=tp, break_even_trigger=0.01, trailing_activation=0.03, trailing_distance=0.02)
            rm = RiskManager(cap_cfg, ris_cfg, stp_cfg)

            for i in range(len(df)):
                ts = df.index[i]
                h, l, c = float(df.iloc[i]["high"]), float(df.iloc[i]["low"]), float(df.iloc[i]["close"])
                rm.update_positions(ts, h, l)
                if len(rm.positions) == 0 and sig.iloc[i]["buy_signal"]:
                    rm.open_position(ts, c)
                elif len(rm.positions) > 0 and sig.iloc[i]["exit_signal"]:
                    rm.close_all_positions(ts, c)

            trades = [t for t in rm.trades if t.pnl_pct is not None and t.pnl_pct != 0]
            if not trades: continue

            pnl_pcts = [t.pnl_pct for t in trades]
            all_pnl_pct.extend(pnl_pcts)
            all_trades_count += len(trades)

            ret_pct = float(np.sum(pnl_pcts))
            pnl_values = [t.pnl for t in trades if t.pnl is not None]
            if pnl_values:
                cumulative = np.cumsum(pnl_values)
                peak = np.maximum.accumulate(cumulative)
                dd = np.max((peak - cumulative) / (CAPITAL + peak) * 100)
            else:
                dd = 0

            per_pair_ret.append(ret_pct)
            per_pair_dd.append(dd)
            per_pair_trades.append(len(trades))
            if ret_pct > 0:
                n_profitable += 1

        except Exception:
            continue

    if len(per_pair_ret) < 10:
        return None

    # Per-trade metrics
    ret_array = np.array(all_pnl_pct)
    avg_trade_ret = float(np.mean(ret_array))
    median_trade_ret = float(np.median(ret_array))
    std_trade = float(np.std(ret_array))
    sharpe_per_trade = avg_trade_ret / std_trade * np.sqrt(365) if std_trade > 1e-10 else 0

    wins = ret_array[ret_array > 0]
    losses = ret_array[ret_array <= 0]
    wr = len(wins) / len(ret_array) * 100
    avg_win = float(np.mean(wins)) if len(wins) > 0 else 0
    avg_loss = float(np.mean(losses)) if len(losses) > 0 else 0
    expectancy = (wr / 100 * avg_win + (1 - wr / 100) * avg_loss)

    # R:R ratio
    rr = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    # Pair-level
    avg_pair_ret = float(np.mean(per_pair_ret))
    avg_pair_dd = float(np.mean(per_pair_dd))
    max_pair_dd = float(np.max(per_pair_dd))
    pair_wr = n_profitable / len(per_pair_ret) * 100

    # Score: maximize per-trade Sharpe × pair consistency / drawdown
    consistency = (n_profitable / len(per_pair_ret))
    score = sharpe_per_trade * consistency * 10000 / max(avg_pair_dd, 0.1)

    return {
        "ef": ef, "es": es, "adx": adx,
        "rp": rp, "sp": sp, "tp": tp,
        "score": round(score, 1),
        "avg_trade_ret%": round(avg_trade_ret, 4),
        "avg_pair_ret%": round(avg_pair_ret, 2),
        "avg_dd%": round(avg_pair_dd, 2),
        "max_dd%": round(max_pair_dd, 2),
        "wr%": round(wr, 1),
        "expectancy%": round(expectancy, 4),
        "rr": round(rr, 2),
        "sharpe": round(sharpe_per_trade, 2),
        "trades": all_trades_count,
        "avg_trades/pair": round(all_trades_count / len(per_pair_ret), 1),
        "pair_wr%": round(pair_wr, 1),
        "profitable": n_profitable,
        "pairs": len(per_pair_ret),
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
            if done % 10 == 0: print(f"  {done}/{len(grid)}", flush=True)
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def print_table(results, title):
    print(f"\n{'='*90}")
    print(f"  {title} — {len(all_data)} pares, {len(results)} combos")
    print(f"{'='*90}")
    hdr = f"{'Score':<9} {'EMAs':<9} {'Risk':<7} {'SL':<7} {'TP':<7} {'TrdRet%':<9} {'WR%':<6} {'Expect%':<9} {'R:R':<6} {'Sharpe':<8} {'PairW%':<7}"
    print(hdr)
    print("-" * 90)
    for r in results[:15]:
        print(f"{r['score']:<9.1f} {str(r['ef'])+'/'+str(r['es']):<9s} {r['rp']:<7.0%} {r['sp']:<7.0%} {r['tp']:<7.0%} "
              f"{r['avg_trade_ret%']:<+9.4f} {r['wr%']:<6.1f} {r['expectancy%']:<+9.4f} {r['rr']:<6.2f} {r['sharpe']:<8.2f} {r['pair_wr%']:<7.1f}")


def main():
    # Stage 1: risk params with EMA 5/20
    g1 = list(product([5], [20], [20],
                       [0.01, 0.02, 0.03, 0.04],
                       [0.01, 0.015, 0.02],
                       [0.04, 0.06, 0.08, 0.10]))
    r1 = run_stage(g1, "Etapa 1 — Risk (EMA 5/20)")
    print_table(r1, "TOP RISK")

    best_r = r1[0]
    # Stage 2: EMA with best risk
    g2 = list(product([3, 5, 8, 10, 12], [10, 15, 20, 30], [20],
                       [best_r["rp"]], [best_r["sp"]], [best_r["tp"]]))
    r2 = run_stage(g2, "Etapa 2 — EMA")
    print_table(r2, "TOP EMA")

    all_r = sorted(r1 + r2, key=lambda x: x["score"], reverse=True)
    b = all_r[0]

    print(f"\n{'='*90}")
    print(f"  MEJOR GLOBAL:")
    print(f"  EMA {b['ef']}/{b['es']}, ADX {b['adx']}, Risk {b['rp']:.0%}, SL {b['sp']:.0%}, TP {b['tp']:.0%}")
    print(f"  Avg trade: {b['avg_trade_ret%']:+.4f}% | WR: {b['wr%']:.1f}% | Expectancy: {b['expectancy%']:+.4f}%")
    print(f"  R:R: {b['rr']:.2f} | Sharpe: {b['sharpe']:.2f} | Avg DD: {b['avg_dd%']:.2f}%")
    print(f"  Pair WR: {b['pair_wr%']:.1f}% ({b['profitable']}/{b['pairs']}) | Trades: {b['trades']}")
    print(f"{'='*90}")

    out = SETTINGS.data_dir.parent / "results" / "optimization_v3.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "stage1": len(r1), "stage2": len(r2),
        "best": b, "top_10": all_r[:10],
    }, indent=2))
    print(f"\nGuardado en {out}")


if __name__ == "__main__":
    main()
