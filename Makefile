.PHONY: help simulate-8d update-data backtest-v21 test scan optimize live-paper clean

help:
	@echo "═══════════════════════════════════════"
	@echo "  Alcista — Bot Trading"
	@echo "═══════════════════════════════════════"
	@echo ""
	@echo " COMANDOS DISPONIBLES:"
	@echo ""
	@echo "  make simulate-8d    Simula live runner v2.1 en ultimos 8 dias (\$$150)"
	@echo "  make update-data    Descarga velas 4h recientes de Binance"
	@echo "  make backtest-v21   Backtest v2.1 multiciclo con friction"
	@echo "  make test           Ejecuta tests (pytest)"
	@echo "  make scan           Escanea top pares alcistas en Binance"
	@echo "  make optimize       Optimiza parametros en BTC/USDT"
	@echo "  make live-paper     Inicia paper trading (simulacion)"
	@echo "  make clean          Limpia __pycache__ y .pytest_cache"
	@echo ""

simulate-8d:
	python scripts/simulate_live.py

update-data:
	python scripts/update_data.py

backtest-v21:
	python scripts/backtest_v21.py

test:
	python -m pytest tests/ -v

scan:
	python src/main.py scan --top 15

optimize:
	python src/main.py optimize --data data/BTC_USDT_4h_2y.csv --metric sharpe_ratio --output results/optimization_results.json

live-paper:
	python scripts/run_live_nopb_v2.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null
	rm -rf .mypy_cache .ruff_cache
	@echo "Cache cleaned"
