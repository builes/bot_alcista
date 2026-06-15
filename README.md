# Alcista — Bot de Trading Long-Only

Bot algorítmico para operar exclusivamente en mercados alcistas, combinando
análisis técnico con gestión de riesgo sistemática.

## Estrategia

**Trend Following Long-Only** basada en:

| Componente | Rol |
|---|---|
| EMA 50 / EMA 200 | Identifica estructura de tendencia alcista |
| ADX + DI± | Confirma fuerza y dirección de la tendencia |
| Volumen (SMA 20) | Filtra movimientos sin respaldo |
| Pullback a EMA 50 | Punto de entrada de baja varianza |

### Entrada (todas las condiciones deben cumplirse)

1. **EMA 50 > EMA 200** — tendencia alcista estructural
2. **ADX > 25** — tendencia con fuerza suficiente
3. **DI+ > DI−** — momentum direccional positivo
4. **Precio > EMA 200** — estructura bullish confirmada
5. **Volumen > SMA 20** — respaldo de volumen
6. **Pullback a EMA 50** — precio toca o se acerca a EMA 50
7. **Vela de rechazo** — cierre por encima de EMA 50 tras el pullback

### Salida

- **Stop Loss** fijo (% configurable)
- **Take Profit** fijo (% configurable)
- **Trailing Stop** se activa tras alcanzar cierto umbral de ganancia
- **Break Even** se activa tras mover el precio un % a favor
- **Señal de reversión** si EMA 50 < EMA 200 o DI+ < DI− (cierre total)

## Gestión de Riesgo

| Parámetro | Defecto | Descripción |
|---|---|---|
| `RISK_PER_TRADE` | 1% | Capital arriesgado por operación |
| `MAX_DRAWDOWN` | 20% | Drawdown máximo antes de parar |
| `MAX_CONCURRENT_POSITIONS` | 3 | Posiciones abiertas simultáneas |
| `MIN_TRADE_INTERVAL_DAYS` | 3 | Días mínimos entre trades |
| `STOP_LOSS_PCT` | 2% | Stop loss fijo |
| `TAKE_PROFIT_PCT` | 6% | Take profit fijo |
| `TRAILING_ACTIVATION_PCT` | 1.5% | Activación del trailing |
| `TRAILING_DISTANCE_PCT` | 1.5% | Distancia del trailing stop |

## Instalación

```bash
# 1. Clonar o copiar el proyecto
cd bot_trading_alcista

# 2. Crear y activar virtualenv
python3 -m venv venv
source venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar (opcional — editar .env)
cp .env.example .env
```

## Uso

### Backtest

```bash
python -m src.main backtest --data data/mi_data.csv
```

Guardar resultados:
```bash
python -m src.main backtest --data data/mi_data.csv --output resultados.json
```

### Optimización de parámetros

```bash
python -m src.main optimize --data data/mi_data.csv
```

Optimizar maximizando Profit Factor:
```bash
python -m src.main optimize --data data/mi_data.csv --metric profit_factor --min-trades 15 --max-dd 25
```

### Tests

```bash
python -m pytest tests/ -v
```

## Estructura del Proyecto

```
bot_trading_alcista/
├── config/
│   ├── __init__.py
│   └── settings.py          # Configuración vía env vars
├── src/
│   ├── main.py              # CLI: backtest / optimize
│   ├── data/
│   │   └── loader.py        # Carga de datos OHLCV
│   ├── strategies/
│   │   ├── base.py          # Clase abstracta BaseStrategy
│   │   └── trend_following.py  # Estrategia principal
│   ├── risk/
│   │   └── manager.py       # Gestión de riesgo y posiciones
│   ├── backtesting/
│   │   ├── engine.py        # Motor de backtesting
│   │   └── optimizer.py     # Optimización de parámetros
│   ├── metrics/
│   │   └── calculator.py    # Métricas de rendimiento
│   ├── exchange/
│   │   └── base.py          # Interfaz abstracta para exchanges
│   └── utils/
│       └── logger.py        # Logging
├── tests/
│   ├── test_strategy.py
│   ├── test_risk.py
│   ├── test_backtest.py
│   └── test_metrics.py
├── logs/
├── requirements.txt
├── .env.example
└── README.md
```

## Métricas Calculadas

| Métrica | Descripción |
|---|---|
| Sharpe Ratio | Rendimiento ajustado por riesgo (anualizado) |
| Profit Factor | Ganancia bruta / Pérdida bruta |
| Win Rate | % de operaciones ganadoras |
| Max Drawdown | Caída máxima desde el pico |
| Expectancy | Valor esperado por operación |
| Avg Win / Avg Loss | Promedio de ganancias y pérdidas |

## Conexión con Exchange

`src/exchange/base.py` define la interfaz abstracta. Para conectar con un
exchange real (Binance, Coinbase, etc.):

1. Crear una clase que herede de `BaseExchange`
2. Implementar los métodos `fetch_ohlcv`, `create_order`, etc.
3. Usar la API key del exchange (almacenada en `.env`)
4. Consumir datos en vivo y ejecutar señales

Ejemplo mínimo con CCXT:

```python
import ccxt
from src.exchange.base import BaseExchange, Order

class BinanceExchange(BaseExchange):
    def __init__(self, api_key, api_secret):
        self.client = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
        })

    def fetch_ohlcv(self, symbol, timeframe, limit=500):
        ohlcv = self.client.fetch_ohlcv(symbol, timeframe, limit=limit)
        # Convertir a DataFrame...
```

## Licencia

MIT
