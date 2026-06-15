import asyncio
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from config.settings import SETTINGS
from src.exchange.binance_exchange import BinanceExchange
from src.exchange.websocket import BinanceWebSocket
from src.portfolio.manager import PortfolioManager
from src.screener.market_screener import MarketScreener
from src.strategies.aggressive_trend import AggressiveTrendStrategy
from src.utils.logger import setup_logger

logger = setup_logger("live", Path("logs"))


class LiveTrader:
    def __init__(self, testnet: bool = False) -> None:
        self._exchange = BinanceExchange(testnet=testnet)
        self._screener = MarketScreener(
            exchange=self._exchange,
            min_volume_usd=SETTINGS.screener.min_volume_usd,
            max_candidates=SETTINGS.screener.max_candidates,
            max_results=SETTINGS.screener.max_results,
        )
        self._portfolio = PortfolioManager(
            total_capital=SETTINGS.capital.initial,
            risk_per_trade_pct=SETTINGS.risk.per_trade,
            max_drawdown=SETTINGS.risk.max_drawdown,
            max_concurrent_pairs=SETTINGS.screener.max_results,
            stop_loss_pct=SETTINGS.stops.loss_pct,
            take_profit_pct=SETTINGS.stops.take_profit_pct,
            break_even_trigger=SETTINGS.stops.break_even_trigger,
            trailing_activation=SETTINGS.stops.trailing_activation,
            trailing_distance=SETTINGS.stops.trailing_distance,
        )
        self._strategies: Dict[str, AggressiveTrendStrategy] = {}
        self._ws: Optional[BinanceWebSocket] = None
        self._running = False
        self._scan_interval = 6

    async def run(self) -> None:
        self._running = True
        logger.info("LiveTrader iniciando...")

        pairs = self._exchange.fetch_top_usdt_pairs(
            n=SETTINGS.screener.max_candidates,
            min_volume_usd=SETTINGS.screener.min_volume_usd,
        )
        if not pairs:
            pairs = ["BTC/USDT", "ETH/USDT"]

        logger.info("Conectando WebSocket a %d pares...", len(pairs))
        self._ws = BinanceWebSocket(pairs, SETTINGS.exchange.timeframe)
        self._ws.on_candle(self._on_candle)

        asyncio.create_task(self._periodic_scan())
        await self._ws.start()

    def stop(self) -> None:
        self._running = False
        if self._ws:
            self._ws.stop()

    def _on_candle(self, symbol: str, candle: pd.Series) -> None:
        try:
            self._process_candle(symbol, candle)
        except Exception as e:
            logger.error("Error procesando %s: %s", symbol, e)

    def _process_candle(self, symbol: str, candle: pd.Series) -> None:
        ts = candle["timestamp"]
        high = candle["high"]
        low = candle["low"]
        close = candle["close"]

        closed = self._portfolio.update_positions(ts, symbol, high, low)
        for t in closed:
            logger.info("%s: EXIT @ %.2f | PnL=%.2f | %s", symbol, t.exit_price, t.pnl, t.exit_reason)

        alloc = self._portfolio.get_allocation(symbol)
        if alloc is None:
            return

        has_position = len(alloc.risk_mgr.positions) > 0
        if symbol not in self._strategies:
            self._strategies[symbol] = AggressiveTrendStrategy({
                "ema_fast": SETTINGS.strategy.ema_fast,
                "ema_slow": SETTINGS.strategy.ema_slow,
                "adx_threshold": SETTINGS.strategy.adx_threshold,
                "volume_threshold": SETTINGS.strategy.volume_threshold,
                "pullback_mode": False,
            })

        strategy = self._strategies[symbol]
        df = pd.DataFrame(
            {"open": [candle["open"]], "high": [high], "low": [low], "close": [close], "volume": [candle["volume"]]},
            index=[ts],
        )
        signals = strategy.generate_signals(df)

        if not has_position and signals.iloc[-1]["buy_signal"] == 1:
            pos = self._portfolio.open_position(symbol, ts, close)
            if pos:
                logger.info("%s: BUY @ %.2f | SL=%.2f TP=%.2f", symbol, close, pos.stop_loss, pos.take_profit)

        if has_position and signals.iloc[-1]["exit_signal"] == 1:
            closed = self._portfolio.close_pair_positions(symbol, close, ts)
            for t in closed:
                logger.info("%s: EXIT SIGNAL @ %.2f | PnL=%.2f", symbol, t.exit_price, t.pnl)

    async def _periodic_scan(self) -> None:
        scan_count = 0
        while self._running:
            try:
                if scan_count % self._scan_interval == 0:
                    bull_pairs = self._screener.scan()
                    self._portfolio.update_screened_pairs(bull_pairs)
                    n = sum(1 for p in bull_pairs if p.is_bull)
                    logger.info("Screener: %d pares en tendencia activos | Equity=%.2f DD=%.2f%%",
                                n, self._portfolio.equity, self._portfolio.drawdown * 100)
                scan_count += 1
            except Exception as e:
                logger.error("Error en periodic_scan: %s", e)
            await asyncio.sleep(3600)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Alcista — Live Trading Multi-Par")
    parser.add_argument("--testnet", action="store_true", default=False)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    trader = LiveTrader(testnet=not args.live)
    try:
        asyncio.run(trader.run())
    except KeyboardInterrupt:
        trader.stop()
        logger.info("LiveTrader detenido")


if __name__ == "__main__":
    main()
