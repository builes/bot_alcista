"""Live / Paper trading — REST polling cada 4h.
Version v2.1 sin pullback (volume_threshold=0.5, retorno +876%).
Misma estrategia que nopb_v3 pero con filtro de volumen activo.
Modos:
  --paper  (default)  Simulacion sin API keys.
  --live              Opera en Binance real.
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
import os

from src.exchange.binance_exchange import BinanceExchange
from src.exchange.base import Order
from src.risk.manager import RiskManager, CapitalConfig, RiskConfig, StopConfig
from src.strategies.aggressive_trend import AggressiveTrendStrategy
from src.utils.logger import setup_logger

# ── Constantes (backtest-proven) ──────────────────────────────────────────
INITIAL_CAPITAL = 150.0
MAX_CAPITAL_USDT = 150.0
MAX_CONCURRENT = 10
MAX_CANDIDATES = 100
MIN_VOLUME_USD = 4_000_000

STABLECOINS = {"USDC", "USD1", "FDUSD", "EUR", "RLUSD", "TUSD", "BUSD", "USDE",
               "U", "BFUSD", "XUSD", "USDP", "USDS", "XAUT", "PAXG",
               "EURI", "AEUR",
               "LINKDOWN", "ETHDOWN", "XRPDOWN", "LINKUP", "1INCHDOWN", "1INCHUP",
               "AAVEDOWN", "AAVEUP", "ADADOWN", "BTCUP", "BTCDOWN"}

STRAT_PARAMS = {
    "ema_fast": 5,
    "ema_slow": 25,
    "adx_period": 14,
    "adx_threshold": 22.0,
    "volume_window": 20,
    "volume_threshold": 0.0,
    "pullback_mode": False,
    "pullback_tolerance": 0.03,
}

RISK_PARAMS = {
    "per_trade": 0.015,
    "max_drawdown": 0.30,
    "max_concurrent": 1,
    "min_interval_days": 0,
}

MAX_CAPITAL_PER_TRADE = 0.50

STOP_PARAMS = {
    "loss_pct": 0.02,
    "take_profit_pct": 0.04,
    "break_even_trigger": 0.005,
    "trailing_activation": 0.015,
    "trailing_distance": 0.01,
}

logger = setup_logger("live_nopb_v2", Path("logs"))


DELISTED = {"UTK", "LRC"}

# ── Screener ────────────────────────────────────────────────────────────────────


def screen_pairs(
    pairs: List[str], dfs: Dict[str, pd.DataFrame]
) -> List[str]:
    """EMA20 > EMA50 + ADX >= 20 + DI+ > DI- en 4h."""
    results: List[str] = []
    for sym in pairs:
        base = sym.split("/")[0]
        if base in STABLECOINS or base in DELISTED:
            continue
        df = dfs.get(sym)
        if df is None or len(df) < 200:
            continue
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()
        prev = close.shift(1)
        tr = pd.concat(
            [(high - low).abs(), (high - prev).abs(), (low - prev).abs()],
            axis=1,
        ).max(axis=1)
        up = high - high.shift(1)
        down = low.shift(1) - low
        pdm = pd.Series(
            np.where((up > down) & (up > 0), up, 0.0), index=high.index
        )
        mdm = pd.Series(
            np.where((down > up) & (down > 0), down, 0.0), index=high.index
        )
        tr14 = tr.ewm(span=14, adjust=False).mean().replace(0, np.nan)
        di_p = 100.0 * pdm.ewm(span=14, adjust=False).mean() / tr14
        di_m = 100.0 * mdm.ewm(span=14, adjust=False).mean() / tr14
        dx = (
            100.0
            * (di_p - di_m).abs()
            / (di_p + di_m).replace(0, np.nan)
        )
        adx = dx.ewm(span=14, adjust=False).mean()
        last = -1
        if (
            ema20.iloc[last] > ema50.iloc[last]
            and float(adx.iloc[last]) >= 22
            and float(di_p.iloc[last]) > float(di_m.iloc[last])
            and float(close.iloc[last]) > float(ema50.iloc[last])
        ):
            results.append(sym)
    return results


# ── ADX + Volume Ratio Helper ────────────────────────────────────────────────


def compute_adx_vol(df: pd.DataFrame):
    """Returns (adx_value, volume_ratio_sma) from the last bar."""
    c = df["close"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    prev = c.shift(1)
    tr = pd.concat(
        [(h - l).abs(), (h - prev).abs(), (l - prev).abs()],
        axis=1,
    ).max(axis=1)
    up = h - h.shift(1)
    down = l.shift(1) - l
    pdm = pd.Series(
        np.where((up > down) & (up > 0), up, 0.0), index=h.index
    )
    mdm = pd.Series(
        np.where((down > up) & (down > 0), down, 0.0), index=h.index
    )
    tr14 = tr.ewm(span=14, adjust=False).mean().replace(0, np.nan)
    dp = 100.0 * pdm.ewm(span=14, adjust=False).mean() / tr14
    dm = 100.0 * mdm.ewm(span=14, adjust=False).mean() / tr14
    dx = (
        100.0 * (dp - dm).abs() / (dp + dm).replace(0, np.nan)
    )
    adx = dx.ewm(span=14, adjust=False).mean()
    adx_val = float(adx.iloc[-1])
    di_plus = float(dp.iloc[-1]) if len(dp) > 0 else 0.0
    di_minus = float(dm.iloc[-1]) if len(dm) > 0 else 0.0
    vol = df["volume"].astype(float)
    vol_sma = vol.rolling(20).mean()
    vol_r = float(vol.iloc[-1] / vol_sma.iloc[-1]) if vol_sma.iloc[-1] > 0 else 0.0
    return adx_val, di_plus, di_minus, vol_r


def get_tp_adx_vol(adx_val: float, vol_r: float) -> float:
    """TP dinámico según fuerza de tendencia + volumen."""
    if adx_val >= 30 and vol_r >= 2.0:
        return 0.25
    if adx_val >= 25 and vol_r >= 1.5:
        return 0.15
    if adx_val >= 25:
        return 0.10
    return 0.06


# ── Sincronización con velas 4h UTC ────────────────────────────────────────


def next_4h_close(dt: datetime) -> datetime:
    """Próximo cierre de vela 4h (0:00, 4:00, 8:00, 12:00, 16:00, 20:00 UTC)."""
    hour = dt.hour
    next_hour = ((hour // 4) + 1) * 4
    candidate = dt.replace(minute=0, second=0, microsecond=0) + timedelta(
        hours=next_hour - hour
    )
    if (candidate - dt).total_seconds() < 60:
        candidate += timedelta(hours=4)
    return candidate


# ── Estado persistente ─────────────────────────────────────────────────────

STATE_FILE = Path("live_state_nopb_v2.json")


class LiveState:
    def __init__(self) -> None:
        self.equity = INITIAL_CAPITAL
        self.peak_equity = INITIAL_CAPITAL
        self.pairs: Dict[str, dict] = {}

    def save(self) -> None:
        data = {
            "equity": round(self.equity, 2),
            "peak_equity": round(self.peak_equity, 2),
            "pairs": self.pairs,
        }
        STATE_FILE.write_text(json.dumps(data, indent=2, default=str))

    @classmethod
    def load(cls) -> "LiveState":
        if not STATE_FILE.exists():
            return cls()
        try:
            data = json.loads(STATE_FILE.read_text())
            s = cls()
            s.equity = data.get("equity", INITIAL_CAPITAL)
            s.peak_equity = data.get("peak_equity", INITIAL_CAPITAL)
            s.pairs = data.get("pairs", {})
            return s
        except Exception as exc:
            logger.warning("Error loading state: %s — fresh start", exc)
            return cls()


# ── Trade Logger ────────────────────────────────────────────────────────────


class TradeLogger:
    def __init__(self) -> None:
        Path("logs").mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._file = Path("logs") / f"trades_nopb_v2_{ts}.csv"
        fh = open(self._file, "w", newline="")
        self._fields = [
            "time", "symbol", "trade_id", "action", "price", "size",
            "pnl", "reason", "equity",
            "entry_price", "entry_adx", "entry_di_plus", "entry_di_minus",
            "entry_vol_ratio", "entry_ema_gap",
            "held_hours", "max_gain_pct",
        ]
        self._writer = csv.DictWriter(fh, fieldnames=self._fields)
        self._writer.writeheader()
        self._consolidated = open(Path("logs") / "trades.csv", "a", newline="")
        self._consolidated_writer = csv.DictWriter(
            self._consolidated, fieldnames=self._fields
        )

    def log(self, equity: float, **kwargs) -> None:
        row = {
            "time": datetime.utcnow().isoformat(),
            "equity": round(equity, 2),
            "held_hours": "",
            "max_gain_pct": "",
            "entry_price": "",
            "entry_adx": "",
            "entry_di_plus": "",
            "entry_di_minus": "",
            "entry_vol_ratio": "",
            "entry_ema_gap": "",
            **kwargs,
        }
        self._writer.writerow(row)
        self._consolidated_writer.writerow(row)


# ── Cycle Logger ────────────────────────────────────────────────────────────


class CycleLogger:
    """Registra un CSV con el resumen de cada ciclo 4h para trazabilidad."""
    def __init__(self) -> None:
        Path("logs").mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._file = Path("logs") / f"cycles_nopb_v2_{ts}.csv"
        fh = open(self._file, "w", newline="")
        self._fields = [
            "cycle_time", "candidates", "screener_passed", "open_positions",
            "trades_cumulative", "equity", "peak_equity", "drawdown_pct",
        ]
        self._writer = csv.DictWriter(fh, fieldnames=self._fields)
        self._writer.writeheader()
        self._consolidated = open(Path("logs") / "cycles.csv", "a", newline="")
        self._consolidated_writer = csv.DictWriter(
            self._consolidated, fieldnames=self._fields
        )

    def log(self, **kwargs) -> None:
        row = {
            "cycle_time": datetime.utcnow().isoformat(),
            "candidates": "", "screener_passed": "", "open_positions": "",
            "trades_cumulative": "", "equity": "", "peak_equity": "", "drawdown_pct": "",
            **kwargs,
        }
        self._writer.writerow(row)
        self._consolidated_writer.writerow(row)


# ── Cycle Diagnostic ─────────────────────────────────────────────────────────


class CycleDiagnostic:
    """Genera CSV y resumen detallado de cada ciclo para debug."""
    def __init__(self, cycle_ts: datetime, candidates: int) -> None:
        Path("logs").mkdir(exist_ok=True)
        self._ts = cycle_ts
        self._candidates = candidates
        self._path = Path("logs") / f"cycle_{cycle_ts.strftime('%Y%m%d_%H%M')}.csv"
        fh = open(self._path, "w", newline="")
        self._fields = [
            "symbol", "has_data", "vol_ok", "ema20>50", "adx_ok", "di_ok",
            "c>e50", "screener", "e5>e25", "c>e25", "vr", "buy_signal",
            "entered", "fail_reason",
        ]
        self._writer = csv.DictWriter(fh, fieldnames=self._fields)
        self._writer.writeheader()
        self._fh = fh
        self._rows = 0
        self._data = {"no_data": 0, "screener_no": 0, "buy_no": 0,
                       "entered": 0, "no_cap": 0, "bugs": 0}
        self._reasons: dict[str, int] = {}

    def _reason_summary(self, reason: str) -> str:
        parts = reason.split("+")
        result = []
        for p in parts:
            p = p.strip()
            if "EMA" in p: result.append("EMA20≤50" if "20" in p else "E5≤25")
            elif "ADX" in p: result.append(f"ADX{p.split('=')[1].split('<')[0]}" if '<' in p else p)
            elif "DI" in p: result.append("DI+≤DI-")
            elif "CLOSE" in p: result.append("C≤E" + ("50" if "50" in p else "25"))
            elif "VOL" in p: result.append("Vol<4M")
            elif "VR" in p: result.append(p[:10])
            elif "SIN_CAPITAL" in p: result.append("SIN_CAPITAL")
            elif "NO_DATA" in p: result.append("SIN_DATOS")
            else: result.append(p)
        return "/".join(result)

    def log(self, **kwargs) -> None:
        row = {k: kwargs.get(k, "") for k in self._fields if k != "fail_reason"}
        reason = kwargs.get("fail_reason", "-")
        row["fail_reason"] = reason
        self._writer.writerow(row)
        self._rows += 1
        if reason != "-":
            self._reasons[reason] = self._reasons.get(reason, 0) + 1

    def summary(self) -> str:
        lines = []
        lines.append("╔════════════════════════════════════╗")
        lines.append(f"║  CICLO {self._ts.strftime('%Y-%m-%d %H:%M UTC')} — DIAGNOSTICO ║")
        lines.append("╠════════════════════════════════════╣")
        lines.append(f"║  Candidatos: {self._candidates:<3}  |  CSV: {self._rows:>3} pares     ║")
        lines.append(f"║  Entradas: {self._data['entered']:<3}  |  Sin datos: {self._data['no_data']:<2}          ║")
        lines.append(f"║  Buy signal: {self._data['entered']+self._data['no_cap']:<3}|  Sin capital: {self._data['no_cap']:<2}       ║")
        lines.append(f"║  Screener NO: {self._data['screener_no']:<3}|  Buy NO: {self._data['buy_no']:<2}            ║")
        if self._reasons:
            lines.append("╠════════════════════════════════════╣")
            if self._data['entered'] == 0:
                lines.append("║  ⚠️  0 ENTRADAS — Razones:         ║")
            for reason, count in sorted(self._reasons.items(), key=lambda x: -x[1])[:6]:
                short = self._reason_summary(reason)
                lines.append(f"║    {count:>3}x {short:<28} ║")
        lines.append("╚════════════════════════════════════╝")
        return "\n".join(lines)

    def export(self) -> None:
        self._fh.flush()
        self._fh.close()

    def __del__(self):
        try:
            self._fh.close()
        except Exception:
            pass


# ── Orquestador ────────────────────────────────────────────────────────────


class LiveRunner:
    def __init__(self, exchange: BinanceExchange, paper: bool = True) -> None:
        self._ex = exchange
        self._paper = paper
        if paper:
            self._state = LiveState.load()
        else:
            self._state = LiveState()
            self._state.equity = self._get_real_balance()
        self._strategies: Dict[str, AggressiveTrendStrategy] = {}
        self._risk_mgrs: Dict[str, RiskManager] = {}
        self._log = TradeLogger()
        self._cycle_log = CycleLogger()
        self._trade_counter = 0

    def _get_real_balance(self) -> float:
        try:
            balances = self._ex.fetch_balance()
            for b in balances:
                if b.asset == "USDT":
                    return min(b.free, MAX_CAPITAL_USDT)
        except Exception as exc:
            logger.warning("Error obteniendo balance real: %s — usando INITIAL_CAPITAL", exc)
        return INITIAL_CAPITAL

    def run(self) -> None:
        mode = "PAPER" if self._paper else "LIVE"
        logger.info("=" * 60)
        logger.info("TRADER %s INICIADO — Capital: $%.2f", mode, self._state.equity)
        if self._paper:
            logger.info("Sin API keys. Simulación con datos reales.")
        logger.info("=" * 60)

        while True:
            now = datetime.utcnow()
            nxt = next_4h_close(now)
            wait = (nxt - now).total_seconds()
            if wait > 60:
                logger.info(
                    "Próximo ciclo en %.1fh (%s UTC)",
                    wait / 3600, nxt.strftime("%H:%M"),
                )

            # Check prices every ~1 minuto entre ciclos
            while wait > 5:
                chunk = min(60.0, wait - 1)
                time.sleep(chunk)
                try:
                    self._check_prices()
                except Exception as exc:
                    logger.warning("Error check_prices: %s", exc)
                wait = (nxt - datetime.utcnow()).total_seconds()

            remaining = (nxt - datetime.utcnow()).total_seconds()
            if remaining > 0:
                time.sleep(remaining)

            try:
                self._cycle(nxt)
                if self._paper:
                    self._state.save()
            except Exception as exc:
                logger.exception("Error en ciclo: %s", exc)
                time.sleep(60)

    # ── Ciclo 4h ────────────────────────────────────────────────────────

    def _cycle(self, ts: datetime) -> None:
        logger.info("─── CICLO %s UTC ───", ts.strftime("%Y-%m-%d %H:%M"))

        candidates = self._ex.fetch_top_usdt_pairs(MAX_CANDIDATES, MIN_VOLUME_USD)
        # Filtrar pares delistados (UTK, LRC)
        candidates = [s for s in candidates if s.split("/")[0] not in DELISTED]
        self._last_candidates = len(candidates) if candidates else 0
        if not candidates:
            logger.warning("No se obtuvieron pares.")
            return
        logger.info("Candidatos: %d", len(candidates))

        dfs = self._ex.fetch_multiple_ohlcv(candidates, "4h", 220)
        n_data = len(dfs)
        n_timeout = len(candidates) - n_data

        # ── Diagnostico por par ────────────────────────────────────────
        diag = CycleDiagnostic(ts, len(candidates))
        # Construir mapa rapido de screener por par
        scr_map = {}
        buy_map = {}
        exit_map = {}
        for sym in candidates:
            df = dfs.get(sym)
            if df is None:
                diag.log(symbol=sym, has_data="NO", fail_reason="NO_DATA")
                diag._data["no_data"] += 1
                continue
            # Timestamp check
            if ts not in df.index:
                nearest = df.index.searchsorted(ts)
                if nearest > 0 and nearest <= len(df.index):
                    idx = nearest - 1
                else:
                    diag.log(symbol=sym, has_data="SI", fail_reason="NO_TIMESTAMP_NEAR")
                    diag._data["no_data"] += 1
                    continue
            else:
                idx = df.index.get_loc(ts)
            if idx < 200:
                diag.log(symbol=sym, has_data="SI", fail_reason="IDX<200")
                diag._data["no_data"] += 1
                continue
            sub = df.iloc[:idx+1]
            cp = float(sub["close"].iloc[-1])
            vol = float(sub["volume"].iloc[-1])
            vu = cp * vol * 6
            vol_ok = vu >= MIN_VOLUME_USD
            
            # Screener
            c = sub["close"].astype(float)
            ema20 = c.ewm(span=20, adjust=False).mean().iloc[-1]
            ema50 = c.ewm(span=50, adjust=False).mean().iloc[-1]
            e20gt50 = ema20 > ema50
            
            h_v = sub["high"].astype(float)
            l_v = sub["low"].astype(float)
            pc2 = c.shift(1)
            tr = pd.concat([(h_v-l_v).abs(), (h_v-pc2).abs(), (l_v-pc2).abs()], axis=1).max(axis=1)
            u = h_v - h_v.shift(1)
            dn = l_v.shift(1) - l_v
            pdm = pd.Series(np.where((u > dn) & (u > 0), u, 0.0), index=sub.index)
            mdm = pd.Series(np.where((dn > u) & (dn > 0), dn, 0.0), index=sub.index)
            t14 = tr.ewm(span=14, adjust=False).mean().replace(0, np.nan)
            dp = 100.0 * pdm.ewm(span=14, adjust=False).mean() / t14
            dm = 100.0 * mdm.ewm(span=14, adjust=False).mean() / t14
            dx = 100.0 * (dp - dm).abs() / (dp + dm).replace(0, np.nan)
            adx_val = dx.ewm(span=14, adjust=False).mean().iloc[-1]
            adx_ok = adx_val >= 22
            di_ok = dp.iloc[-1] > dm.iloc[-1]
            cgte50 = c.iloc[-1] > ema50
            scr_ok = e20gt50 and adx_ok and di_ok and cgte50
            scr_map[sym] = scr_ok
            
            # Buy signal
            sig = AggressiveTrendStrategy(dict(STRAT_PARAMS)).generate_signals(sub)
            e5gt25 = sig.iloc[-1]["ema_fast"] > sig.iloc[-1]["ema_slow"]
            cgte25 = c.iloc[-1] > sig.iloc[-1]["ema_slow"]
            vr_val = float(sig.iloc[-1]["volume_ratio"])
            buy_ok = bool(sig.iloc[-1]["buy_signal"])
            buy_map[sym] = buy_ok
            exit_map[sym] = bool(sig.iloc[-1]["exit_signal"])
            
            # Build fail reasons
            reasons = []
            if not vol_ok: reasons.append(f"VOL={vu/1e6:.1f}M<4M")
            if not e20gt50: reasons.append("EMA20<=50")
            if not adx_ok: reasons.append(f"ADX={adx_val:.0f}<22")
            if not di_ok: reasons.append("DI+<=DI-")
            if not cgte50: reasons.append("CLOSE<=EMA50")
            if not e5gt25: reasons.append(f"E5<={sig.iloc[-1]['ema_slow']:.4f}")
            if not cgte25: reasons.append(f"CLOSE<=E25")
            reason_str = "+".join(reasons) if reasons else "-"
            if not reasons and not buy_ok:
                reason_str = "BUG:BUT_SIGNAL_FALSE"
                diag._data["bugs"] += 1
            
            diag.log(
                symbol=sym, has_data="SI",
                vol_ok="SI" if vol_ok else f"NO({vu/1e6:.1f}M)",
                ema20_gt_50="SI" if e20gt50 else "NO",
                adx_ok=f"SI({adx_val:.0f})" if adx_ok else f"NO({adx_val:.0f})",
                di_ok=f"SI({dp.iloc[-1]:.0f}>{dm.iloc[-1]:.0f})" if di_ok else f"NO({dp.iloc[-1]:.0f}<={dm.iloc[-1]:.0f})",
                close_gt_ema50="SI" if cgte50 else "NO",
                screener="SI" if scr_ok else "NO",
                ema5_gt_25=f"SI({sig.iloc[-1]['ema_fast']:.4f}>{sig.iloc[-1]['ema_slow']:.4f})" if e5gt25 else f"NO",
                close_gt_ema25="SI" if cgte25 else "NO",
                vr=f"{vr_val:.2f}",
                buy_signal="SI" if buy_ok else "NO",
                entered="NO",
                fail_reason=reason_str,
            )
            if not scr_ok:
                diag._data["screener_no"] += 1
            elif not buy_ok:
                diag._data["buy_no"] += 1
            else:
                diag._data["no_cap"] += 1  # will be overridden if entered

        active = screen_pairs(candidates, dfs)
        active_set = set(active)
        # Loguear los primeros 20 activos para trazabilidad (no saturar log)
        muestra = " ".join(active[:20])
        resto = len(active) - 20
        if resto > 0:
            muestra += f" ... y {resto} mas"
        logger.info("Activos: %d %s", len(active), muestra if active else "NINGUNO")

        if ts.hour == 0:
            logger.info(
                "═══ RESUMEN DIARIO %s ═══ equity=$%.2f | "
                "trades=%d | abiertas=%d | DD=%+.2f%%",
                ts.strftime("%Y-%m-%d"), self._state.equity,
                self._trade_count(),
                sum(1 for p in self._state.pairs.values() if p.get("position")),
                self._drawdown_pct(),
            )

        # Verificar SL/TP en el mismo ciclo (paper: simulado; live: balance)
        if self._paper:
            self._check_stops_paper(ts, dfs)
        else:
            self._sync_exchange(ts, active_set, dfs)

        # Cerrar pares que salieron del screener
        self._close_removed(ts, active_set)

        # Fase 1: Procesar SALIDAS (exit_signal) de TODOS los activos
        for sym in active:
            try:
                ps = self._state.pairs.get(sym)
                if ps and ps.get("position"):
                    self._process(sym, dfs.get(sym), ts)
            except Exception as exc:
                logger.error("Error en exit de %s: %s", sym, exc)

        # Fase 2: Procesar ENTRADAS hasta MAX_CONCURRENT globales
        open_positions = sum(
            1 for p in self._state.pairs.values() if p.get("position")
        )
        buy_count = 0
        saltados_ts = 0
        saltados_idx = 0
        for sym in active:
            try:
                ps = self._state.pairs.get(sym)
                if ps and ps.get("position"):
                    continue
                df = dfs.get(sym)
                if df is None or len(df) < 200:
                    continue
                # Filtrar al timestamp exacto del ciclo (con tolerancia de 1h)
                if ts not in df.index:
                    saltados_ts += 1
                    logger.info("FASE2_TS: %s no tiene vela en %s, buscando cercano...", sym, ts)
                    nearest = df.index.searchsorted(ts)
                    if nearest > 0 and nearest <= len(df.index):
                        idx = nearest - 1
                        logger.info("FASE2_TS: usando %s en vez de %s", df.index[idx], ts)
                    else:
                        continue
                else:
                    idx = df.index.get_loc(ts)
                if idx < 200:
                    saltados_idx += 1
                    continue
                sub = df.iloc[:idx+1]
                if sym not in self._strategies:
                    self._strategies[sym] = AggressiveTrendStrategy(dict(STRAT_PARAMS))
                sig = self._strategies[sym].generate_signals(sub)
                buy_sig = bool(sig.iloc[-1]["buy_signal"])
                if buy_sig:
                    buy_count += 1
                    if open_positions >= MAX_CONCURRENT:
                        logger.info("BUY_SIGNAL_SIN_CUPO: %s tiene buy_signal pero ya hay %d posiciones", sym, open_positions)
                        continue
                    if sym not in self._state.pairs:
                        effective = min(self._state.equity, MAX_CAPITAL_USDT)
                        capital_en_uso = sum(p["capital"] for p in self._state.pairs.values())
                        disp = max(0.0, effective - capital_en_uso)
                        capital = min(disp * MAX_CAPITAL_PER_TRADE, disp / max(1, len(self._state.pairs) + 1)) if disp > 0 else 0.0
                        self._state.pairs[sym] = {"capital": capital, "trades": []}
                    self._enter(sym, self._state.pairs[sym], ts, sub)
                    if self._state.pairs.get(sym, {}).get("position"):
                        open_positions += 1
                        diag._data["entered"] += 1
                        diag._data["no_cap"] -= 1
            except Exception as exc:
                logger.error("Error en entry de %s: %s", sym, exc)
        logger.info("FASE2: %d buy_signal, %d posiciones | TS_OOB=%d IDX<200=%d",
                    buy_count, open_positions, saltados_ts, saltados_idx)

        # Mostrar resumen del diagnostico por ciclo
        for line in diag.summary().split("\n"):
            logger.info(line)
        diag.export()
        logger.info("CSV diagnostico: %s", diag._path)

        positions = sum(
            1 for p in self._state.pairs.values() if p.get("position")
        )
        dd = self._drawdown_pct()
        logger.info(
            "Equity: $%.2f | DD: %.2f%% | Posiciones: %d | Trades: %d",
            self._state.equity, dd, positions, self._trade_count(),
        )
        # Registrar resumen del ciclo en CSV
        self._cycle_log.log(
            cycle_time=ts.strftime("%Y-%m-%d %H:%M"),
            candidates=len(candidates) if hasattr(self, '_last_candidates') else "",
            screener_passed=len(active),
            open_positions=positions,
            trades_cumulative=self._trade_count(),
            equity=round(self._state.equity, 2),
            peak_equity=round(self._state.peak_equity, 2),
            drawdown_pct=round(dd, 2),
        )
        # Loguear pares que pasaron el screener pero no entraron por limite global
        if len(active) > MAX_CONCURRENT:
            sin_capital = len(active) - MAX_CONCURRENT
            logger.info("SIN_ENTRAR: %d pares pasaron el screener pero no entraron (limite %d)", sin_capital, MAX_CONCURRENT)

    def _trade_count(self) -> int:
        count = 0
        for ps in self._state.pairs.values():
            count += len(ps.get("trades", []))
        return count

    # ── Helper: registrar un trade cerrado ──────────────────────────────

    def _record_close(
        self, sym: str, ps: dict, t, ts: datetime,
    ) -> None:
        pnl_pct = (t.exit_price - t.entry_price) / t.entry_price
        pnl = pnl_pct * t.size * t.entry_price
        self._state.equity += pnl
        self._state.peak_equity = max(self._state.peak_equity, self._state.equity)

        held = str(ts - t.entry_time).split(".")[0] if ts >= t.entry_time else "0:00:00"
        held_hours = round((ts - t.entry_time).total_seconds() / 3600, 1) if ts >= t.entry_time else 0
        max_gain = ps.get("max_gain", 0.0)

        # Leer metadata guardada en el entry
        pos_meta = ps.get("position", {})
        trade_id = pos_meta.get("trade_id", "N/A")
        entry_adx = pos_meta.get("adx", "")
        entry_di_plus = pos_meta.get("di_plus", "")
        entry_di_minus = pos_meta.get("di_minus", "")
        entry_vol = pos_meta.get("vol_ratio", "")
        entry_gap = pos_meta.get("ema_gap", "")

        logger.info(
            "── EXIT ── [%s] %s %s @ %.2f | PnL=%+.2f (%+.2f%%) | "
            "held=%s | max_gain=%+.2f%%",
            trade_id, sym, t.exit_reason, t.exit_price,
            pnl, pnl_pct * 100, held, max_gain,
        )
        logger.info(
            "  entry=%.2f -> exit=%.2f | equity=%.2f DD=%.2f%%",
            t.entry_price, t.exit_price, self._state.equity, self._drawdown_pct(),
        )
        logger.info(
            "  entry_conditions: ADX=%s DI+=%s DI-=%s vol=%s gap=%s%% | "
            "result=%s",
            entry_adx, entry_di_plus, entry_di_minus, entry_vol, entry_gap,
            "WIN" if pnl >= 0 else "LOSS",
        )

        self._log.log(
            equity=self._state.equity,
            symbol=sym, trade_id=trade_id, action="EXIT_" + t.exit_reason,
            price=t.exit_price, size=t.size,
            pnl=round(pnl, 2), reason=t.exit_reason,
            entry_price=round(t.entry_price, 2),
            entry_adx=entry_adx, entry_di_plus=entry_di_plus,
            entry_di_minus=entry_di_minus,
            entry_vol_ratio=entry_vol, entry_ema_gap=entry_gap,
            held_hours=held_hours, max_gain_pct=round(max_gain, 2),
        )
        ps.setdefault("trades", []).append({
            "trade_id": trade_id,
            "exit_time": str(t.exit_time),
            "exit_price": t.exit_price,
            "pnl": pnl,
            "reason": t.exit_reason,
            "entry_adx": entry_adx,
            "entry_di_plus": entry_di_plus,
            "entry_di_minus": entry_di_minus,
            "entry_vol_ratio": entry_vol,
            "entry_ema_gap": entry_gap,
            "max_gain": round(max_gain, 2),
            "held_hours": held_hours,
        })
        ps["position"] = None
        ps["capital"] = self._rm(sym).equity

    # ── SL/TP en paper (simulado con high/low de la vela) ────────────────

    def _check_stops_paper(
        self, ts: datetime, dfs: Dict[str, pd.DataFrame],
    ) -> None:
        for sym, ps in list(self._state.pairs.items()):
            pos = ps.get("position")
            if pos is None:
                continue
            df = dfs.get(sym)
            if df is None or len(df) == 0:
                continue
            row = df.iloc[-1]
            high, low = float(row["high"]), float(row["low"])
            rm = self._rm(sym)
            if len(rm.positions) > 0:
                po = rm.positions[0]
                gain = (po.highest_price - po.entry_price) / po.entry_price * 100
                ps["max_gain"] = max(ps.get("max_gain", 0.0), gain)
                held = str(ts - po.entry_time).split(".")[0] if ts >= po.entry_time else "0:00:00"
                logger.info(
                    "  %s UPDATE | held=%s gain=%+.2f%% | "
                    "H=$%.2f L=$%.2f C=$%.2f | trail=%s dist=%.2f%% | "
                    "SL=$%.2f TP=$%.2f",
                    sym, held, gain, high, low, float(row["close"]),
                    "SÍ" if po.trailing_activated else "no",
                    self._risk_mgrs.get(sym, rm)._stop_cfg.trailing_distance * 100,
                    po.stop_loss, po.take_profit if po.take_profit else 0,
                )
            closed = rm.update_positions(ts, high, low)
            for t in closed:
                self._record_close(sym, ps, t, ts)

    # ── Check de precio cada ~2 minutos entre ciclos 4h ────────────────

    def _check_prices(self) -> None:
        """Obtiene precio actual para cada posicion abierta y revisa SL/TP."""
        changed = False
        for sym, ps in list(self._state.pairs.items()):
            pos = ps.get("position")
            if pos is None:
                continue
            rm = self._risk_mgrs.get(sym)
            if rm is None or len(rm.positions) == 0:
                continue
            try:
                ticker = self._ex.get_ticker(sym)
                current = float(ticker["last"])
            except Exception:
                continue

            po = rm.positions[0]
            old_sl = po.stop_loss
            highest_pos = po.highest_price
            gain = (max(current, highest_pos) - po.entry_price) / po.entry_price * 100
            ps["max_gain"] = max(ps.get("max_gain", 0.0), gain)
            ts = datetime.utcnow()
            closed = rm.update_positions(ts, max(current, highest_pos), current)
            for t in closed:
                self._record_close(sym, ps, t, ts)
                changed = True
            # Sync SL en LIVE si trailing lo movio
            if not self._paper and not closed and len(rm.positions) > 0:
                new_sl = rm.positions[0].stop_loss
                if abs(new_sl - old_sl) > 0.0001:
                    try:
                        self._cancel_orders(sym)
                        self._place_sl_tp(sym, rm.positions[0])
                    except Exception as exc:
                        logger.warning("%s: Error actualizando SL trailing: %s", sym, exc)
        if changed and self._paper:
            self._state.save()

    # ── SL/TP en live (verificar balance en exchange) ────────────────────

    def _sync_exchange(
        self, ts: datetime, active_set: set, dfs: Dict[str, pd.DataFrame],
    ) -> None:
        balances = {b.asset: b for b in self._ex.fetch_balance()}
        for sym, ps in list(self._state.pairs.items()):
            base = sym.split("/")[0]
            bal = balances.get(base)
            has_coins = bal is not None and (bal.free + bal.locked) > 1e-7
            has_pos = ps.get("position") is not None

            if not has_coins and has_pos:
                pos = ps["position"]
                df = dfs.get(sym)
                price = (
                    float(df["close"].iloc[-1])
                    if df is not None and len(df) > 0
                    else pos["entry_price"]
                )
                exit_price = pos["take_profit"] if price > pos["entry_price"] else pos["stop_loss"]
                reason = "TP" if price > pos["entry_price"] else "SL"
                pnl_pct = (exit_price - pos["entry_price"]) / pos["entry_price"]
                pnl = pnl_pct * pos["size"] * pos["entry_price"]
                self._state.equity += pnl
                self._state.peak_equity = max(self._state.peak_equity, self._state.equity)
                logger.info("%s: %S entre ciclos @ %.2f | PnL=%.2f", sym, reason, exit_price, pnl)
                self._log.log(equity=self._state.equity, symbol=sym, action="EXIT_"+reason, price=exit_price, size=pos["size"], pnl=pnl, reason=reason)
                ps["position"] = None

            if not has_coins and not has_pos and sym not in active_set:
                del self._state.pairs[sym]

    # ── Cerrar pares removidos del screener ──────────────────────────────

    def _close_removed(self, ts: datetime, active_set: set) -> None:
        for sym, ps in list(self._state.pairs.items()):
            if sym in active_set:
                continue
            if ps.get("position"):
                pos = ps["position"]
                rm = self._rm(sym)
                # Usar SL real del RiskManager (incluye trailing dinámico)
                if len(rm.positions) > 0:
                    close_price = rm.positions[0].stop_loss
                    closed = rm.close_all_positions(ts, close_price)
                    for t in closed:
                        self._record_close(sym, ps, t, ts)
                else:
                    close_price = pos.get("stop_loss", pos["entry_price"] * (1 - STOP_PARAMS["loss_pct"]))
                    pnl_pct = (close_price - pos["entry_price"]) / pos["entry_price"]
                    pnl = pnl_pct * pos["size"] * pos["entry_price"]
                    self._state.equity += pnl
                    self._state.peak_equity = max(self._state.peak_equity, self._state.equity)
                    logger.info("%s: SCREENER_EXIT @ %.2f | PnL=%.2f", sym, close_price, pnl)
                    self._log.log(equity=self._state.equity, symbol=sym, action="EXIT", price=close_price, size=pos["size"], pnl=pnl, reason="SCREENER_EXIT")
                    ps["position"] = None
                if not self._paper:
                    self._cancel_orders(sym)
                    self._market_sell(sym, pos["size"])
            # Liberar capital: si no tiene posicion y no esta activo, limpiar
            if sym not in active_set and not ps.get("position"):
                del self._state.pairs[sym]
                self._risk_mgrs.pop(sym, None)
                self._strategies.pop(sym, None)

    # ── Procesar un par activo ──────────────────────────────────────────

    def _process(
        self, sym: str, df: Optional[pd.DataFrame], ts: datetime,
    ) -> None:
        if df is None or len(df) < 200:
            logger.warning("%s: datos insuficientes", sym)
            return

        ps = self._state.pairs.get(sym)
        if ps is None:
            effective = min(self._state.equity, MAX_CAPITAL_USDT)
            capital_en_uso = sum(p["capital"] for p in self._state.pairs.values())
            disponible = max(0.0, effective - capital_en_uso)
            if disponible > 0:
                capital = min(
                    disponible * MAX_CAPITAL_PER_TRADE,
                    disponible / max(1, len(self._state.pairs) + 1),
                )
            else:
                capital = 0.0
            self._state.pairs[sym] = {"capital": capital, "trades": []}
            ps = self._state.pairs[sym]

        has_position = ps.get("position") is not None

        if sym not in self._strategies:
            self._strategies[sym] = AggressiveTrendStrategy(dict(STRAT_PARAMS))
        # Filtrar al timestamp exacto del ciclo (con tolerancia)
        if ts not in df.index:
            nearest = df.index.searchsorted(ts)
            if nearest > 0 and nearest <= len(df.index):
                idx = nearest - 1
            else:
                return
        else:
            idx = df.index.get_loc(ts)
        sub = df.iloc[:idx+1]
        sig = self._strategies[sym].generate_signals(sub)
        buy = bool(sig.iloc[-1]["buy_signal"])
        exit_sig = bool(sig.iloc[-1]["exit_signal"])

        if has_position:
            if exit_sig:
                close = float(sub["close"].iloc[-1])
                rm = self._rm(sym)
                closed = rm.close_all_positions(ts, close)
                for t in closed:
                    self._record_close(sym, ps, t, ts)
                if not self._paper:
                    self._cancel_orders(sym)
                    self._market_sell(sym, pos.get("size", 0) if ps.get("position") else 0)
                return

            # Trailing cada ciclo usando high/low de la vela
            row = sub.iloc[-1]
            high, low = float(row["high"]), float(row["low"])
            rm = self._rm(sym)
            old_sl = rm.positions[0].stop_loss if len(rm.positions) > 0 else 0
            closed = rm.update_positions(ts, high, low)
            for t in closed:
                self._record_close(sym, ps, t, ts)
            if closed:
                return
            # Sync SL en LIVE si el trailing lo movio
            if not self._paper and len(rm.positions) > 0:
                new_sl = rm.positions[0].stop_loss
                if abs(new_sl - old_sl) > 0.0001:
                    self._cancel_orders(sym)
                    self._place_sl_tp(sym, rm.positions[0])

        elif buy:
            self._enter(sym, ps, ts, sub)

    # ── Risk Manager ────────────────────────────────────────────────────

    def _rm(self, sym: str) -> RiskManager:
        if sym not in self._risk_mgrs:
            ps = self._state.pairs.get(sym, {})
            effective = min(self._state.equity, MAX_CAPITAL_USDT)
            capital = ps.get("capital", min(
                effective * MAX_CAPITAL_PER_TRADE,
                effective / max(1, len(self._state.pairs)),
            ))
            self._risk_mgrs[sym] = RiskManager(
                CapitalConfig(initial=capital),
                RiskConfig(**RISK_PARAMS),
                StopConfig(**STOP_PARAMS),
            )
        return self._risk_mgrs[sym]

    # ── Entry ───────────────────────────────────────────────────────────

    def _enter(
        self, sym: str, ps: dict, ts: datetime, df: pd.DataFrame,
    ) -> None:
        # Validar que el par aun existe y esta listado
        if not self._paper:
            try:
                self._ex.get_ticker(sym)
            except Exception:
                logger.warning("%s: par no encontrado en exchange — saltando", sym)
                return

        close = float(df["close"].iloc[-1])
        rm = self._rm(sym)

        # ADX+Vol dinámico y metadata de entrada
        adx_val, di_plus, di_minus, vol_r = compute_adx_vol(df)
        row = df.iloc[-1]
        ema5 = float(df["close"].astype(float).ewm(span=5, adjust=False).mean().iloc[-1])
        ema20 = float(df["close"].astype(float).ewm(span=20, adjust=False).mean().iloc[-1])
        low = float(row["low"])
        open_p = float(row["open"])
        ema_gap = (ema5 / ema20 - 1) * 100
        pullback_ok = low <= ema5 * 1.03
        bounce_ok = (close > open_p) and (low <= ema5) and (close > ema5)
        entry_conditions = {
            "adx": round(adx_val, 1), "di_plus": round(di_plus, 1),
            "di_minus": round(di_minus, 1), "vol_ratio": round(vol_r, 2),
            "ema5": round(ema5, 2), "ema20": round(ema20, 2),
            "ema_gap": round(ema_gap, 2), "pullback": "OK" if pullback_ok else "NO",
            "bounce": "OK" if bounce_ok else "NO",
        }

        self._trade_counter += 1
        trade_id = f"ALCISTA_{ts.strftime('%Y%m%d')}_{self._trade_counter:04d}"

        tp_pct = get_tp_adx_vol(adx_val, vol_r)
        tp_price = close * (1.0 + tp_pct)

        pos = rm.open_position(ts, close, take_profit_price=tp_price)
        if pos is None:
            return

        logger.info(
            "── ENTRY ── [%s] %s BUY @ %.2f | size=%.4f | SL=%.2f TP=%.2f",
            trade_id, sym, close, pos.size, pos.stop_loss, pos.take_profit,
        )
        logger.info(
            "  ADX=%.1f DI+=%.1f DI-=%.1f vol=%.2f | "
            "EMA5=%.2f EMA20=%.2f gap=%+.2f%%",
            adx_val, di_plus, di_minus, vol_r,
            ema5, ema20, ema_gap,
        )
        logger.info(
            "  pullback: low=%.2f <= EMA5*1.03=%.2f %s | "
            "bounce: close>open=%.2f>%.2f %s",
            low, ema5 * 1.03, "OK" if pullback_ok else "NO",
            close, open_p, "OK" if bounce_ok else "NO",
        )
        self._log.log(
            equity=self._state.equity,
            symbol=sym, trade_id=trade_id, action="BUY",
            price=close, size=pos.size, pnl=0, reason="",
            entry_price=close,
            entry_adx=entry_conditions["adx"],
            entry_di_plus=entry_conditions["di_plus"],
            entry_di_minus=entry_conditions["di_minus"],
            entry_vol_ratio=entry_conditions["vol_ratio"],
            entry_ema_gap=entry_conditions["ema_gap"],
        )

        if not self._paper:
            order_size = pos.size
            order_value = close * order_size
            
            # Pre-validaciones antes de enviar orden
            try:
                balance_usdt = self._get_real_balance()
            except Exception:
                balance_usdt = self._state.equity
            
            logger.info("[%s] %s: Pre-validando orden | size=%.6f | value=$%.2f | balance=$%.2f",
                       trade_id, sym, order_size, order_value, balance_usdt)
            
            if order_value < 10.0:
                logger.error("[%s] %s: ORDEN RECHAZADA — valor $%.2f < min_notional (~$10)",
                            trade_id, sym, order_value)
                rm._positions.pop()
                return
            
            if balance_usdt < order_value * 1.01:
                logger.error("[%s] %s: ORDEN RECHAZADA — balance $%.2f insuficiente para compra de $%.2f",
                            trade_id, sym, balance_usdt, order_value)
                rm._positions.pop()
                return
            
            # Enviar orden market buy con reintentos
            order_ok = False
            last_error = ""
            for attempt in range(3):
                try:
                    self._ex.create_order(Order(
                        symbol=sym, side="buy", order_type="market",
                        quantity=order_size,
                    ))
                    order_ok = True
                    break
                except Exception as exc:
                    last_error = str(exc)
                    error_msg = str(exc).lower()
                    if "rate" in error_msg or "timeout" in error_msg or "timed" in error_msg:
                        if attempt < 2:
                            logger.warning("[%s] %s: Reintentando (%d/3) tras error transitorio: %s",
                                          trade_id, sym, attempt+1, str(exc)[:100])
                            import time as _time
                            _time.sleep(5)
                            continue
                    if "insufficient" in error_msg or "balance" in error_msg or "fund" in error_msg:
                        logger.error("[%s] %s: MARKET BUY RECHAZADO — fondos insuficientes | "
                                    "balance=$%.2f | order=$%.2f (size=%.6f)",
                                    trade_id, sym, balance_usdt, order_value, order_size)
                        break
                    elif "notional" in error_msg or "min" in error_msg:
                        logger.error("[%s] %s: MARKET BUY RECHAZADO — min_notional | "
                                    "order=$%.2f | par=%s",
                                    trade_id, sym, order_value, sym)
                        break
                    elif "closed" in error_msg or "market is closed" in error_msg:
                        logger.error("[%s] %s: MARKET BUY RECHAZADO — mercado cerrado/delistado",
                                    trade_id, sym)
                        break
                    else:
                        logger.error("[%s] %s: MARKET BUY RECHAZADO — %s | "
                                    "balance=$%.2f order=$%.2f size=%.6f",
                                    trade_id, sym, last_error[:100],
                                    balance_usdt, order_value, order_size)
                        break
            
            if not order_ok:
                logger.error("[%s] %s: MARKET BUY FALLÓ tras %d intentos: %s",
                            trade_id, sym, 3 if attempt >= 2 else attempt+1, last_error[:100])
                rm._positions.pop()
                return
            if not self._place_sl_tp(sym, pos):
                logger.error("[%s] %s: SL/TP no colocado — revirtiendo compra", trade_id, sym)
                try:
                    self._ex.create_order(Order(symbol=sym, side="sell", order_type="market", quantity=pos.size))
                except Exception as exc2:
                    logger.error("[%s] %s: Error revirtiendo compra: %s", trade_id, sym, exc2)
                rm._positions.pop()
                return

        ps["position"] = {
            "entry_price": close,
            "entry_time": ts.isoformat(),
            "trade_id": trade_id,
            "size": pos.size,
            "stop_loss": pos.stop_loss,
            "take_profit": pos.take_profit,
            **entry_conditions,
        }

    # ── Órdenes (solo live) ─────────────────────────────────────────────

    def _cancel_orders(self, sym: str) -> None:
        if self._paper:
            return
        ps = self._state.pairs.get(sym)
        if not ps or not ps.get("position"):
            return
        pos = ps["position"]
        for oid_key in ("sl_order_id", "tp_order_id"):
            oid = pos.get(oid_key)
            if oid:
                try:
                    self._ex.cancel_order(oid, sym)
                except Exception:
                    pass

    def _place_sl_tp(self, sym: str, pos) -> bool:
        """Coloca SL y TP en Binance. Devuelve True si ambas se colocaron."""
        sl_id = ""
        tp_id = ""
        sl_ok = False
        tp_ok = False
        trade_id = ""
        ps = self._state.pairs.get(sym, {})
        if ps.get("position"):
            trade_id = ps["position"].get("trade_id", "")
        try:
            sl_id = self._ex._client.create_order(
                symbol=sym.replace("/", ""),
                type="STOP_LOSS_LIMIT",
                side="sell",
                amount=pos.size,
                price=round(pos.stop_loss * 0.995, 8),
                params={"stopPrice": pos.stop_loss},
            )
            sl_ok = True
        except Exception as exc:
            logger.warning("[%s] %s: Error STOP_LOSS order: %s", trade_id, sym, exc)
        try:
            tp_id = self._ex.create_order(Order(
                symbol=sym, side="sell", order_type="limit",
                quantity=pos.size, price=pos.take_profit,
            ))
            tp_ok = True
        except Exception as exc:
            logger.warning("[%s] %s: Error TAKE_PROFIT order: %s", trade_id, sym, exc)
        if ps.get("position"):
            ps["position"]["sl_order_id"] = sl_id
            ps["position"]["tp_order_id"] = tp_id
        return sl_ok and tp_ok

    def _market_sell(self, sym: str, size: float) -> None:
        try:
            self._ex.create_order(Order(
                symbol=sym, side="sell", order_type="market", quantity=size,
            ))
        except Exception as exc:
            logger.error("%s: Error market sell: %s", sym, exc)

    # ── Drawdown ────────────────────────────────────────────────────────

    def _drawdown_pct(self) -> float:
        self._state.peak_equity = max(self._state.peak_equity, self._state.equity)
        if self._state.peak_equity == 0:
            return 0.0
        return (
            (self._state.peak_equity - self._state.equity)
            / self._state.peak_equity * 100
        )


# ── Entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Alcista — Paper / Live Trading (REST cada 4h)"
    )
    parser.add_argument("--live", action="store_true", help="Operar en Binance LIVE (default: paper)")
    args = parser.parse_args()
    paper = not args.live

    if paper:
        # Sin keys, solo datos públicos
        exchange = BinanceExchange(api_key="", api_secret="", testnet=False)
    else:
        api_key = os.getenv("EXCHANGE_API_KEY", "")
        api_secret = os.getenv("EXCHANGE_API_SECRET", "")
        if not api_key or not api_secret:
            print("ERROR: --live requiere EXCHANGE_API_KEY y EXCHANGE_API_SECRET en .env")
            sys.exit(1)
        exchange = BinanceExchange(api_key=api_key, api_secret=api_secret, testnet=False)

    runner = LiveRunner(exchange, paper=paper)
    try:
        runner.run()
    except KeyboardInterrupt:
        logger.info("Detenido por usuario")
    except Exception as exc:
        logger.exception("Error fatal: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
