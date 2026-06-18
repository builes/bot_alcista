"""Live / Paper trading — REST polling cada 4h (cierre de vela UTC).
Version SIN pullback (entra sin esperar rebote en EMA5).
Reutiliza AggressiveTrendStrategy, RiskManager, BinanceExchange.

Modos:
  --paper  (default)  Simulación sin API keys. Solo datos públicos.
  --live              Opera en Binance real con API keys de .env
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
INITIAL_CAPITAL = 100_000.0
MAX_CONCURRENT = 10
MAX_CANDIDATES = 100
MIN_VOLUME_USD = 500_000

STABLECOINS = {"USDC", "USD1", "FDUSD", "EUR", "RLUSD", "TUSD", "BUSD", "USDE", "U", "BFUSD", "XUSD", "USDP", "USDS"}

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
    "per_trade": 0.03,
    "max_drawdown": 0.30,
    "max_concurrent": 1,
    "min_interval_days": 0,
}

STOP_PARAMS = {
    "loss_pct": 0.01,
    "take_profit_pct": 0.04,
    "break_even_trigger": 0.005,
    "trailing_activation": 0.015,
    "trailing_distance": 0.01,
}

logger = setup_logger("live_nopb", Path("logs"))


# ── Screener ────────────────────────────────────────────────────────────────


def screen_pairs(
    pairs: List[str], dfs: Dict[str, pd.DataFrame]
) -> List[str]:
    """EMA20 > EMA50 + ADX >= 20 + DI+ > DI- en 4h."""
    results: List[str] = []
    for sym in pairs:
        base = sym.split("/")[0]
        if base in STABLECOINS:
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
    return results[:MAX_CONCURRENT]


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

STATE_FILE = Path("live_state_nopb.json")


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
        self._file = Path("logs") / f"trades_nopb_{ts}.csv"
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


# ── Orquestador ────────────────────────────────────────────────────────────


class LiveRunner:
    def __init__(self, exchange: BinanceExchange, paper: bool = True) -> None:
        self._ex = exchange
        self._paper = paper
        self._state = LiveState.load()
        self._strategies: Dict[str, AggressiveTrendStrategy] = {}
        self._risk_mgrs: Dict[str, RiskManager] = {}
        self._log = TradeLogger()
        self._trade_counter = 0

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

            # Check prices every ~2 minutos entre ciclos (solo paper)
            while wait > 5:
                chunk = min(120.0, wait - 1)
                time.sleep(chunk)
                if self._paper:
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
                self._state.save()
            except Exception as exc:
                logger.exception("Error en ciclo: %s", exc)
                time.sleep(60)

    # ── Ciclo 4h ────────────────────────────────────────────────────────

    def _cycle(self, ts: datetime) -> None:
        logger.info("─── CICLO %s UTC ───", ts.strftime("%Y-%m-%d %H:%M"))

        candidates = self._ex.fetch_top_usdt_pairs(MAX_CANDIDATES, MIN_VOLUME_USD)
        if not candidates:
            logger.warning("No se obtuvieron pares.")
            return
        logger.info("Candidatos: %d", len(candidates))

        dfs = self._ex.fetch_multiple_ohlcv(candidates, "4h", 220)

        active = screen_pairs(candidates, dfs)
        active_set = set(active)
        logger.info("Activos: %d %s", len(active), " ".join(active) if active else "")

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

        # Procesar señales
        for sym in active:
            try:
                self._process(sym, dfs.get(sym), ts)
            except Exception as exc:
                logger.error("Error en %s: %s", sym, exc)

        positions = sum(
            1 for p in self._state.pairs.values() if p.get("position")
        )
        dd = self._drawdown_pct()
        logger.info(
            "Equity: $%.2f | DD: %.2f%% | Posiciones: %d | Trades: %d",
            self._state.equity, dd, positions, self._trade_count(),
        )

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
            highest_pos = po.highest_price
            gain = (max(current, highest_pos) - po.entry_price) / po.entry_price * 100
            ps["max_gain"] = max(ps.get("max_gain", 0.0), gain)
            ts = datetime.utcnow()
            closed = rm.update_positions(ts, max(current, highest_pos), current)
            for t in closed:
                self._record_close(sym, ps, t, ts)
                changed = True
        if changed:
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
                close = pos["entry_price"]
                pnl_pct = -STOP_PARAMS["loss_pct"]
                pnl = pnl_pct * pos["size"] * pos["entry_price"]
                self._state.equity += pnl
                self._state.peak_equity = max(self._state.peak_equity, self._state.equity)
                logger.info("%s: SCREENER_EXIT (est. PnL=%.2f)", sym, pnl)
                self._log.log(equity=self._state.equity, symbol=sym, action="EXIT", price=close, size=pos["size"], pnl=pnl, reason="SCREENER_EXIT")
                ps["position"] = None
                if not self._paper:
                    self._cancel_orders(sym)
                    self._market_sell(sym, pos["size"])

    # ── Procesar un par activo ──────────────────────────────────────────

    def _process(
        self, sym: str, df: Optional[pd.DataFrame], ts: datetime,
    ) -> None:
        if df is None or len(df) < 200:
            logger.warning("%s: datos insuficientes", sym)
            return

        ps = self._state.pairs.get(sym)
        if ps is None:
            capital = self._state.equity / MAX_CONCURRENT
            self._state.pairs[sym] = {"capital": capital, "trades": []}
            ps = self._state.pairs[sym]

        has_position = ps.get("position") is not None

        if sym not in self._strategies:
            self._strategies[sym] = AggressiveTrendStrategy(dict(STRAT_PARAMS))
        sig = self._strategies[sym].generate_signals(df)
        buy = bool(sig.iloc[-1]["buy_signal"])
        exit_sig = bool(sig.iloc[-1]["exit_signal"])

        if has_position:
            if exit_sig:
                close = float(df["close"].iloc[-1])
                rm = self._rm(sym)
                closed = rm.close_all_positions(ts, close)
                for t in closed:
                    self._record_close(sym, ps, t, ts)
                if not self._paper:
                    self._cancel_orders(sym)
                    self._market_sell(sym, pos.get("size", 0) if ps.get("position") else 0)
                return

            # Trailing cada ciclo (solo paper; en live lo manejan las órdenes)
            if self._paper:
                row = df.iloc[-1]
                high, low = float(row["high"]), float(row["low"])
                rm = self._rm(sym)
                closed = rm.update_positions(ts, high, low)
                for t in closed:
                    self._record_close(sym, ps, t, ts)
                if closed:
                    return

        elif buy:
            self._enter(sym, ps, ts, df)

    # ── Risk Manager ────────────────────────────────────────────────────

    def _rm(self, sym: str) -> RiskManager:
        if sym not in self._risk_mgrs:
            ps = self._state.pairs.get(sym, {})
            capital = ps.get("capital", self._state.equity / MAX_CONCURRENT)
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
            try:
                self._ex.create_order(Order(
                    symbol=sym, side="buy", order_type="market",
                    quantity=pos.size,
                ))
            except Exception as exc:
                logger.error("%s: Error market buy: %s", sym, exc)
                rm._positions.pop()
                return
            self._place_sl_tp(sym, pos)

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

    def _place_sl_tp(self, sym: str, pos) -> None:
        sl_id = ""
        tp_id = ""
        try:
            sl_id = self._ex.create_stop_loss_order(sym, pos.size, pos.stop_loss)
        except Exception as exc:
            logger.warning("%s: Error SL order: %s", sym, exc)
        try:
            tp_id = self._ex.create_order(Order(
                symbol=sym, side="sell", order_type="limit",
                quantity=pos.size, price=pos.take_profit,
            ))
        except Exception as exc:
            logger.warning("%s: Error TP order: %s", sym, exc)
        ps = self._state.pairs.get(sym, {})
        if ps.get("position"):
            ps["position"]["sl_order_id"] = sl_id
            ps["position"]["tp_order_id"] = tp_id

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
