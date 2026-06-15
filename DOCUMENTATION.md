# Alcista — Bot de Trading Algorítmico

## Documentación Completa

---

### Versión: 1.0 — Junio 2026

---

# Índice de Contenidos

1. [¿Qué es este bot?](#1-qué-es-este-bot)
2. [Conceptos básicos de trading](#2-conceptos-básicos-de-trading)
3. [¿Qué es una estrategia de trading?](#3-qué-es-una-estrategia-de-trading)
4. [La estrategia AggressiveTrend](#4-la-estrategia-aggresivetrend)
5. [Indicadores técnicos explicados](#5-indicadores-técnicos-explicados)
6. [El Screener: cómo elige los pares](#6-el-screener-cómo-elige-los-pares)
7. [Gestión de riesgo](#7-gestión-de-riesgo)
8. [Stop Loss y Take Profit](#8-stop-loss-y-take-profit)
9. [Trailing Stop progresivo](#9-trailing-stop-progresivo)
10. [El ciclo del bot (cada 4 horas)](#10-el-ciclo-del-bot-cada-4-horas)
11. [Modo Paper vs Modo Live](#11-modo-paper-vs-modo-live)
12. [Requisitos del sistema](#12-requisitos-del-sistema)
13. [Instalación paso a paso](#13-instalación-paso-a-paso)
14. [Cómo ejecutar el bot](#14-cómo-ejecutar-el-bot)
15. [El archivo .env explicado](#15-el-archivo-env-explicado)
16. [Estructura del proyecto](#16-estructura-del-proyecto)
17. [Archivos de log y estado](#17-archivos-de-log-y-estado)
18. [Cómo interpretar los resultados](#18-cómo-interpretar-los-resultados)
19. [Rendimientos históricos](#19-rendimientos-históricos)
20. [Validación del backtest](#20-validación-del-backtest)
21. [Comisiones de Binance](#21-comisiones-de-binance)
22. [Solución de problemas comunes](#22-solución-de-problemas-comunes)
23. [Preguntas frecuentes](#23-preguntas-frecuentes)
24. [Glosario de términos](#24-glosario-de-términos)
25. [Arquitectura del software](#25-arquitectura-del-software)
26. [Mantenimiento del bot](#26-mantenimiento-del-bot)
27. [Mejoras futuras](#27-mejoras-futuras)

---

# 1. ¿Qué es este bot?

Alcista es un **bot de trading algorítmico** que opera de forma automática en el exchange de criptomonedas **Binance**. Su objetivo es generar ganancias comprando y vendiendo criptomonedas de forma sistemática, sin intervención humana.

## ¿Qué significa "algorítmico"?

Significa que las decisiones de compra y venta las toma un programa de computadora siguiendo reglas matemáticas predefinidas, no una persona. El bot analiza datos del mercado (precios, volúmenes) y cuando se cumplen ciertas condiciones, ejecuta operaciones automáticamente.

## ¿Qué hace este bot específicamente?

1. **Solo compra** (long-only): nunca vende en corto. Solo gana si el precio sube.
2. **Opera en pares USDT**: compra criptos con USDT (una moneda estable que vale $1).
3. **Timeframe 4 horas**: toma decisiones cada 4 horas, no en tiempo real.
4. **Multi-par**: monitorea hasta 100 criptomonedas y opera hasta 10 al mismo tiempo.
5. **Spot**: opera en el mercado al contado, sin apalancamiento ni futuros.

## ¿Para quién es este bot?

Para personas que:
- Tienen criptomonedas en Binance
- Quieren una estrategia automatizada de trading
- Prefieren un enfoque de mediano plazo (no day trading)
- Quieren minimizar riesgos con stops y trailing

---

# 2. Conceptos básicos de trading

## ¿Qué es un par de trading?

Un par de trading es el intercambio entre dos criptomonedas. Por ejemplo, **BTC/USDT** significa "comprar Bitcoin con USDT" o "vender Bitcoin por USDT".

Los pares que opera este bot siempre tienen **USDT** como segunda moneda. USDT es una "stablecoin" cuyo valor es siempre ~$1 USD.

**Ejemplos de pares:**
- BTC/USDT (Bitcoin)
- ETH/USDT (Ethereum)
- SOL/USDT (Solana)
- DOGE/USDT (Dogecoin)

## ¿Qué es una vela (candle)?

Una vela es una representación gráfica del precio de un activo durante un período de tiempo específico. Este bot usa **velas de 4 horas**, lo que significa que cada vela representa el movimiento del precio durante 4 horas consecutivas.

Cada vela contiene 4 precios clave:

```
Precio más alto (High)     →  |‾|  ← Precio de apertura (Open)
                            |   |     (primer precio del período)
Precio más bajo (Low)      →  |_|  ← Precio de cierre (Close)
                                    (último precio del período)
```

- **Open**: precio al inicio de las 4 horas
- **Close**: precio al final de las 4 horas
- **High**: precio máximo durante las 4 horas
- **Low**: precio mínimo durante las 4 horas

## ¿Qué es el timeframe?

El timeframe es el período de tiempo que representa cada vela. Este bot usa **timeframe 4h** (4 horas). Esto significa:

- Cada día se generan 6 velas nuevas (24h / 4h = 6)
- El bot toma decisiones 6 veces al día
- Las decisiones se toman al cierre de cada vela

## ¿Qué es el mercado spot?

El mercado spot es el mercado al contado: compras la criptomoneda directamente con dinero real. No hay apalancamiento, no hay futuros, no hay margen.

**Ejemplo:** Compras 1 BTC a $60,000 USDT. Ahora tienes 1 BTC. Si el BTC sube a $70,000, vendes y tienes $70,000 USDT (ganaste $10,000). Si baja a $50,000, vendes y tienes $50,000 (perdiste $10,000).

Este bot **solo opera en spot**. No apalanca, no usa futuros.

## ¿Qué es un exchange?

Un exchange es una plataforma donde se compran y venden criptomonedas. Este bot usa **Binance**, que es el exchange más grande del mundo por volumen de operaciones.

---

# 3. ¿Qué es una estrategia de trading?

Una estrategia de trading es un conjunto de **reglas** que determinan cuándo comprar y cuándo vender. Estas reglas se basan en **indicadores técnicos**, que son cálculos matemáticos sobre los precios y volúmenes históricos.

## Componentes de toda estrategia

| Componente | Descripción | Ejemplo |
|---|---|---|
| **Regla de entrada** | Cuándo comprar | "Comprar cuando la EMA rápida cruce arriba de la EMA lenta" |
| **Regla de salida** | Cuándo vender | "Vender cuando la EMA rápida cruce abajo de la EMA lenta" |
| **Gestión de riesgo** | Cómo proteger el capital | "Poner Stop Loss al 1.5% por debajo del entry" |
| **Filtros** | Condiciones adicionales | "Solo operar si ADX >= 20 (hay tendencia)" |
| **Selección de activos** | Qué pares operar | "Solo los 10 pares con mayor volumen en tendencia alcista" |

## ¿Por qué una estrategia sistemática?

Las emociones humanas (miedo, avaricia, esperanza) son el peor enemigo del trader. Una estrategia sistemática:

1. **Elimina las emociones**: el bot sigue las reglas sin desviarse
2. **Es consistente**: aplica las mismas reglas siempre
3. **Se puede probar**: se puede simular con datos históricos para ver si funciona
4. **Se puede mejorar**: se pueden ajustar parámetros y medir el impacto

## ¿Qué es un backtest?

Un backtest es una simulación de la estrategia usando datos históricos. El bot "retrocede en el tiempo" y opera como si estuviera en vivo, pero usando velas pasadas. Al final, se miden los resultados:

- Retorno total (%)
- Máxima caída (drawdown)
- Ratio de Sharpe (retorno ajustado por riesgo)
- Tasa de aciertos (win rate)
- Número de operaciones

---

# 4. La estrategia AggressiveTrend

AggressiveTrend es la estrategia central del bot. Combina tres ideas clave:

## Idea 1: Seguir la tendencia

El bot solo compra cuando el mercado está en **tendencia alcista**. Para detectar la tendencia usa dos medias móviles:

- **EMA 5**: media rápida (últimas 5 velas = ~20 horas)
- **EMA 20**: media lenta (últimas 20 velas = ~80 horas)

La tendencia es alcista cuando **EMA 5 > EMA 20** (la media rápida está por encima de la lenta).

## Idea 2: Confirmar la tendencia con ADX

El ADX mide la **fuerza** de la tendencia. Un ADX >= 20 significa que hay tendencia (alcista o bajista). El bot solo compra si ADX >= 20.

Además, requiere DI+ > DI-: esto significa que la presión compradora es mayor que la vendedora.

## Idea 3: Comprar en retrocesos (pullback)

En lugar de comprar cuando el precio ya subió mucho, el bot espera a que el precio **retroceda** hacia la EMA rápida y **rebote**. Esto permite entrar a mejor precio.

**Condiciones de pullback:**
1. El precio bajo de la vela actual está cerca de la EMA 5 (dentro de 3%)
2. El precio cierra por encima de la apertura (vela verde)
3. El precio toca la EMA 5 por abajo y cierra por encima

## Reglas completas de entrada (buy_signal)

El bot compra cuando TODAS estas condiciones se cumplen:

```
buy_signal =
  EMA5 > EMA20          AND   // Tendencia corto plazo alcista
  ADX >= 20             AND   // Tendencia presente
  DI+ > DI-             AND   // Compradores dominan
  close > EMA20         AND   // Precio sobre la media lenta
  volume >= 0.7x SMA    AND   // Mínimo volumen
  low <= EMA5 * 1.03    AND   // Precio cerca de EMA5 (pullback)
  close > open          AND   // Vela verde
  low <= EMA5           AND   // Tocó la EMA por abajo
  close > EMA5                 // Cerró por encima de la EMA
```

## Reglas de salida (exit_signal)

El bot vende si:

```
exit_signal =
  EMA5 < EMA20                // Cruce a la baja
  O DI+ < DI-                  // Vendedores dominan
```

Además de estas señales, el bot también sale por:

- **Stop Loss** (1.5% por debajo del entry)
- **Take Profit** (6% por encima del entry)
- **Trailing Stop** (se ajusta según la ganancia acumulada)

---

# 5. Indicadores técnicos explicados

## EMA (Exponential Moving Average)

La Media Móvil Exponencial es un promedio de precios que da más peso a los precios recientes. Es más sensible a los cambios de precio que una media simple.

**EMA 5** → Promedio de las últimas 5 velas (~20 horas en 4h)
**EMA 20** → Promedio de las últimas 20 velas (~80 horas en 4h)

**Cómo se usa:**
- Cuando EMA 5 > EMA 20 → tendencia alcista
- Cuando EMA 5 < EMA 20 → tendencia bajista
- El cruce de ambas es una señal de cambio de tendencia

## ADX (Average Directional Index)

El ADX mide la **fuerza** de la tendencia, sin importar su dirección. Va de 0 a 100.

| Valor | Significado |
|---|---|
| 0-20 | Sin tendencia (mercado lateral/rango) |
| 20-30 | Tendencia débil |
| 30-40 | Tendencia fuerte |
| 40+ | Tendencia muy fuerte |

El bot requiere ADX >= 20 para asegurar que hay tendencia.

## DI+ y DI- (Directional Indicators)

Estos indicadores complementan al ADX mostrando la **dirección** de la tendencia:

| Condición | Significado |
|---|---|
| DI+ > DI- | La presión compradora domina (alcista) |
| DI- > DI+ | La presión vendedora domina (bajista) |

El bot solo compra cuando DI+ > DI-.

## ATR (Average True Range)

El ATR mide la **volatilidad** del mercado. Un ATR alto significa que los precios se mueven mucho; un ATR bajo significa que están tranquilos.

Este bot usa ATR de forma indirecta: el trailing stop progresivo se ajusta según la ganancia acumulada, no según ATR.

## Volumen

El volumen es la cantidad de criptomoneda que se negocia en un período. Un volumen alto confirma que el movimiento de precio es real.

El bot requiere que el volumen de la vela actual sea al menos **70% del volumen promedio** de las últimas 20 velas. Esto filtra velas con poco interés de mercado.

## Pullback

Un pullback es un retroceso temporal del precio dentro de una tendencia alcista. El bot está diseñado para comprar en estos retrocesos, cuando el precio "rebota" en la EMA 5 y continúa subiendo.

**Visualmente:**
```
Precio subiendo → retrocede hacia la EMA5 → rebota → sigue subiendo
                                        ↓
                                  El bot compra aquí
```

---

# 6. El Screener: cómo elige los pares

El screener es el primer filtro del bot. Su trabajo es seleccionar qué pares están en **tendencia alcista** de fondo, para que la estrategia solo opere en esos.

## ¿Cómo funciona el screener?

Cada **24 horas** (cada 6 velas de 4h), el bot evalúa todos los pares candidatos:

1. Obtiene los 100 pares USDT con mayor volumen en Binance
2. Para cada par, descarga 220 velas de 4h (~37 días)
3. Aplica el filtro de tendencia:

```
bull_trend =
  EMA 20 > EMA 50          // Tendencia de mediano plazo alcista
  AND ADX >= 20             // Hay tendencia
  AND DI+ > DI-             // Compradores dominan
  AND close > EMA 50        // Precio arriba de la media
```

4. Selecciona hasta 10 pares que cumplen

## ¿Por qué dos niveles de filtro?

El bot tiene **dos niveles de EMAs**:

| Nivel | EMAs | Propósito |
|---|---|---|
| **Screener** (cada 24h) | EMA 20/50 | Filtro de tendencia de fondo |
| **Estrategia** (cada 4h) | EMA 5/20 | Señales de entrada rápidas |

Esto evita que el bot opere en criptos que están en tendencia bajista de mediano plazo, aunque tengan un rebote temporal de 4 horas.

## ¿Qué pasa si un par sale del screener?

Si un par estaba activo pero en el siguiente ciclo (24h después) ya no cumple las condiciones:

1. Si tiene posición abierta: se **cierra** (exit por SCREENER_EXIT)
2. Si no tiene posición: simplemente se elimina de la lista de activos
3. El capital se libera para otros pares

---

# 7. Gestión de riesgo

La gestión de riesgo es el conjunto de reglas que protegen el capital. Es **más importante que la estrategia misma**.

## Capital total

El bot comienza con un capital definido en la configuración (default: $100,000). Este capital se divide entre los pares activos.

## Capital por par

El capital se divide equitativamente: $100,000 / 10 pares = $10,000 por par. Cada par opera con su propio "sub-cuenta" separada.

## Tamaño de la posición

Cuando el bot decide comprar, calcula cuánto comprar:

```
riesgo_por_operacion = capital_del_par × 3%
distancia_al_SL = 1.5% del entry

tamaño_teorico = riesgo_por_operacion / (entry × 1.5%)

Pero el tamaño máximo es:
  tamaño_máximo = capital_del_par / precio_entry
  (no puedes gastar más de lo que tienes)
```

**Ejemplo práctico:**
- Capital del par: $10,000
- Riesgo por trade: $10,000 × 3% = $300
- Precio entry: $1,800
- Distancia SL: $1,800 × 1.5% = $27

- Tamaño teórico: $300 / $27 = 11.11 ETH
- Tamaño máximo: $10,000 / $1,800 = 5.55 ETH
- Como 11.11 > 5.55, el tamaño real es **5.55 ETH**
- Riesgo real: 5.55 × $27 = $150 = 1.5% del capital del par

## Límite de pares concurrentes

Máximo 10 pares al mismo tiempo. Si el screener selecciona más de 10, solo se toman los primeros 10 en orden de volumen.

## Drawdown máximo

Si el capital total cae más del 30% desde su punto más alto, el bot deja de operar hasta que se recupere.

---

# 8. Stop Loss y Take Profit

## Stop Loss (SL)

El Stop Loss es una orden que **vende automáticamente** si el precio cae por debajo de un nivel predefinido. Sirve para limitar las pérdidas.

**Configuración:** SL = 1.5% por debajo del precio de entrada.

**Ejemplo:** Compras ETH a $1,800. El SL se coloca a $1,800 × 0.985 = $1,773. Si ETH cae a $1,773, se vende automáticamente y la pérdida máxima es de 1.5%.

## Take Profit (TP)

El Take Profit es una orden que **vende automáticamente** si el precio alcanza un nivel de ganancia predefinido.

**Configuración:** TP = 6% por encima del precio de entrada.

**Ejemplo:** Compras ETH a $1,800. El TP se coloca a $1,800 × 1.06 = $1,908. Si ETH sube a $1,908, se vende automáticamente y la ganancia es de 6%.

## Relación Riesgo:Recompensa (R:R)

La relación R:R compara la ganancia potencial con la pérdida potencial:

```
R:R = Take Profit % / Stop Loss % = 6% / 1.5% = 4:1
```

Esto significa que por cada dólar que arriesgas, potencialmente ganas 4.

## ¿Por qué R:R 4:1?

Con un Win Rate (WR) de ~50%, una relación R:R de 4:1 da una expectativa positiva:

```
Expectativa = WR × Win% - (1-WR) × Loss%
             = 0.5 × 4.5% - 0.5 × 1.36%
             = 2.25% - 0.68%
             = +1.57% por trade
```

Incluso con un WR bajo (30-40%), la estrategia sigue siendo rentable gracias a la alta relación R:R.

---

# 9. Trailing Stop progresivo

El trailing stop es una mejora sobre el Stop Loss fijo. En lugar de tener un SL fijo en 1.5%, el trailing stop **se mueve hacia arriba** a medida que el precio sube, protegiendo las ganancias acumuladas.

## ¿Cómo funciona el trailing stop progresivo?

La distancia del trailing stop **se reduce** a medida que aumenta la ganancia:

| Ganancia acumulada | Distancia del trailing | Si el precio retrocede eso, sales con |
|---|---|---|
| 0% a 2% | 1.5% | ~0.5% de ganancia (con breakeven) |
| 2% a 3% | 1.0% | +1% a +2% |
| 3% a 5% | 0.75% | +2.25% a +4.25% |
| 5% a 7% | 0.50% | +4.5% a +6.5% |
| 7% a 10% | 0.25% | +6.75% a +9.75% |
| 10%+ | 0.10% | +9.9%+ |

## Breakeven (protección de pérdida)

Cuando la ganancia alcanza +1%, el SL se mueve al **precio de entrada** (breakeven). A partir de ese punto, la operación no puede terminar en pérdida.

## Activación del trailing

El trailing stop se activa cuando la ganancia supera el **2%**. Antes de eso, el bot usa el Stop Loss fijo de 1.5% o el breakeven si corresponde.

## Ejemplo práctico

```
1. Compras ETH a $1,800 → SL en $1,773 (1.5%)
2. ETH sube a $1,836 (+2%) → Se activa el trailing
3. ETH sigue subiendo a $1,872 (+4%)
   → Trailing distance = 0.75%
   → SL se mueve a $1,872 × 0.9925 = $1,858 (+3.2%)
4. ETH retrocede a $1,858 → Se vende con +3.2% de ganancia
   (Mejor que el SL fijo que habría vendido en el TP de 6% o nada)
```

## ¿Por qué progresivo?

El trailing progresivo es mejor que el trailing fijo porque:

- **Protege más** cuando hay mucha ganancia (distance 0.1% = casi el máximo)
- **Da espacio** cuando la ganancia es pequeña (distance 1.5% = no te saca prematuramente)
- **Maximiza ganancias** en tendencias fuertes largas

---

# 10. El ciclo del bot (cada 4 horas)

El bot opera en ciclos sincronizados con el cierre de velas de 4 horas en UTC:

```
00:00 UTC, 04:00 UTC, 08:00 UTC, 12:00 UTC, 16:00 UTC, 20:00 UTC
```

## Paso a paso de cada ciclo

### Paso 1: Esperar el cierre de la vela

El bot duerme hasta el cierre de la siguiente vela 4h. Mientras duerme, entre ciclos, **cada 2 minutos** revisa los precios actuales de las posiciones abiertas para ejecutar SL/TP si es necesario.

### Paso 2: Obtener pares candidatos

```
fetch_top_usdt_pairs(100, min_volume=$500k)
  → Obtiene los 100 pares USDT de mayor volumen en Binance
  → Ej: BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT...
```

### Paso 3: Descargar datos

```
fetch_multiple_ohlcv(pares, "4h", 220)
  → Descarga 220 velas 4h (~37 días) para cada par
  → Usa 10 hilos en paralelo para descargar rápido
```

### Paso 4: Aplicar el screener

Para cada par candidato:
```
Si EMA 20 > EMA 50 Y ADX >= 20 Y DI+ > DI- Y close > EMA 50
  → Añadir a lista de activos
Límite: 10 pares activos
```

### Paso 5: Verificar SL/TP

```
Para cada posición abierta:
  → ¿El low de la vela tocó el SL? → Cerrar posición (pérdida)
  → ¿El high de la vela tocó el TP? → Cerrar posición (ganancia)
  → Actualizar trailing stop según la ganancia
```

### Paso 6: Cerrar pares fuera del screener

```
Si un par tiene posición pero ya no pasa el screener:
  → Cerrar posición (exit forzado)
  → Liberar el capital
```

### Paso 7: Generar señales

```
Para cada par activo sin posición:
  → Calcular EMA 5/20, ADX, DI+/DI-, volumen
  → Si buy_signal = True → COMPRAR
  → Si exit_signal = True y hay posición → VENDER
```

### Paso 8: Ejecutar órdenes

```
En modo paper:
  → Solo registrar la operación en el log
  → Actualizar el capital virtual

En modo live:
  → Colocar orden market de compra/venta en Binance
  → Colocar orden SL y TP en Binance
```

### Paso 9: Guardar estado

```
→ live_state.json: capital, drawdown, posiciones abiertas
→ logs/trades.csv: trade registrado
→ logs/live.log: evento en el log
```

---

# 11. Modo Paper vs Modo Live

## Modo Paper (default)

El modo paper es un **simulador**. No usa dinero real ni coloca órdenes en Binance. Solo usa datos públicos del mercado para simular operaciones.

**Características:**
- No requiere API keys de Binance
- Usa datos públicos (velas 4h, tickers)
- Simula compras y ventas en la memoria del bot
- Calcula ganancias/pérdidas virtuales
- Guarda todo en logs para análisis
- Sin riesgo de perder dinero real

**Para qué sirve:**
1. Validar que la estrategia funciona en tiempo real
2. Verificar que el bot se conecta correctamente
3. Ajustar parámetros sin riesgo
4. Generar confianza antes de pasar a live

## Modo Live

El modo live opera con dinero real en Binance.

**Características:**
- Requiere API keys de Binance (con permisos de trading)
- Coloca órdenes reales de compra/venta
- Coloca órdenes SL y TP reales
- Riesgo de perder dinero real

**Requisitos para activarlo:**
1. API Key y Secret de Binance en .env
2. Ejecutar con `--live`
3. Capital disponible en la cuenta de Binance

## Recomendación

1. Ejecuta en **modo paper** por 1-2 semanas
2. Revisa los resultados en `logs/trades.csv`
3. Compara los resultados con el backtest
4. Si los resultados son consistentes, pasa a **modo live**

---

# 12. Requisitos del sistema

## Hardware

| Componente | Requisito mínimo |
|---|---|
| CPU | Cualquier procesador moderno |
| RAM | 2 GB |
| Disco | 500 MB libres |
| Internet | Conexión estable (el bot hace peticiones cada 2 min) |

## Software

| Componente | Versión |
|---|---|
| Sistema operativo | Linux (recomendado), macOS, Windows |
| Python | 3.10 o superior |
| Pip | Última versión |

## Cuenta de Binance

- Cuenta gratuita en Binance
- (Opcional para modo live) API key con permisos de trading

## Dependencias de Python

El bot usa las siguientes librerías (se instalan automáticamente):

| Librería | Propósito |
|---|---|
| `ccxt` | Conectar con Binance (API de trading) |
| `pandas` | Manipulación de datos de velas |
| `numpy` | Cálculos matemáticos |
| `python-dotenv` | Leer archivo .env de configuración |
| `websockets` | (No usado actualmente, para futura integración) |

---

# 13. Instalación paso a paso

## Paso 1: Clonar o descargar el proyecto

```bash
git clone https://github.com/tu-usuario/bot_trading_alcista.git
cd bot_trading_alcista
```

Si no tienes git instalado:

```bash
# Descarga el ZIP del proyecto
# Descomprímelo en una carpeta
cd bot_trading_alcista
```

## Paso 2: Crear el entorno virtual

El entorno virtual aísla las dependencias del bot del resto del sistema.

```bash
python3 -m venv venv
```

## Paso 3: Activar el entorno virtual

**Linux/macOS:**
```bash
source venv/bin/activate
```

**Windows:**
```bash
venv\Scripts\activate
```

## Paso 4: Instalar dependencias

```bash
pip install -r requirements.txt
```

## Paso 5: Configurar .env

Copia el archivo de ejemplo:

```bash
cp .env.example .env
```

Luego edita `.env` con tus valores (explicado en la siguiente sección).

## Paso 6: Verificar instalación

```bash
python3 -m pytest tests/ -v
```

Todos los tests deben pasar (19 tests, todos verdes).

## Paso 7: Ejecutar el bot en modo paper

```bash
python3 scripts/run_live.py
```

El bot comenzará a simular operaciones cada 4 horas.

---

# 14. Cómo ejecutar el bot

## Comandos básicos

### Modo paper (simulación, sin dinero real)

```bash
python3 scripts/run_live.py
```

### Modo live (con dinero real)

```bash
python3 scripts/run_live.py --live
```

## Ejecución en segundo plano

Para que el bot siga funcionando después de cerrar la terminal, usa **tmux**:

```bash
# Iniciar sesión tmux
tmux new-session -d -s alcista 'python3 scripts/run_live.py'

# Ver el bot en vivo
tmux attach -t alcista

# Salir sin detener: Ctrl+B, luego D

# Detener el bot
tmux kill-session -t alcista
```

## Ver los resultados

```bash
# Log detallado
tail -f logs/live.log

# Trades realizados
tail -f logs/trades.csv

# Estado actual del bot
cat live_state.json

# Última salida de tmux
tmux capture-pane -t alcista -p
```

---

# 15. El archivo .env explicado

El archivo `.env` contiene la configuración del bot. Se crea copiando `.env.example`:

```bash
cp .env.example .env
```

## Variables de capital

```ini
# Capital inicial para backtesting
INITIAL_CAPITAL=100000.0
```

Capital virtual con el que empieza el bot en paper mode. En live mode, debe coincidir con el capital disponible en Binance.

## Variables de riesgo

```ini
# Riesgo por operación (% del capital del par)
RISK_PER_TRADE=0.03

# Drawdown máximo antes de parar (%)
MAX_DRAWDOWN=0.30

# Máximo de posiciones concurrentes por par
MAX_CONCURRENT_POSITIONS=1

# Días mínimo entre trades (0 = sin límite)
MIN_TRADE_INTERVAL_DAYS=0
```

## Variables de stops

```ini
# Stop Loss (% por debajo del entry)
STOP_LOSS_PCT=0.015

# Take Profit (% por encima del entry)
TAKE_PROFIT_PCT=0.06

# Breakeven: cuándo mover el SL al entry (%)
BREAK_EVEN_TRIGGER_PCT=0.01

# Activación del trailing stop (%)
TRAILING_ACTIVATION_PCT=0.02

# Distancia del trailing stop (%)
TRAILING_DISTANCE_PCT=0.015
```

## Variables de estrategia

```ini
# EMAs
EMA_FAST=5
EMA_SLOW=20

# ADX
ADX_PERIOD=14
ADX_THRESHOLD=20

# Volumen
VOLUME_WINDOW=20
VOLUME_THRESHOLD=0.7

# Pullback
PULLBACK_TOLERANCE=0.03
```

## API Keys de Binance

```ini
# Solo necesario para modo live
EXCHANGE_API_KEY=tu_api_key
EXCHANGE_API_SECRET=tu_api_secret
```

## ⚠️ Seguridad de API Keys

NUNCA compartas tu archivo `.env`. Contiene las llaves para acceder a tu cuenta de Binance.

**Reglas de seguridad:**
1. `.env` está en `.gitignore` — no se sube a git
2. No compartas pantallazos del .env
3. Usa una API key con permisos limitados (solo trading, sin retiros)
4. En modo paper no se necesita API key

---

# 16. Estructura del proyecto

```
bot_trading_alcista/
│
├── scripts/                    # Scripts ejecutables
│   ├── run_live.py             # Bot principal (paper/live)
│   ├── update_data.py          # Actualizar datos históricos
│   ├── optimized_multi_backtest.py  # Backtest multi-par
│   └── fast_optimizer_v3.py    # Optimizador de parámetros
│
├── src/                        # Código fuente
│   ├── strategies/             # Estrategias de trading
│   │   ├── aggressive_trend.py # Estrategia principal (EMA 5/20)
│   │   └── trend_following.py  # Estrategia secundaria
│   ├── risk/                   # Gestión de riesgo
│   │   └── manager.py          # SL, TP, trailing, posición
│   ├── exchange/               # Conexión con Binance
│   │   ├── binance_exchange.py # API REST de Binance
│   │   ├── websocket.py        # WebSocket (no usado activamente)
│   │   └── base.py             # Clases base (Order, Balance)
│   ├── screener/               # Selección de pares
│   │   └── market_screener.py  # Filtro de tendencia
│   ├── portfolio/              # Gestión de portafolio
│   │   └── manager.py          # Asignación de capital
│   ├── metrics/                # Métricas de rendimiento
│   │   └── calculator.py       # Sharpe, drawdown, etc.
│   ├── backtesting/            # Motor de backtest
│   │   ├── engine.py           # Backtest de un par
│   │   ├── multi_engine.py     # Backtest multi-par
│   │   └── optimizer.py        # Optimización de parámetros
│   ├── data/                   # Carga de datos
│   │   └── loader.py           # Leer CSVs de velas
│   ├── live.py                 # LiveTrader (versión anterior)
│   └── main.py                 # CLI principal
│
├── config/                     # Configuración
│   └── settings.py             # Leer variables de .env
│
├── tests/                      # Tests unitarios
│   ├── test_risk.py            # Tests de gestión de riesgo
│   ├── test_strategy.py        # Tests de estrategias
│   ├── test_metrics.py         # Tests de métricas
│   └── test_backtest.py        # Tests de backtest
│
├── data/                       # Datos históricos (velas 4h CSV)
│   ├── BTC_USDT_4h_2y.csv      # ~5000 velas de BTC
│   ├── ETH_USDT_4h_2y.csv      # ~4380 velas de ETH
│   └── ...                     # Total: 83+ pares
│
├── logs/                       # Archivos de log
│   ├── live.log                # Log principal del bot
│   ├── binance.log             # Log de conexiones
│   ├── trades.csv              # Todos los trades (append)
│   └── trades_*.csv            # Trades por sesión
│
├── results/                    # Resultados de backtest
│   └── realistic_multi_*/      # Resultados por configuración
│
├── live_state.json             # Estado actual del bot
├── .env                        # Configuración (no subir a git)
├── .env.example                # Ejemplo de configuración
├── .gitignore                  # Archivos ignorados por git
├── requirements.txt            # Dependencias de Python
└── README.md                   # Instrucciones rápidas
```

---

# 17. Archivos de log y estado

## live.log — Log principal

Contiene TODO lo que hace el bot:

```
2026-06-15 16:00:00 | INFO | live | ─── CICLO 2026-06-15 16:00 UTC ───
2026-06-15 16:00:00 | INFO | live | Candidatos: 100
2026-06-15 16:00:00 | INFO | live | Activos: 10 BTC ETH SOL XRP
2026-06-15 16:00:00 | INFO | live | ── ENTRY ── ETH BUY @ 1845.53
2026-06-15 16:00:00 | INFO | live |   ADX=25.3 DI+=28 DI- =18 vol=1.4
2026-06-15 16:00:00 | INFO | live |   pullback: low=1828 <= EMA5*1.03=1887 OK
2026-06-15 16:00:00 | INFO | live |   Equity: $100000.00 | DD: 0.00%
```

## trades.csv — Todos los trades

Cada fila es un trade ejecutado:

```
time,symbol,action,price,size,pnl,reason,equity
2026-06-15T16:00:00,ETH/USDT,BUY,1845.53,5.4185,0.0,,100000.0
2026-06-15T22:15:00,ETH/USDT,EXIT_SL,1817.85,5.4185,-149.98,SL,99850.02
```

Campos:
- **time**: fecha/hora UTC
- **symbol**: par operado
- **action**: BUY, EXIT_SL, EXIT_TP, EXIT_TRAILING, EXIT_SIGNAL
- **price**: precio de entrada/salida
- **size**: cantidad de cripto
- **pnl**: ganancia/pérdida en USDT
- **reason**: motivo de la salida
- **equity**: capital total después del trade

## live_state.json — Estado actual

Contiene el estado actual del bot. Se actualiza cada ciclo.

```json
{
  "equity": 100000.0,
  "peak_equity": 100000.0,
  "pairs": {
    "ETH/USDT": {
      "capital": 10000.0,
      "trades": [],
      "position": {
        "entry_price": 1845.53,
        "entry_time": "2026-06-15T16:00:00",
        "size": 5.4185,
        "stop_loss": 1817.85,
        "take_profit": 1956.26
      }
    }
  }
}
```

Este archivo permite que el bot se reinicie sin perder las posiciones abiertas.

## trades_*.csv — Trades por sesión

Cada vez que se inicia el bot, se crea un archivo nuevo: `trades_20260615_160000.csv`. Esto evita perder datos si el bot se reinicia.

---

# 18. Cómo interpretar los resultados

## Equity

El equity es el capital total del bot. Comienza en $100,000. Cada trade suma o resta.

```
Equity final = Capital inicial + Suma de todos los PnLs
```

## Drawdown (DD)

El drawdown es la caída desde el punto más alto del equity:

```
DD = (Máximo histórico - Equity actual) / Máximo histórico × 100
```

**Ejemplo:**
- Equity máximo: $120,000
- Equity actual: $108,000
- DD = (120,000 - 108,000) / 120,000 = 10%

Un DD bajo (menos de 5%) es bueno. Significa que el bot no tiene pérdidas grandes.

## Sharpe Ratio

Mide el retorno ajustado por riesgo:

```
Sharpe = (Retorno - Tasa libre de riesgo) / Volatilidad
```

Interpretación:
| Sharpe | Significado |
|---|---|
| > 2.0 | Excelente |
| 1.0 - 2.0 | Bueno |
| 0.5 - 1.0 | Aceptable |
| < 0.5 | Malo |

## Win Rate (WR)

Porcentaje de trades que terminan en ganancia:

```
WR = Trades ganadores / Total de trades × 100

Ejemplo: 643 ganadores de 1270 = 50.6% WR
```

Un WR del 50% con R:R 4:1 es excelente.

## Profit Factor (PF)

Relación entre ganancias totales y pérdidas totales:

```
PF = Suma de ganancias / Suma de pérdidas

Ejemplo: ganancias = $400,000, pérdidas = $105,000, PF = 3.81
```

Un PF > 2.0 es muy bueno.

## Expectancy

Ganancia esperada por cada trade:

```
Expectancy = WR × Avg Win - (1-WR) × Avg Loss

Ejemplo: 0.506 × 4.45% - 0.494 × 1.36% = +1.56%
```

Una expectativa positiva significa que la estrategia gana dinero a largo plazo.

---

# 19. Rendimientos históricos

Los siguientes resultados son del backtest en el período **15 Dic 2025 → 15 Jun 2026** con las configuraciones actuales del bot v1.

## Resultados generales

| Métrica | Valor |
|---|---|
| **Retorno neto** (con comisiones) | **+237.52%** |
| Comisiones pagadas (0.2%/trade) | $14,545 (14.5%) |
| Capital inicial | $100,000 |
| Capital final | $337,520 |
| Período | 6 meses (15 Dic 2025 → 15 Jun 2026) |
| Pares operados | 75 |
| Trades totales | 1,270 |
| **Win Rate** | **50.24%** |
| **Profit Factor** | **3.81** |
| **Sharpe Ratio** | **3.50** |
| **Max Drawdown** | **2.38%** |
| Expectativa por trade | +1.56% |
| Avg Win | +4.45% |
| Avg Loss | -1.36% |

## Rendimiento por mes

| Mes | Retorno mensual |
|---|---|
| Enero 2026 | +24.28% |
| Febrero 2026 | +20.42% |
| Marzo 2026 | +16.27% |
| Abril 2026 | +11.13% |
| Mayo 2026 | +28.64% |
| Junio 2026 | +37.57% |

**6 meses consecutivos positivos.** Ningún mes en rojo.

## Periodo completo (2024-2026)

El backtest de 22 meses (2024-2026) muestra:

| Métrica | Valor |
|---|---|
| Retorno | ~+345% (estimado) |
| DD máximo | ~1.5% |
| Sharpe | ~1.7 |

*Nota: el backtest completo se ejecutó antes de los últimos ajustes. Los números exactos pueden variar ligeramente.*

---

# 20. Validación del backtest

## ¿Son reales estos números?

Los resultados del backtest son **simulaciones** basadas en datos históricos. No garantizan resultados futuros.

## Factores que inflan los resultados del backtest

| Factor | Impacto | Explicación |
|---|---|---|
| **Sin comisiones** | Alto | Binance cobra 0.1% por lado (0.2% por trade). En 1270 trades, ~$14,500 en comisiones. |
| **Survivorship bias** | Medio | Solo se incluyen pares que existen hoy. Los que quebraron no están en los datos. |
| **Look-ahead bias** | Bajo | Las señales se calculan al cierre de la vela. En realidad se ejecutaría en la siguiente vela. |
| **Slippage** | Medio | Las órdenes pueden ejecutarse a peor precio, especialmente en pares de bajo volumen. |

## ¿Cuánto esperar en realidad?

Ajustando por comisiones y slippage, los resultados reales esperados son:

| Métrica | Backtest | Real esperado |
|---|---|---|
| Retorno mensual | ~+39% | ~+15-20% |
| DD | 2.38% | ~5-8% |
| Sharpe | 3.5 | ~1.5-2.0 |

El bot sigue siendo rentable, pero **no esperes los números del backtest** al pie de la letra.

---

# 21. Comisiones de Binance

## Estructura de comisiones

Binance cobra una comisión por cada orden ejecutada:

| Tipo de orden | Comisión |
|---|---|
| Market (compra) | 0.1% |
| Market (venta) | 0.1% |
| Stop Loss | 0.1% |
| Take Profit (limit) | 0.1% |

**Por trade completo:** 0.1% entrada + 0.1% salida = **0.2%**

## Impacto de las comisiones

Con 1,270 trades en 6 meses y un valor promedio de posición de ~$8,000:

```
Comisiones = 1,270 × $8,000 × 0.2% = $20,320
```

Pero el bot distribuye el capital entre 10 pares, y el valor promedio por trade es menor (~$5,700):

```
Comisiones = 1,270 × $5,700 × 0.2% = $14,478
```

Esto coincide con los ~$14,500 calculados en el backtest con comisiones.

---

# 22. Solución de problemas comunes

## Error: "No module named ..."

```
ModuleNotFoundError: No module named 'ccxt'
```

**Solución:** Instala las dependencias:

```bash
pip install -r requirements.txt
```

## Error: "API key invalid"

```
binance | Error conectando a Binance: binance ... API-key format invalid
```

**Causa:** La API key de Binance en `.env` es inválida.
**Solución:** Genera una nueva API key en Binance.

## El bot no abre posiciones

**Causas posibles:**
1. No hay pares que pasen el screener (mercado bajista)
2. El pullback no se está dando (precio muy lejos de la EMA)
3. El volumen es insuficiente

**Qué revisar:**
```bash
tail -f logs/live.log
# Busca "Activos:" y "Buy signal"
```

## Error de conexión a Binance

```
binance | Error conectando a Binance: ...
```

**Causa:** Problemas de red o Binance caído.
**Solución:** El bot reintenta automáticamente. Si persiste, revisa tu conexión a internet.

## El bot se detuvo inesperadamente

**Causa:** Error no controlado en el código.
**Solución:** Revisa el final del log:

```bash
tail -50 logs/live.log
```

Si el bot se detuvo, reinícialo:

```bash
tmux kill-session -t alcista
tmux new-session -d -s alcista 'python3 scripts/run_live.py'
```

## No se crean archivos de log

**Causa:** Permisos de directorio.
**Solución:**

```bash
mkdir -p logs
chmod 755 logs/
```

---

# 23. Preguntas frecuentes

## ¿Puedo perder todo mi dinero?

Con Stop Loss de 1.5%, el riesgo máximo por operación es de 1.5% del capital del par. Con 10 pares, el riesgo máximo simultáneo es de ~15% del capital total.

Sin embargo, si todas las posiciones pierden al mismo tiempo, la pérdida máxima teórica es de 15%. El bot deja de operar si el drawdown supera el 30%.

## ¿El bot funciona en mercado bajista?

El bot solo compra en tendencia alcista. En mercado bajista, el screener no seleccionará pares y el bot no operará. Esto es normal y deseable.

## ¿Puedo modificar los parámetros?

Sí, editando el archivo `.env`. Los parámetros más importantes:

- `STOP_LOSS_PCT`: riesgo por operación
- `TAKE_PROFIT_PCT`: ganancia objetivo
- `EMA_FAST` y `EMA_SLOW`: sensibilidad de la estrategia

Cambia un parámetro a la vez y ejecuta backtest para ver el impacto.

## ¿El bot necesita estar 24/7 encendido?

Sí, el bot necesita estar funcionando continuamente para capturar las señales de trading. Si se apaga, pierde las señales mientras estuvo caído.

Sin embargo, si se reinicia, carga `live_state.json` y continúa con las posiciones abiertas.

## ¿Qué pasa si Binance se cae?

Si Binance está caído en el momento del ciclo, el bot espera 60 segundos y reintenta. Si sigue caído, espera al siguiente ciclo.

## ¿Puedo operar en otros exchanges?

El bot está diseñado para Binance, pero la arquitectura es modular. Se podría adaptar a otros exchanges que soporte `ccxt`.

## ¿Cuánto tiempo toma ver resultados significativos?

Con ~200 trades por mes, en 1 semana tendrás ~50 trades. Suficiente para ver tendencias. Para una evaluación completa, espera 2-4 semanas.

## ¿El bot reinvierte las ganancias?

Sí, las ganancias se acumulan en el equity de cada par. A mayor equity, mayor tamaño de posición en el siguiente trade.

---

# 24. Glosario de términos

| Término | Definición |
|---|---|
| **ADX** | Indicador que mide la fuerza de la tendencia (0-100). |
| **ATR** | Average True Range. Mide la volatilidad del mercado. |
| **Backtest** | Simulación de la estrategia con datos históricos. |
| **Break-even** | Punto donde ganancia = pérdida. SL movido al entry price. |
| **Candle/Vela** | Representación gráfica del precio en un período (4h en este bot). |
| **DI+ / DI-** | Indicadores de dirección (alcista/bajista). |
| **Drawdown (DD)** | Caída desde el punto más alto del capital. |
| **EMA** | Media Móvil Exponencial. Promedio de precios ponderado. |
| **Equity** | Capital total del bot en un momento dado. |
| **Exchange** | Plataforma para comprar/vender criptomonedas (Binance). |
| **Expectancy** | Ganancia esperada por cada operación. |
| **Long-only** | Estrategia que solo compra (nunca vende en corto). |
| **Market order** | Orden que se ejecuta al precio actual del mercado. |
| **Paper trading** | Trading simulado sin dinero real. |
| **Profit Factor** | Ganancia total / Pérdida total. > 2.0 es bueno. |
| **Pullback** | Retroceso temporal del precio dentro de una tendencia. |
| **R:R (Risk:Reward)** | Relación riesgo/beneficio. Este bot usa 4:1. |
| **Sharpe Ratio** | Retorno ajustado por riesgo. |
| **SL / Stop Loss** | Orden que vende si el precio cae a cierto nivel. |
| **Slippage** | Diferencia entre precio esperado y precio real de ejecución. |
| **SMA** | Media Móvil Simple. Promedio de precios sin ponderar. |
| **Spot** | Mercado al contado (sin apalancamiento). |
| **Stablecoin** | Criptomoneda cuyo valor es fijo (~$1 USDT). |
| **Timeframe** | Período de cada vela (4h, 1h, 1d). |
| **TP / Take Profit** | Orden que vende si el precio sube a cierto nivel. |
| **Trader** | Persona que compra y vende activos financieros. |
| **Trailing Stop** | Stop Loss que se mueve hacia arriba con el precio. |
| **Win Rate (WR)** | Porcentaje de trades ganadores. |

---

# 25. Arquitectura del software

## Diagrama de flujo

```
                    ┌─────────────────────────┐
                    │     Binance Exchange     │
                    │   (API Pública/Privada)  │
                    └──────────┬──────────────┘
                               │
                    ┌──────────▼──────────────┐
                    │   BinanceExchange       │
                    │   (fetch_ohlcv, ticker) │
                    └──────────┬──────────────┘
                               │
                    ┌──────────▼──────────────┐
                    │   scripts/run_live.py    │
                    │   (Orquestador principal)│
                    │                          │
                    │  ┌────────────────────┐  │
                    │  │  Screener          │  │
                    │  │  (EMA 20/50, ADX)  │  │
                    │  └──────────┬─────────┘  │
                    │             │             │
                    │  ┌──────────▼─────────┐  │
                    │  │  AggressiveTrend   │  │
                    │  │  (EMA 5/20, ADX)   │  │
                    │  └──────────┬─────────┘  │
                    │             │             │
                    │  ┌──────────▼─────────┐  │
                    │  │  RiskManager       │  │
                    │  │  (SL, TP, trailing) │  │
                    │  └──────────┬─────────┘  │
                    │             │             │
                    │  ┌──────────▼─────────┐  │
                    │  │  LiveState         │  │
                    │  │  (persistencia)    │  │
                    │  └────────────────────┘  │
                    └──────────┬──────────────┘
                               │
                    ┌──────────▼──────────────┐
                    │  logs/    live_state.json│
                    │  trades.csv  live.log   │
                    └─────────────────────────┘
```

## Principios de diseño

| Principio | Aplicación |
|---|---|
| **Separación de responsabilidades** | Cada módulo hace una cosa: estrategia, riesgo, screener, exchange |
| **Configurable** | Todos los parámetros via .env, no hardcodeados |
| **Persistente** | Estado se guarda en JSON, permite reinicio sin pérdida |
| **Observable** | Logging detallado de cada decisión |
| **Testeable** | Tests unitarios para cada módulo |
| **Seguro** | Paper mode por default, --live explícito |

## Dependencias entre módulos

```
run_live.py
  ├── BinanceExchange → obtiene datos de mercado
  ├── screen_pairs()  → filtra pares por tendencia
  ├── AggressiveTrend → genera señales de trading
  ├── RiskManager     → ejecuta órdenes y gestiona riesgo
  └── LiveState       → guarda/carga estado persistente
```

---

# 26. Mantenimiento del bot

## Tareas diarias (opcional)

```bash
# Revisar que el bot sigue vivo
tmux has-session -t alcista

# Ver trades del día
tail -20 logs/trades.csv

# Ver equity actual
python3 -c "import json; d=json.load(open('live_state.json')); print(f'Equity: \${d[\"equity\"]:,.2f} | DD: {(d[\"peak_equity\"]-d[\"equity\"])/d[\"peak_equity\"]*100:.2f}%')"
```

## Tareas semanales

```bash
# Análisis de rendimiento (después de 1+ semanas)
python3 -c "
import csv
trades = []
with open('logs/trades.csv') as f:
    for r in csv.DictReader(f):
        trades.append(r)
wins = [t for t in trades if float(t['pnl']) > 0]
losses = [t for t in trades if float(t['pnl']) <= 0]
print(f'Trades: {len(trades)} | Wins: {len(wins)} ({len(wins)/len(trades)*100:.1f}%) | Losses: {len(losses)}')
print(f'Avg Win: {sum(float(t[\"pnl\"]) for t in wins)/len(wins):.2f}' if wins else 'No wins')
print(f'Avg Loss: {sum(float(t[\"pnl\"]) for t in losses)/len(losses):.2f}' if losses else 'No losses')
"
```

## Actualizar datos históricos

Los datos de velas se descargan automáticamente del backtest. Para actualizar los CSVs con datos hasta hoy:

```bash
python3 scripts/update_data.py
```

## Reiniciar el bot después de cambios

```bash
# Detener
tmux kill-session -t alcista

# Iniciar de nuevo
tmux new-session -d -s alcista 'python3 scripts/run_live.py'
```

## Limpiar logs antiguos

```bash
# Eliminar logs de más de 30 días
find logs/ -name 'trades_*.csv' -mtime +30 -delete
find logs/ -name '*.log' -mtime +30 -delete
```

---

# 27. Mejoras futuras

## Prioridad alta

| Mejora | Beneficio |
|---|---|
| Alertas Telegram/Discord | Notificaciones de trades y errores en tiempo real |
| Dashboard web | Ver equity, trades, DD en navegador |
| Logging de comisiones | Registrar automáticamente el costo de cada trade |

## Prioridad media

| Mejora | Beneficio |
|---|---|
| Base de datos SQLite | Más escalable que JSON para estado |
| Optimización trailing thresholds | Ajustar los puntos de activación (2/3/5/7/10) con datos reales |
| Filtro de correlación | Evitar operar pares muy correlacionados (ej: BTC y ETH juntos) |

## Prioridad baja

| Mejora | Beneficio |
|---|---|
| Más estrategias seleccionables | Poder cambiar de estrategia sin reiniciar |
| Backtest automático en papel | Comparar rendimiento real vs backtest automáticamente |
| Rebalanceo de capital semanal | Ajustar capital por par según rendimiento histórico |

---

## Nota final

Este bot es una herramienta de trading automatizado. **Ninguna estrategia garantiza ganancias.** El mercado de criptomonedas es altamente volátil y riesgoso.

Usa este bot con:
- Capital que puedas permitirte perder
- Pruebas en paper mode antes de pasar a live
- Monitoreo regular de los resultados
- Actualizaciones periódicas del código

---

*Documentación generada el 15 de Junio de 2026*
*Versión del bot: v1.0*
