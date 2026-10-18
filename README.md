# 🤖 Quantitative Grid Trading Bot (v13 - Institutional Edition)
### Motor Cuantitativo Algorítmico Autónomo de Mallas Spot, Interés Compuesto Estricto y Adaptador para Pionex

---

## 📌 Visión y Filosofía Real del Proyecto

Este proyecto es un **sistema de trading cuantitativo determinista y matemático** diseñado para operar en mercados Spot de criptomonedas (adaptable a **Pionex** y **Binance**). 

A diferencia de modelos que dependen de llamadas lentas o impredecibles a modelos de lenguaje (LLMs) durante el tick de mercado, este motor ejecuta **lógica algorítmica pura, cuantitativa y de baja latencia** basada en microestructura de mercado, profundidad de libro de órdenes (LOB), régimen macro de volatilidad y geometría adaptativa de rejilla.

---

## ⚡ Principios Cuantitativos y Pilares Operativos

### 1. 🔁 Interés Compuesto Estricto (Cada Centavo se Reinvierten)
* **Reinversión Inmediata de Ganancias**: Cada micro-ganancia obtenida al cerrar un ciclo o escalón de venta se suma de inmediato a `bot.cash` (efectivo líquido disponible).
* **Dimensionamiento Dinámico**: Las nuevas órdenes y mallas calculan su tamaño sobre el capital actualizado en tiempo real. Si la cuenta gana $0.15 USDT en una rotación, esos $0.15 USDT quedan instantáneamente disponibles para financiar los siguientes escalones de compra.

### 2. 🛡️ Escalabilidad de Concurrencia por Capital (Slots Dinámicos)
Para proteger micro-cuentas y evitar la fragmentación destructiva del margen, la cantidad de mallas concurrentes se escala automáticamente según el equity total:

| Equity de la Cuenta (USDT) | Máximo de Mallas Simultáneas | Enfoque Estratégico |
|---|:---:|---|
| **$80.00 – $125.00** | **1 Malla Activa** | Concentración total de liquidez en el candidato #1 del radar. |
| **$125.00 – $250.00** | **2 Mallas Activas** | Diversificación inicial en 2 activos con baja correlación. |
| **$250.00 – $375.00** | **3 Mallas Activas** | Rotación fluida entre líderes de volatilidad. |
| **$375.00 – $550.00** | **4 Mallas Activas** | Cobertura amplia de canales laterales. |
| **> $550.00** | **Hasta 6 Mallas** | Escalamiento compuesto institucional. |

---

### 3. 🎯 Arquitectura de Malla Viva (Paso Dinámico & Trailing)

```
                       ┌──────────────────────────────────────────────┐
                       │           ESTRUCTURA DE MALLA VIVA           │
                       └──────────────────────────────────────────────┘
                                              │
                      ┌───────────────────────┴───────────────────────┐
                      ▼                                               ▼
         ┌─────────────────────────┐                     ┌─────────────────────────┐
         │  1. PASO DINÁMICO (ATR) │                     │   2. TRAILING GRID      │
         │   Calibra el GROSOR     │                     │  Desplaza el RANGO      │
         │   de los escalones      │                     │  persiguiendo tendencia │
         └─────────────────────────┘                     └─────────────────────────┘
```

#### A. Paso Dinámico por ATR (Adaptive Spacing)
* **Distancia Adaptativa:** La separación entre escalones se calcula en tiempo real usando el True Range promedio ($\text{ATR}_{15m}$).
* **Piso Anticomisiones:** Paso mínimo fijado en **0.42%**. Evita el "fee drag" letal donde las comisiones del exchange canibalicen las ganancias netas.
* **Techo de Inactividad:** Paso máximo acotado (1.20%) para asegurar frecuencia de fills y flujo constante de caja.

#### B. Trailing Grid Inteligente (Movimiento de Rango)
* **Trailing Up (Tendencia Alcista):** Si el precio rompe el techo de la malla, cancela la orden de compra más baja (capital ocioso en el fondo) y desplaza el escalón hacia arriba para continuar capturando la subida sin quedarse fuera.
* **Trailing Down Condicional (Pullback Ladder con Re-evaluación):**
  * Si el precio cae por debajo del piso, el supervisor somete el activo a un **filtro estricto de pureza y convicción**.
  * **Si el Score $\ge 65$ y el macro acompaña:** Desplaza la malla 1 escalón hacia abajo para pescar el rebote en el siguiente nivel de liquidez institucional.
  * **Si el activo pierde momentum o falla la evaluación:** Se prohíbe promediar a la baja. El bot busca una salida en breakeven (cero pérdida) o activa los Circuit Breakers para cortar el riesgo inmediatamente.

---

### 4. 🧯 Circuit Breakers y Supervisión de Anomalías

Para evitar quedar atrapado en activos en caída libre ("bagholding"), el supervisor vigila el estado de anomalía con reglas implacables:

* **Stop Catastrófico (-3.50% bajo el piso):** Si el precio perfora más de 3.50% por debajo del rango de la malla, se ejecuta una liquidación inmediata a mercado para proteger el capital núcleo.
* **Time-Stop (Ventana Máxima de 4 Horas):** Si el activo cae por debajo del piso y tras 4 horas completas no logra rebotar al punto de equilibrio (Breakeven), el bot ejecuta `close_grid_market()` con slippage simulado (0.08%) y comisión taker, liberando el capital para rotar a activos líderes con rendimiento positivo comprobado.
* **Diagnóstico Clínico en Vivo:** Telemetría en el Dashboard que monitorea:
  * Tiempo exacto en anomalía (`time_in_anomaly`).
  * Desviación porcentual respecto al piso (`deviation_floor_pct`).
  * Distancia porcentual requerida para salida en breakeven (`dist_to_be_pct`).
  * Veredicto clínico en tiempo real (Saludable, Alerta Amarilla, Peligro Inminente).

---

### 5. 🔬 Microestructura y Simulación Realista de Ejecución (LOB)

Para evitar sesgos de "papel irreal" (*overfitting*), la ejecución simula las condiciones del libro de órdenes (*Limit Order Book*):
* **Queue Penetration Buffer (0.03%):** Las órdenes límite no se ejecutan con solo tocar el precio; requieren que el tick perfore 0.03% más allá del nivel para simular el consumo real de la cola del libro.
* **Intermediate Wicks (`get_tick_price_range`):** Detección de mechas reales mediante `fetch_trades` entre ticks, capturando mínimos y máximos intra-segundo.
* **Slippage y Taker Drag:** Las salidas de emergencia a mercado aplican 0.08% de deslizamiento y tarifa taker (1.5x fee rate).

---

### 6. 🏛️ Bóveda de Almacenamiento SQLite WAL (`db_vault.py`)
* Motor de persistencia ACID de ultra-alta velocidad (microsegundos).
* **Modo WAL (Write-Ahead Logging)** con lectura y escritura no bloqueante: elimina por completo los errores de bloqueo de archivos en Windows (`WinError 32`).
* Tablas indexadas para `trades` y `equity_history` con migración transparente de archivos CSV existentes.

---

## 🔌 Puntos de Unión y Adaptador para Cuenta Real (Pionex)

El repositorio incluye [`pionex_bridge.py`](pionex_bridge.py), un módulo desacoplado diseñado específicamente para conectar el motor con la **API Spot de Pionex**:

* **Autenticación HMAC-SHA256**: Firmas y marcas de tiempo en milisegundos conforme a los estándares de Pionex.
* **Normalización de Pares**: Conversión automática de formatos (ej. `SAND/USDT` a `SAND_USDT`).
* **Operaciones Soportadas**:
  - `get_usdt_free()`: Consulta del saldo líquido para interés compuesto.
  - `place_limit_order(symbol, side, price, size)`: Creación de órdenes límite de compra/venta.
  - `cancel_order(symbol, order_id)`: Cancelación individual de órdenes.
  - `cancel_all_orders(symbol)`: Limpieza integral de órdenes para cosechas automáticas.
  - `test_connection()`: Comprobación de estado y credenciales sin arriesgar capital.
* **Modo Dry-Run / Simulación**: Si las claves no están configuradas en `.env`, el puente opera en modo simulado para pruebas seguras.

---

## 📊 Dashboard SPA Reactivo en Tiempo Real

El sistema sirve un cockpit visual local en **`http://localhost:8888`** con:
* **Curva de Equity Histórica Completa**: Representación desde el génesis ($80.00) hasta el tick actual sin recortes de datos.
* **Pestaña de Diagnóstico & Salud**: Tarjetas de telemetría de piso, breakeven, tiempo en anomalía y veredicto clínico.
* **Inspector con Tooltip Flotante**: Métricas exactas en cada instante temporal.
* **Auditoría PnL Sincronizada 1:1**: Refleja cada ciclo completado y cada malla en curso como `⚡ EN VIVO` con rendimiento flotante y comisiones deducidas.
* **Insignia del Scanner:** Identificación pura en modo `MALLA 🔸`.

---

## 📁 Estructura del Proyecto

```
bot grok/
├── paper_trading_agent.py     # Motor cuantitativo principal, gestor de mallas y servidor HTTP
├── db_vault.py                # Bóveda de almacenamiento SQLite en modo WAL de alta concurrencia
├── pionex_bridge.py           # Adaptador de integración directa con Pionex Spot API
├── dashboard_spa.py           # Interfaz gráfica reactiva (HTML5 / Tailwind CSS / JS)
├── self_eval.py               # Motor de auto-evaluación y auditoría PnL por ciclo
├── agent_committee.py         # Módulo colegiado de reglas cuantitativas de entrada
├── macro_radar.py             # Detección de régimen macro de BTC y volatilidad
├── meta_labeling.py           # Filtro clasificador Machine Learning para falsas rupturas
├── tests/                     # Suite de pruebas unitarias y de regresión (test_grid_engine.py)
├── paper_logs/                # Logs persistentes, estado del portafolio y transacciones
│   ├── portfolio_state.json   # Estado vivo de balance, mallas activas y tenencias
│   ├── trading_vault.db       # Bóveda SQLite con historial ACID y WAL
│   ├── equity_history.csv     # Historial cronológico de equity desde el génesis
│   └── trades.csv             # Registro contable de órdenes ejecutadas
├── .env.example               # Plantilla de configuración de credenciales y parámetros
└── README.md                  # Documentación institucional y operativa
```

---

## ⚙️ Configuración y Puesta en Marcha

### 1. Requisitos de Entorno
* Python 3.12 (`py -3.12`) recomendado en entornos Windows.
* Dependencias requeridas:
```bash
pip install requests python-dotenv pandas numpy ccxt
```

### 2. Configurar `.env`
Copia el archivo de ejemplo y ajusta tus preferencias:
```bash
cp .env.example .env
```

Parámetros clave en `.env`:
```env
TRADING_MODE=paper
EXCHANGE=pionex
INITIAL_CAPITAL=80.0
MIN_ORDER_USDT=10.0
COMPOUND_INTEREST=true
HTTP_PORT=8888
```

---

## 🚀 Comandos de Ejecución

### Ejecución Ordinaria (Preserva Historial)
```bash
py -3.12 paper_trading_agent.py
```

### Reinicio Limpio a Génesis ($80.00 USDT)
Para reiniciar el portafolio y los registros desde cero con $80.00:
```bash
py -3.12 paper_trading_agent.py --reset
```

### Ejecutar Suite de Tests de Regresión
```bash
py -3.12 -m unittest discover tests
```

### Abrir el Dashboard en Vivo
Ingresa en tu navegador a:
```
http://localhost:8888
```

### Agente de reversión (solo paper)
`reversion_agent.py` busca retrocesos moderados en una lista acotada de monedas líquidas. Una señal requiere caída de 3-8% en 24h, debilidad moderada frente a BTC y al menos $10M de volumen cotizado estimado en 24h; BTC no debe caer más de 4%. Además, la última vela horaria cerrada debe marcar mínimo creciente, cerrar hasta 1.5% por encima del máximo previo y tener entre 1.2x y 3x el volumen medio de las 20 velas anteriores. No compra únicamente porque una moneda haya caído, ni garantiza un rebote.

```bash
py -3.12 reversion_agent.py --once
py -3.12 tools/backtest_reversal.py
```

El agente sigue siendo exclusivamente de simulación (`PAPER`); el backtest usa las mismas reglas de señal.
