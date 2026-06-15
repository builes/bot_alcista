"""Backtest multi-par independiente: cada par se testea por separado y se agregan resultados."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from config.settings import SETTINGS
from src.backtesting.engine import BacktestEngine
from src.data.loader import load_ohlcv_csv
from src.metrics.calculator import MetricsCalculator
from src.strategies.aggressive_trend import AggressiveTrendStrategy
from src.risk.manager import RiskManager, CapitalConfig, RiskConfig, StopConfig
from src.utils.logger import setup_logger

logger = setup_logger("multi_bt", SETTINGS.logs_dir)
CAPITAL_PER_PAIR = SETTINGS.capital.initial

capital_cfg = CapitalConfig(initial=CAPITAL_PER_PAIR)
risk_cfg = RiskConfig(
    per_trade=SETTINGS.risk.per_trade,
    max_drawdown=SETTINGS.risk.max_drawdown,
    max_concurrent=1,
    min_interval_days=0,
)
stop_cfg = StopConfig(
    loss_pct=SETTINGS.stops.loss_pct,
    take_profit_pct=SETTINGS.stops.take_profit_pct,
    break_even_trigger=SETTINGS.stops.break_even_trigger,
    trailing_activation=SETTINGS.stops.trailing_activation,
    trailing_distance=SETTINGS.stops.trailing_distance,
)


def run_pair(csv_path: Path) -> dict:
    try:
        df = load_ohlcv_csv(csv_path)
        sym = csv_path.stem.replace("_4h", "").replace("_", "/", 1)
        if "/" not in sym:
            sym = sym.replace("_", "/")

        risk_mgr = RiskManager(capital_cfg, risk_cfg, stop_cfg)
        strategy = AggressiveTrendStrategy({
            "ema_fast": 5,
            "ema_slow": 20,
            "adx_threshold": 20,
            "volume_threshold": 1.0,
            "pullback_mode": False,
        })
        signals = strategy.generate_signals(df)
        trades = []

        for i in range(len(df)):
            ts = df.index[i]
            row = df.iloc[i]
            high, low, close = float(row["high"]), float(row["low"]), float(row["close"])

            closed = risk_mgr.update_positions(ts, high, low)
            trades.extend(closed)

            sig = signals.iloc[i]
            pos_open = len(risk_mgr.positions) > 0

            if not pos_open and sig["buy_signal"] == 1:
                risk_mgr.open_position(ts, close)
            elif pos_open and sig["exit_signal"] == 1:
                closed = risk_mgr.close_all_positions(ts, close)
                trades.extend(closed)

        eq = risk_mgr.equity
        ret = (eq - CAPITAL_PER_PAIR) / CAPITAL_PER_PAIR * 100
        n_trades = len(risk_mgr.trades)
        return {
            "symbol": sym,
            "return_pct": round(ret, 2),
            "final_equity": round(eq, 2),
            "trades": n_trades,
            "errors": 0,
        }
    except Exception as e:
        return {"symbol": csv_path.name, "return_pct": 0, "final_equity": 0, "trades": 0, "errors": 1, "error": str(e)}


def main():
    data_dir = SETTINGS.data_dir
    csv_files = sorted(data_dir.glob("*_4h.csv"))
    logger.info("Backtest independiente de %d pares...", len(csv_files))

    results = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        fut = {pool.submit(run_pair, f): f for f in csv_files}
        for f in as_completed(fut):
            r = f.result()
            results.append(r)
            if r["trades"] > 0:
                logger.info("%-20s return=%+.2f%% trades=%d", r["symbol"], r["return_pct"], r["trades"])

    results.sort(key=lambda x: x["return_pct"], reverse=True)

    n = len(results)
    returns = [r["return_pct"] for r in results]
    trades = [r["trades"] for r in results]
    wins = sum(1 for r in results if r["return_pct"] > 0)
    losses = sum(1 for r in results if r["return_pct"] <= 0)
    errors = sum(r["errors"] for r in results)

    avg_ret = sum(returns) / n if n else 0
    total_trades = sum(trades)

    total_capital = CAPITAL_PER_PAIR * n
    total_final = sum(r["final_equity"] for r in results)
    total_return = (total_final - total_capital) / total_capital * 100

    print(f"\n{'='*60}")
    print(f"  MULTI-BACKTEST AGREGADO ({n} pares)")
    print(f"{'='*60}")
    print(f"  Capital total:     ${total_capital:,.2f}")
    print(f"  Equity final:      ${total_final:,.2f}")
    print(f"  Retorno total:     {total_return:+.2f}%")
    print(f"  Retorno promedio:  {avg_ret:+.2f}% por par")
    print(f"  Pares ganadores:   {wins}/{n} ({wins/n*100:.1f}%)")
    print(f"  Pares perdedores:  {losses}/{n} ({losses/n*100:.1f}%)")
    print(f"  Total trades:      {total_trades}")
    print(f"  Errors:            {errors}")
    print(f"\n  Top 10:")
    for r in results[:10]:
        print(f"    {r['symbol']:<20s} {r['return_pct']:+.2f}%  trades={r['trades']}")
    print(f"\  Bottom 5:")
    for r in results[-5:]:
        print(f"    {r['symbol']:<20s} {r['return_pct']:+.2f}%  trades={r['trades']}")
    print(f"{'='*60}\n")

    out = SETTINGS.data_dir.parent / "results" / "multi_independent.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "total_pairs": n,
        "total_return_pct": round(total_return, 2),
        "avg_return_pct": round(avg_ret, 2),
        "winners": wins,
        "losers": losses,
        "total_trades": total_trades,
        "errors": errors,
        "top_10": [{"symbol": r["symbol"], "return_pct": r["return_pct"], "trades": r["trades"]} for r in results[:10]],
        "bottom_5": [{"symbol": r["symbol"], "return_pct": r["return_pct"], "trades": r["trades"]} for r in results[-5:]],
    }, indent=2))
    logger.info("Resultados guardados en %s", out)


if __name__ == "__main__":
    main()
