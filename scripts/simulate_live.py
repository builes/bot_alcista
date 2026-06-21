"""Simula el LiveRunner v2.1 (run_live_nopb_v2.py) en los ultimos 8 dias.
Usa las MISMAS funciones y clases del live runner, no reimplementaciones.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

from config.settings import SETTINGS, CapitalConfig, RiskConfig, StopConfig
from src.risk.manager import RiskManager
from src.strategies.aggressive_trend import AggressiveTrendStrategy

# ── Importar las funciones y constantes REALES del live runner ────────
from scripts.run_live_nopb_v2 import (
    screen_pairs,
    compute_adx_vol,
    get_tp_adx_vol,
    STRAT_PARAMS,
    RISK_PARAMS,
    STOP_PARAMS,
    INITIAL_CAPITAL as LR_CAPITAL,
    MAX_CAPITAL_USDT,
    MAX_CAPITAL_PER_TRADE,
    STABLECOINS,
)

DATA_DIR = SETTINGS.data_dir
CANDLE_TIMES = [0, 4, 8, 12, 16, 20]
FRICTION = 0.003  # 0.3% comision Binance + slippage estimado


@dataclass
class TradeLog:
    symbol: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    pnl_pct: float
    exit_reason: str
    adx: float = 0.0
    vol_ratio: float = 0.0
    fee: float = 0.0

def apply_friction(entry_price: float, exit_price: float, size: float, pnl: float) -> tuple[float, float]:
    """Resta comision 0.3% del PnL. Devuelve (pnl_ajustado, fee)."""
    fee = (entry_price + exit_price) * size * FRICTION / 2
    pnl_adj = pnl - fee
    return pnl_adj, fee


def main():
    now = datetime.now(timezone.utc)
    end = now.replace(minute=0, second=0, microsecond=0)
    end = end.replace(hour=(end.hour // 4) * 4).replace(tzinfo=None)
    start = (end - timedelta(days=8)).replace(tzinfo=None)

    print(f"Capital: ${LR_CAPITAL}")
    print(f"Periodo: {start} → {end} UTC")
    print()

    # ── Cargar CSV ────────────────────────────────────────────────────
    csv_files = sorted(DATA_DIR.glob("*_4h_2y.csv"))
    all_data = {}
    for fpath in csv_files:
        sym = fpath.stem.replace("_4h_2y", "").replace("_", "/", 1)
        if "/" not in sym:
            sym = sym.replace("_", "/")
        base = sym.split("/")[0]
        if base in STABLECOINS:
            continue
        try:
            df = pd.read_csv(fpath, parse_dates=["timestamp"])
            df["timestamp"] = df["timestamp"].dt.tz_localize(None)
            df.sort_values("timestamp", inplace=True)
            df.reset_index(drop=True, inplace=True)
            if len(df) >= 200:
                all_data[sym] = df
        except Exception:
            continue

    # Volcamos los pares en una lista (como fetch_top_usdt_pairs los daria)
    all_symbols = list(all_data.keys())
    print(f"Pares: {len(all_symbols)}")
    print()

    # ── Generar timestamps 4h ─────────────────────────────────────────
    timestamps = []
    ts = start
    while ts <= end:
        if ts.hour in CANDLE_TIMES:
            timestamps.append(ts)
        ts += timedelta(hours=1)
    timestamps = sorted(set(
        t.replace(minute=0, second=0, microsecond=0)
        for t in timestamps if t.hour in CANDLE_TIMES
    ))

    # ── Estado (como en LiveRunner) ────────────────────────────────────
    equity = LR_CAPITAL
    peak_equity = LR_CAPITAL
    pairs_state: dict[str, dict] = {}  # symbol -> {"capital": float, "position": dict or None, "trades": list, "rm": RiskManager, "strat": AggressiveTrendStrategy}
    all_trades: list[TradeLog] = []
    equity_curve = [(timestamps[0], equity)]
    cycle_count = 0

    for cycle_ts in timestamps:
        cycle_count += 1

        # Preparar dfs hasta este timestamp
        dfs = {}
        for sym, df in all_data.items():
            mask = df["timestamp"] <= cycle_ts
            if mask.any():
                dfs[sym] = df[mask].reset_index(drop=True)

        # ── 1. SCREENER (igual que screen_pairs en live runner) ───────
        # Filtramos pares con datos suficientes
        candidates = [s for s in all_symbols if s in dfs and len(dfs[s]) >= 200]
        active = screen_pairs(candidates, dfs)
        active_set = set(active)
        n_screener = len(active)

        # ── 2. CLOSE_REMOVED: cerrar pares que salieron del screener ──
        for sym in list(pairs_state.keys()):
            ps = pairs_state[sym]
            if sym in active_set:
                continue
            if ps.get("position") is not None:
                pos = ps["position"]
                exit_price = pos["entry_price"] * (1 - STOP_PARAMS["loss_pct"])
                pnl_pct = -STOP_PARAMS["loss_pct"]
                pnl = pnl_pct * pos["size"] * pos["entry_price"]
                pnl_adj, fee = apply_friction(pos["entry_price"], exit_price, pos["size"], pnl)
                equity += pnl_adj
                peak_equity = max(peak_equity, equity)

                all_trades.append(TradeLog(
                    symbol=sym,
                    entry_time=pos["entry_time"],
                    exit_time=cycle_ts,
                    entry_price=pos["entry_price"],
                    exit_price=exit_price,
                    size=pos["size"],
                    pnl=pnl_adj,
                    pnl_pct=pnl_adj / (pos["size"] * pos["entry_price"]) if pos["size"] * pos["entry_price"] > 0 else 0,
                    exit_reason="SCREENER_EXIT",
                    adx=pos.get("adx", 0),
                    vol_ratio=pos.get("vol_ratio", 0),
                    fee=fee,
                ))
                ps["position"] = None
                ps["capital"] = ps["rm"].equity

        # ── 3. CHECK_STOPS_PAPER (SL/TP via high/low) ────────────────
        for sym in list(pairs_state.keys()):
            ps = pairs_state[sym]
            if ps.get("position") is None:
                continue
            df = dfs.get(sym)
            if df is None or len(df) == 0:
                continue
            row = df.iloc[-1]
            high, low = float(row["high"]), float(row["low"])
            rm = ps["rm"]
            closed = rm.update_positions(cycle_ts, high, low)
            for t in closed:
                pnl_adj, fee = apply_friction(t.entry_price, t.exit_price, t.size, t.pnl)
                equity += pnl_adj
                peak_equity = max(peak_equity, equity)
                pos_meta = ps.get("position") or {}
                all_trades.append(TradeLog(
                    symbol=sym,
                    entry_time=t.entry_time,
                    exit_time=t.exit_time,
                    entry_price=t.entry_price,
                    exit_price=t.exit_price,
                    size=t.size,
                    pnl=pnl_adj,
                    pnl_pct=pnl_adj / (t.size * t.entry_price) if t.size * t.entry_price > 0 else 0,
                    exit_reason=t.exit_reason,
                    adx=pos_meta.get("adx", 0),
                    vol_ratio=pos_meta.get("vol_ratio", 0),
                    fee=fee,
                ))
                ps["position"] = None
                ps["capital"] = rm.equity

        # ── 4. PROCESS: procesar cada par activo ─────────────────────
        for sym in active:
            df = dfs.get(sym)
            if df is None or len(df) < 200:
                continue

            # Inicializar estado del par si es primera vez
            if sym not in pairs_state:
                effective = min(equity, MAX_CAPITAL_USDT)
                capital_en_uso = sum(p["capital"] for p in pairs_state.values())
                disponible = max(0.0, effective - capital_en_uso)
                if disponible > 0:
                    capital = min(
                        disponible * MAX_CAPITAL_PER_TRADE,
                        disponible / max(1, len(pairs_state) + 1),
                    )
                else:
                    capital = 0.0

                if capital <= 0:
                    continue  # sin capital disponible para este par

                rm = RiskManager(
                    CapitalConfig(initial=capital),
                    RiskConfig(**RISK_PARAMS),
                    StopConfig(**STOP_PARAMS),
                )
                strat = AggressiveTrendStrategy(dict(STRAT_PARAMS))
                pairs_state[sym] = {
                    "capital": capital,
                    "position": None,
                    "trades": [],
                    "rm": rm,
                    "strat": strat,
                }

            ps = pairs_state[sym]
            has_position = ps.get("position") is not None
            sig = ps["strat"].generate_signals(df)
            buy = bool(sig.iloc[-1]["buy_signal"])
            exit_sig = bool(sig.iloc[-1]["exit_signal"])

            if has_position:
                if exit_sig:
                    close = float(df["close"].iloc[-1])
                    closed = ps["rm"].close_all_positions(cycle_ts, close)
                    for t in closed:
                        pnl_adj, fee = apply_friction(t.entry_price, t.exit_price, t.size, t.pnl)
                        equity += pnl_adj
                        peak_equity = max(peak_equity, equity)
                        pos_meta = ps.get("position") or {}
                        all_trades.append(TradeLog(
                            symbol=sym,
                            entry_time=t.entry_time,
                            exit_time=t.exit_time,
                            entry_price=t.entry_price,
                            exit_price=t.exit_price,
                            size=t.size,
                            pnl=pnl_adj,
                            pnl_pct=pnl_adj / (t.size * t.entry_price) if t.size * t.entry_price > 0 else 0,
                            exit_reason=t.exit_reason,
                            adx=pos_meta.get("adx", 0),
                            vol_ratio=pos_meta.get("vol_ratio", 0),
                            fee=fee,
                        ))
                        ps["position"] = None
                        ps["capital"] = ps["rm"].equity
                    # No seguir si se cerro por exit_signal (sale del if)
                    # Sigue al siguiente par

            elif buy:
                # ── ENTER ──
                close = float(df["close"].iloc[-1])
                adx_val, di_plus, di_minus, vol_r = compute_adx_vol(df)
                tp_pct = get_tp_adx_vol(adx_val, vol_r)
                tp_price = close * (1.0 + tp_pct)

                pos = ps["rm"].open_position(
                    cycle_ts, close, take_profit_price=tp_price
                )
                if pos is not None:
                    ps["position"] = {
                        "entry_price": close,
                        "entry_time": cycle_ts,
                        "size": pos.size,
                        "stop_loss": pos.stop_loss,
                        "take_profit": pos.take_profit,
                        "adx": round(adx_val, 1),
                        "vol_ratio": round(vol_r, 2),
                    }

        # ── 5. Equity snapshot ─────────────────────────────────────
        # equity solo se actualiza en cierres (como state.equity en live runner)
        equity_curve.append((cycle_ts, equity))

    # ── Cerrar posiciones abiertas al final ───────────────────────────
    for sym in list(pairs_state.keys()):
        ps = pairs_state[sym]
        if ps.get("position") is not None and len(ps["rm"].positions) > 0:
            df = dfs.get(sym)
            if df is not None:
                close = float(df["close"].iloc[-1])
                closed = ps["rm"].close_all_positions(timestamps[-1], close)
                for t in closed:
                    pnl_adj, fee = apply_friction(t.entry_price, t.exit_price, t.size, t.pnl)
                    equity += pnl_adj
                    all_trades.append(TradeLog(
                        symbol=sym,
                        entry_time=t.entry_time,
                        exit_time=t.exit_time,
                        entry_price=t.entry_price,
                        exit_price=t.exit_price,
                        size=t.size,
                        pnl=pnl_adj,
                        pnl_pct=pnl_adj / (t.size * t.entry_price) if t.size * t.entry_price > 0 else 0,
                        exit_reason="FORCE_CLOSE",
                        fee=fee,
                    ))
                    ps["position"] = None

    final_equity = equity

    # ── Metricas ──────────────────────────────────────────────────────
    total_return = ((final_equity - LR_CAPITAL) / LR_CAPITAL) * 100
    total_fees = sum(t.fee for t in all_trades)
    wins = [t for t in all_trades if t.pnl > 0]
    losses = [t for t in all_trades if t.pnl <= 0]
    win_rate = len(wins) / len(all_trades) * 100 if all_trades else 0
    gross_profit = sum(t.pnl for t in wins) if wins else 0
    gross_loss = sum(t.pnl for t in losses) if losses else 0
    profit_factor = abs(gross_profit / gross_loss) if gross_loss != 0 else float('inf')

    eq_series = pd.Series([e for _, e in equity_curve])
    peak = eq_series.expanding().max()
    dd = (peak - eq_series) / peak * 100
    max_dd = dd.max()

    avg_win = (sum(t.pnl_pct for t in wins) / len(wins) * 100) if wins else 0
    avg_loss = (sum(t.pnl_pct for t in losses) / len(losses) * 100) if losses else 0

    # ── Mostrar ───────────────────────────────────────────────────────
    print(f"{'='*62}")
    print(f"  SIMULACION LIVE RUNNER v2.1 (CODIGO REAL)")
    print(f"{'='*62}")
    print(f"  Capital inicial:    ${LR_CAPITAL:.2f}")
    print(f"  Capital final:      ${final_equity:.2f}")
    print(f"  Retorno total:      {total_return:+.2f}%")
    print(f"  Max Drawdown:       {max_dd:.2f}%")
    print(f"  Trades:             {len(all_trades)}")
    print(f"  Win Rate:           {win_rate:.1f}%")
    print(f"  Profit Factor:      {profit_factor:.2f}")
    print(f"  Ganadas:            {len(wins)}  (avg +{avg_win:.2f}%)")
    print(f"  Perdidas:           {len(losses)}  (avg {avg_loss:.2f}%)")
    print(f"  Friccion total:     ${total_fees:.2f} ({FRICTION*100:.1f}% por trade)")
    print(f"  Ciclos 4h:          {cycle_count}")

    if all_trades:
        print(f"\n  {'─'*60}")
        print(f"  TRADES:")
        print(f"  {'─'*60}")
        for i, t in enumerate(all_trades, 1):
            held = (t.exit_time - t.entry_time).total_seconds() / 3600
            print(f"  {i:2d}. [{t.exit_reason:<12}] "
                  f"{t.symbol:<12} "
                  f"{t.entry_time.strftime('%m/%d %H:%M')}→"
                  f"{t.exit_time.strftime('%m/%d %H:%M')} | "
                  f"${t.entry_price:<7.2f}→${t.exit_price:<7.2f} | "
                  f"{t.pnl_pct*100:+.2f}% (${t.pnl:+.2f}) fee=${t.fee:.3f}")


if __name__ == "__main__":
    main()
