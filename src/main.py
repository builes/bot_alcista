import argparse
import json
from pathlib import Path

from config.settings import SETTINGS
from src.backtesting.engine import BacktestEngine
from src.backtesting.multi_engine import MultiPairBacktestEngine
from src.backtesting.optimizer import Optimizer, OptimizerConfig
from src.exchange.binance_exchange import BinanceExchange
from src.screener.market_screener import MarketScreener
from src.utils.logger import setup_logger

logger = setup_logger("main", SETTINGS.logs_dir)


def cmd_backtest(args: argparse.Namespace) -> None:
    data_path = Path(args.data)
    engine = BacktestEngine(SETTINGS)
    result = engine.run(data_path)
    _print_metrics("BACKTEST", result.metrics)
    if args.output:
        Path(args.output).write_text(json.dumps(result.metrics, indent=2))


def cmd_multi_backtest(args: argparse.Namespace) -> None:
    data_dir = Path(args.data_dir)
    screen_fast = SETTINGS.strategy.ema_fast or 20
    screen_slow = SETTINGS.strategy.ema_slow or 50
    engine = MultiPairBacktestEngine(
        SETTINGS,
        strategy_params={
            "ema_fast": screen_fast,
            "ema_slow": screen_slow,
            "adx_threshold": SETTINGS.strategy.adx_threshold,
            "volume_threshold": SETTINGS.strategy.volume_threshold,
            "pullback_mode": False,
        },
        max_pairs=args.max_pairs or 10,
        min_volume_usd=1_000_000,
        screen_ema_fast=screen_fast,
        screen_ema_slow=screen_slow,
    )
    result = engine.run(data_dir)
    _print_metrics("MULTI-BACKTEST", result.metrics)
    if args.output:
        Path(args.output).write_text(json.dumps({
            "metrics": result.metrics,
            "total_pairs": args.max_pairs or 10,
        }, indent=2))


def cmd_scan(args: argparse.Namespace) -> None:
    ex = BinanceExchange(testnet=False)
    screener = MarketScreener(
        exchange=ex,
        min_volume_usd=args.min_volume or 1_000_000,
        max_candidates=args.max_candidates or 100,
        max_results=args.top or 10,
    )
    results = screener.scan()
    print(f"\nTop {len(results)} pares en tendencia alcista:\n")
    print(f"{'Par':<16} {'Precio':<12} {'Vol 24h':<14} {'Score':<10} {'ADX':<8} {'Bull':<6}")
    print("-" * 66)
    for p in results:
        vol_str = f"${p.volume_24h_usd:,.0f}" if p.volume_24h_usd > 0 else "N/A"
        print(f"{p.symbol:<16} {p.close_price:<12.2f} {vol_str:<14} {p.trend_score:<10.2f} {p.adx:<8.1f} {'YES' if p.is_bull else 'NO'}")


def cmd_optimize(args: argparse.Namespace) -> None:
    data_path = Path(args.data)
    param_grid = {
        "ema_fast": [30, 50, 70],
        "ema_slow": [150, 200, 250],
        "adx_threshold": [20, 25, 30],
        "volume_threshold": [0.8, 1.0, 1.2],
        "pullback_tolerance": [0.005, 0.01, 0.02],
    }
    opt_config = OptimizerConfig(
        param_grid=param_grid,
        maximize=args.metric or "sharpe_ratio",
        min_trades=args.min_trades or 10,
        max_drawdown_limit=args.max_dd or 30.0,
    )
    optimizer = Optimizer(SETTINGS, opt_config)
    best_params, result = optimizer.optimize(data_path)
    print("\nBest parameters:")
    for key, val in best_params.items():
        print(f"  {key}: {val}")
    if result:
        _print_metrics("OPTIMIZATION", result.metrics)
    if args.output and result:
        Path(args.output).write_text(json.dumps({"best_params": best_params, "metrics": result.metrics}, indent=2))


def _print_metrics(title: str, metrics: dict) -> None:
    print(f"\n{'=' * 54}")
    print(f"  {title}")
    print(f"{'=' * 54}")
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    print(f"{'=' * 54}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Alcista — Bot Long-Only Multi-Par")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("backtest", help="Backtest de un solo par")
    p.add_argument("--data", required=True)
    p.add_argument("--output")

    p = sub.add_parser("multi-backtest", help="Backtest multi-par simultáneo")
    p.add_argument("--data-dir", required=True, help="Directorio con archivos *_4h.csv")
    p.add_argument("--max-pairs", type=int, default=10, help="Máximo de pares simultáneos")
    p.add_argument("--output")

    p = sub.add_parser("scan", help="Escanea top 100 pares USDT en tendencia alcista")
    p.add_argument("--min-volume", type=float, default=1_000_000, help="Volumen 24h mínimo USD")
    p.add_argument("--max-candidates", type=int, default=100, help="Candidatos a evaluar")
    p.add_argument("--top", type=int, default=10, help="Resultados a mostrar")

    p = sub.add_parser("optimize", help="Optimizar parámetros")
    p.add_argument("--data", required=True)
    p.add_argument("--metric", default="sharpe_ratio")
    p.add_argument("--min-trades", type=int, default=10)
    p.add_argument("--max-dd", type=float, default=30.0)
    p.add_argument("--output")

    args = parser.parse_args()

    if args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "multi-backtest":
        cmd_multi_backtest(args)
    elif args.command == "scan":
        cmd_scan(args)
    elif args.command == "optimize":
        cmd_optimize(args)


if __name__ == "__main__":
    main()
