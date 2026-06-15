"""Multi-backtest realista — parametrizable para pruebas de optimización."""
import sys, json
from pathlib import Path
from typing import Dict, List, Tuple
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import pandas as pd
from config.settings import SETTINGS
from src.data.loader import load_ohlcv_csv
from src.risk.manager import RiskManager, CapitalConfig, RiskConfig, StopConfig
from src.strategies.aggressive_trend import AggressiveTrendStrategy
from src.metrics.calculator import MetricsCalculator

TOTAL_CAPITAL = SETTINGS.capital.initial
MAX_PAIRS = 10
SCREEN_INTERVAL = 6
SCREEN_EMA_FAST = 20
SCREEN_EMA_SLOW = 50

# ---- OVERRIDE PARAMS ----
CFG_EMA_FAST = 12
CFG_EMA_SLOW = 30
CFG_ADX = 20
CFG_RISK = 0.01      # 1%
CFG_SL = 0.02        # 2%
CFG_TP = 0.10        # 10%


def screen_pairs(all_data: Dict[str, pd.DataFrame], ts: pd.Timestamp) -> List[str]:
    results = []
    for sym, df in all_data.items():
        df_before = df.loc[:ts]
        if len(df_before) < SCREEN_EMA_SLOW + 20: continue
        close = df_before["close"].astype(float)
        ema_fast = close.ewm(span=SCREEN_EMA_FAST, adjust=False).mean()
        ema_slow = close.ewm(span=SCREEN_EMA_SLOW, adjust=False).mean()
        high = df_before["high"].astype(float)
        low = df_before["low"].astype(float)
        prev = close.shift(1)
        tr = pd.concat([(high-low).abs(), (high-prev).abs(), (low-prev).abs()], axis=1).max(axis=1)
        up = high - high.shift(1)
        down = low.shift(1) - low
        pdm = pd.Series(np.where((up>down)&(up>0), up, 0.0), index=high.index)
        mdm = pd.Series(np.where((down>up)&(down>0), down, 0.0), index=high.index)
        trs = tr.ewm(span=14, adjust=False).mean().replace(0, np.nan)
        ps = pdm.ewm(span=14, adjust=False).mean()
        ms = mdm.ewm(span=14, adjust=False).mean()
        dp = 100.0 * ps / trs
        dm = 100.0 * ms / trs
        dx = 100.0 * (dp-dm).abs() / (dp+dm).replace(0, np.nan)
        adx = dx.ewm(span=14, adjust=False).mean()
        l = -1
        if (ema_fast.iloc[l] > ema_slow.iloc[l]
            and float(adx.iloc[l]) >= 20
            and float(dp.iloc[l]) > float(dm.iloc[l])
            and float(close.iloc[l]) > float(ema_slow.iloc[l])):
            results.append(sym)
    return results[:MAX_PAIRS]


def main():
    data_dir = SETTINGS.data_dir
    csv_files = sorted(data_dir.glob("*_4h_2y.csv")) + sorted(data_dir.glob("*_4h.csv"))
    seen = set()
    unique = []
    for f in csv_files:
        stem = f.stem.replace("_4h_2y","").replace("_4h","")
        if stem not in seen: seen.add(stem); unique.append(f)

    all_data = {}
    for f in unique:
        try:
            sym = f.stem.replace("_4h_2y","").replace("_4h","").replace("_","/",1)
            if "/" not in sym: sym = sym.replace("_","/")
            all_data[sym] = load_ohlcv_csv(f)
        except Exception: pass

    short = [s for s,df in all_data.items() if len(df) < 4000]
    for s in short: del all_data[s]

    # Exclude pairs that don't reach the latest date
    latest_end = max(df.index[-1] for df in all_data.values())
    cutoff = latest_end - pd.Timedelta(days=14)
    old_pairs = [s for s, df in all_data.items() if df.index[-1] < cutoff]
    for s in old_pairs:
        del all_data[s]

    start = max(df.index[0] for df in all_data.values())
    end = min(df.index[-1] for df in all_data.values())
    idx = pd.date_range(start=start, end=end, freq="4h")
    print(f"Rango: {start.date()} → {end.date()} ({len(idx)} velas, {len(all_data)} pares)", flush=True)

    strategies = {sym: AggressiveTrendStrategy({"ema_fast": CFG_EMA_FAST, "ema_slow": CFG_EMA_SLOW, "adx_threshold": CFG_ADX, "volume_threshold": 1.0, "pullback_mode": False}) for sym in all_data}

    cap_per_pair = TOTAL_CAPITAL / MAX_PAIRS
    active: set = set()
    rms: dict = {}
    idle = TOTAL_CAPITAL
    all_trades: List = []
    equity_curve: List[Tuple[pd.Timestamp, float]] = []

    for i, ts in enumerate(idx):
        if i % SCREEN_INTERVAL == 0:
            active = set(screen_pairs(all_data, ts))
            for sym in list(rms.keys()):
                if sym not in active and len(rms[sym].positions) == 0:
                    all_trades.extend(rms[sym].trades)
                    idle += rms[sym].equity
                    del rms[sym]
            for sym in active:
                if sym in rms or len(rms) >= MAX_PAIRS:
                    continue
                alloc = min(cap_per_pair, idle)
                if alloc < cap_per_pair * 0.5:
                    continue
                rms[sym] = RiskManager(
                    CapitalConfig(initial=alloc),
                    RiskConfig(per_trade=CFG_RISK, max_drawdown=1.0, max_concurrent=1, min_interval_days=0),
                    StopConfig(loss_pct=CFG_SL, take_profit_pct=CFG_TP, break_even_trigger=0.01, trailing_activation=0.03, trailing_distance=0.02),
                )
                idle -= alloc

        total_eq = sum(rm.equity for rm in rms.values())
        equity_curve.append((ts, total_eq + max(0.0, idle)))

        for sym in list(rms.keys()):
            df = all_data.get(sym)
            if df is None or ts not in df.index: continue
            row = df.loc[ts]
            h, l, c = float(row["high"]), float(row["low"]), float(row["close"])
            rms[sym].update_positions(ts, h, l)
            sig = strategies[sym].generate_signals(df.loc[:ts]).iloc[-1]
            if len(rms[sym].positions) == 0 and sig["buy_signal"] and sym in active:
                rms[sym].open_position(ts, c)
            elif len(rms[sym].positions) > 0 and sig["exit_signal"]:
                rms[sym].close_all_positions(ts, c)



    for rm in rms.values():
        all_trades.extend(rm.trades)
    trades = all_trades
    eq = pd.Series(data=[e for _,e in equity_curve], index=[t for t,_ in equity_curve])

    mc = MetricsCalculator(initial_capital=TOTAL_CAPITAL)
    metrics = mc.compute(eq, trades)
    days = (idx[-1]-idx[0]).total_seconds()/86400
    months = days/30.44
    monthly = metrics.get("total_return_pct", 0)/months if months>0 else 0

    label = f"EMA{CFG_EMA_FAST}/{CFG_EMA_SLOW}_R{CFG_RISK:.0%}_SL{CFG_SL:.0%}_TP{CFG_TP:.0%}"
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Capital: ${TOTAL_CAPITAL:,.0f} | Pares: {len(all_data)} | Max conc: {MAX_PAIRS}")
    print(f"  Periodo: {start.date()} → {end.date()} ({months:.1f} meses)")
    for k,v in metrics.items():
        if isinstance(v, float): print(f"  {k}: {v:.4f}")
        else: print(f"  {k}: {v}")
    print(f"  Retorno mensual:  {monthly:+.2f}%")
    print(f"  Trades totales:   {len(trades)}")
    print(f"{'='*60}\n")

    out = SETTINGS.data_dir.parent / "results" / f"realistic_multi_{label}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "config": {"ema_fast": CFG_EMA_FAST, "ema_slow": CFG_EMA_SLOW, "adx": CFG_ADX, "risk": CFG_RISK, "sl": CFG_SL, "tp": CFG_TP},
        "period": {"start": str(start.date()), "end": str(end.date()), "months": round(months,1)},
        "pairs": len(all_data), "max_concurrent": MAX_PAIRS,
        "metrics": {k: round(v,4) if isinstance(v,float) else v for k,v in metrics.items()},
        "monthly_return_pct": round(monthly, 2),
        "trades": len(trades),
    }, indent=2))
    print(f"Guardado en results/realistic_multi_{label}.json")


if __name__ == "__main__":
    main()
