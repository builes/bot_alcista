"""Multi-backtest v2.1 — SL=2% risk=1.5% con fricción (comisiones+slippage).
Capital: $150 USD.
"""
import sys, json, numpy as np, pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import SETTINGS, CapitalConfig, RiskConfig, StopConfig
from src.data.loader import load_ohlcv_csv
from src.risk.manager import RiskManager
from src.strategies.aggressive_trend import AggressiveTrendStrategy
from src.metrics.calculator import MetricsCalculator

TOTAL_CAPITAL = 150.0
COP_PER_USD = 1.0
MAX_PAIRS = 10
SCREEN_INTERVAL = 6
SCREEN_EMA_FAST = 20
SCREEN_EMA_SLOW = 50
STABLECOINS = {"USDC","USD1","FDUSD","EUR","RLUSD","TUSD","BUSD","USDE","U","BFUSD","XUSD","USDP","USDS","XAUT","PAXG","EURI","AEUR"}

STRAT_PARAMS = {"ema_fast":5,"ema_slow":25,"adx_threshold":22,"volume_threshold":0.5,"pullback_mode":False}
RISK_CFG = {"per_trade":0.015, "max_drawdown":0.30, "max_concurrent":1, "min_interval_days":0}
STOP_CFG = {"loss_pct":0.02, "take_profit_pct":0.04, "break_even_trigger":0.005, "trailing_activation":0.015, "trailing_distance":0.01}
FRICTION = 0.003

def get_tp(adx, vr):
    if adx>=30 and vr>=2: return 0.25
    if adx>=25 and vr>=1.5: return 0.15
    if adx>=25: return 0.10
    return 0.06

def compute_indicators(df):
    c=df["close"].astype(float); h=df["high"].astype(float); l=df["low"].astype(float)
    e20=c.ewm(span=20,adjust=False).mean(); e50=c.ewm(span=50,adjust=False).mean()
    p=c.shift(1)
    tr=pd.concat([(h-l).abs(),(h-p).abs(),(l-p).abs()],axis=1).max(axis=1)
    up=h-h.shift(1); dn=l.shift(1)-l
    pdm=pd.Series(np.where((up>dn)&(up>0),up,0.0),index=h.index)
    mdm=pd.Series(np.where((dn>up)&(dn>0),dn,0.0),index=h.index)
    t14=tr.ewm(span=14,adjust=False).mean().replace(0,np.nan)
    dp=100.0*pdm.ewm(span=14,adjust=False).mean()/t14
    dm=100.0*mdm.ewm(span=14,adjust=False).mean()/t14
    dx=100.0*(dp-dm).abs()/(dp+dm).replace(0,np.nan)
    adx=dx.ewm(span=14,adjust=False).mean()
    return pd.DataFrame({"ema20":e20,"ema50":e50,"adx":adx,"dp":dp,"dm":dm,"close":c},index=df.index)

def run_backtest(friction_label, friction):
    print(f"\n{'='*70}")
    print(f"  Ejecutando con fricción={friction*100:.2f}%", flush=True)
    print(f"{'='*70}")
    data_dir=SETTINGS.data_dir
    files=sorted(data_dir.glob("*_4h_2y.csv"))+sorted(data_dir.glob("*_4h.csv"))
    seen=set(); uf=[]
    for f in files:
        s=f.stem.replace("_4h_2y","").replace("_4h","")
        if s not in seen: seen.add(s); uf.append(f)
    all_data={}
    for f in uf:
        try:
            sym=f.stem.replace("_4h_2y","").replace("_4h","").replace("_","/",1)
            if "/" not in sym: sym=sym.replace("_","/")
            all_data[sym]=load_ohlcv_csv(f)
        except: pass
    short=[s for s,df in all_data.items() if len(df)<4000]
    for s in short: del all_data[s]
    start=max(df.index[0] for df in all_data.values())
    end=min(df.index[-1] for df in all_data.values())
    idx=pd.date_range(start=start,end=end,freq="4h")
    print(f"  Rango: {start.date()} → {end.date()} ({len(idx)} velas, {len(all_data)} pares)",flush=True)

    strategies={sym:AggressiveTrendStrategy(dict(STRAT_PARAMS)) for sym in all_data}
    sigs={sym:strategies[sym].generate_signals(all_data[sym]) for sym in all_data}

    screener_ind={sym:compute_indicators(df) for sym,df in all_data.items() if sym.split("/")[0] not in STABLECOINS}
    screener_cache={}
    for i,ts in enumerate(idx):
        if i%SCREEN_INTERVAL==0:
            res=[]
            for sym,ind in screener_ind.items():
                if ts not in ind.index: continue
                r=ind.loc[ts]
                if pd.isna(r["ema50"]): continue
                if r["ema20"]>r["ema50"] and r["adx"]>=22 and r["dp"]>r["dm"] and r["close"]>r["ema50"]:
                    res.append(sym)
            screener_cache[ts]=set(res[:MAX_PAIRS])

    cap_per_pair=TOTAL_CAPITAL/MAX_PAIRS
    active=set(); rms={}; idle=TOTAL_CAPITAL; all_trades=[]; eq_curve=[]
    total_friction=0.0

    for i,ts in enumerate(idx):
        if i%SCREEN_INTERVAL==0:
            active=screener_cache.get(ts, set())
            for sym in list(rms.keys()):
                if sym not in active and len(rms[sym].positions)==0:
                    all_trades.extend(rms[sym].trades)
                    idle+=rms[sym].equity
                    del rms[sym]
            for sym in active:
                if sym in rms or len(rms)>=MAX_PAIRS: continue
                alloc=min(cap_per_pair,idle)
                if alloc<cap_per_pair*0.5: continue
                rms[sym]=RiskManager(CapitalConfig(initial=alloc), RiskConfig(**RISK_CFG), StopConfig(**STOP_CFG))
                idle-=alloc
        total_eq=sum(rm.equity for rm in rms.values())
        eq_curve.append((ts,total_eq+max(0,idle)-total_friction))
        for sym in list(rms.keys()):
            df=all_data.get(sym)
            if df is None or ts not in df.index: continue
            row=df.loc[ts]; h,l,c=float(row["high"]),float(row["low"]),float(row["close"])
            closed=rms[sym].update_positions(ts,h,l)
            for t in closed:
                fc=(t.entry_price+t.exit_price)*t.size*friction/2
                total_friction+=fc
                t.pnl-=fc
                t.pnl_pct=t.pnl/(t.size*t.entry_price) if t.size*t.entry_price>0 else 0
            all_trades.extend(closed)
            sig=sigs[sym].loc[ts]
            if len(rms[sym].positions)==0 and sig["buy_signal"] and sym in active:
                adx_v=float(sig["adx"]); vr=float(sig["volume_ratio"])
                tp_pct=get_tp(adx_v,vr)
                rms[sym].open_position(ts,c,take_profit_price=c*(1+tp_pct))
            elif len(rms[sym].positions)>0 and sig["exit_signal"]:
                closed2=rms[sym].close_all_positions(ts,c)
                for t in closed2:
                    fc=(t.entry_price+t.exit_price)*t.size*friction/2
                    total_friction+=fc
                    t.pnl-=fc
                    t.pnl_pct=t.pnl/(t.size*t.entry_price) if t.size*t.entry_price>0 else 0
                all_trades.extend(closed2)
    for rm in rms.values(): all_trades.extend(rm.trades)
    trades=all_trades
    eq=pd.Series(data=[e for _,e in eq_curve],index=[t for t,_ in eq_curve])
    mc=MetricsCalculator(initial_capital=TOTAL_CAPITAL)
    metrics=mc.compute(eq,trades)
    days=(idx[-1]-idx[0]).total_seconds()/86400; months=days/30.44
    monthly=metrics.get("total_return_pct",0)/months if months>0 else 0
    fe=metrics.get("final_equity",TOTAL_CAPITAL); tr=metrics.get("total_return",0)
    label_friction = f"friccion{friction_label}" if friction>0 else "sin_friccion"
    label=f"v21_SL2_R1.5_{label_friction}"
    out=SETTINGS.data_dir.parent/"results"/f"backtest_{label}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "config":{"capital_usd":TOTAL_CAPITAL,"friction":friction,
                  "strategy":STRAT_PARAMS,"risk":RISK_CFG,"stops":STOP_CFG},
        "period":{"start":str(start.date()),"end":str(end.date()),"months":round(months,1)},
        "pairs":len(all_data),"max_concurrent":MAX_PAIRS,
        "total_friction_usd":round(total_friction,2),
        "metrics":{k:round(v,4) if isinstance(v,float) else v for k,v in metrics.items()},
        "monthly_return_pct":round(monthly,2),
    },indent=2))
    print(f"\n  BACKTEST v2.1 — SL=2% Risk=1.5% — {friction_label.replace('_',' ')}")
    print(f"{'─'*70}")
    print(f"  Retorno:        {metrics.get('total_return_pct',0):+.2f}%  ({tr:+.2f} USD)")
    print(f"  Mensual:        {monthly:+.2f}%")
    print(f"  Max DD:         {metrics.get('max_drawdown_pct',0):.2f}%")
    print(f"  Sharpe:         {metrics.get('sharpe_ratio','N/A')}")
    print(f"  Profit Factor:  {metrics.get('profit_factor','N/A')}")
    print(f"  Win Rate:       {metrics.get('win_rate_pct',0):.2f}%")
    print(f"  Avg Win/Loss:   {metrics.get('avg_win_pct',0):.2f}% / {metrics.get('avg_loss_pct',0):.2f}%")
    print(f"  Trades:         {metrics.get('total_trades',len(trades))}")
    print(f"{'─'*70}")
    print(f"  Capital final:  ${fe:,.2f}")
    print(f"  Ganancia:       ${tr:+,.2f}")
    if friction>0: print(f"  Comisiones:     ${-total_friction:+,.2f}")
    print(f"{'='*70}\n")
    print(f"  Resultados → {out}")

if __name__=="__main__":
    run_backtest("sin_friccion", friction=0.0)
    run_backtest("con_friccion", friction=FRICTION)
