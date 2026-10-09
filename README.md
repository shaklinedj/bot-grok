# 🤖 Quantitative Grid Trading Bot (v12)
### Motor Cuantitativo Algorítmico Autónomo de Mallas Spot, Interés Compuesto Estricto y Adaptador para Pionex

---

## 📌 Visión y Filosofía Real del Proyecto

Este proyecto es un **sistema de trading cuantitativo determinista y matemático** diseñado para operar en mercados Spot de criptomonedas (adaptable a **Pionex** y **Binance**). 

A diferencia de modelos que dependen de llamadas lentas o impredecibles a modelos de lenguaje (LLMs), este motor ejecuta **lógica algorítmica pura, cuantitativa y de baja latencia** basada en microestructura de mercado, flujo de órdenes y geometría de rejilla adaptativa.

---

## ⚡ Principios Cuantitativos y Pilares Operativos

### 1. 🔁 Interés Compuesto Estricto (Cada Centavo se Reinvierten)
* **Reinversión Inmediata de Ganancias**: Cada micro-ganancia obtenida al cerrar un ciclo o escalón de venta se suma de inmediato a `bot.cash` (efectivo líquido disponible).
* **Dimensionamiento Dinámico**: Las nuevas órdenes y mallas calculan su tamaño sobre el capital actualizado en tiempo real. Si la cuenta gana \$0.15 USDT en una rotación, esos \$0.15 USDT quedan instantáneamente disponibles para financiar los siguientes escalones de compra.

### 2. 🛡️ Escalabilidad de Concurrencia por Capital (Slots Dinámicos)
Para proteger micro-cuentas y evitar la fragmentación destructiva del margen, la cantidad de mallas concurrentes se escala automáticamente según el equity total:

| Equity de la Cuenta (USDT) | Máximo de Mallas Simultáneas | Enfoque Estratégico |
|---|:---:|---|
| **\$80.00 – \$125.00** | **1 Malla Activa** | Concentración total de liquidez en el candidato #1 del radar. |
| **\$125.00 – \$250.00** | **2 Mallas Activas** | Diversificación inicial en 2 activos con baja correlación. |
| **\$250.00 – \$375.00** | **3 Mallas Activas** | Rotación fluida entre líderes de volatilidad. |
| **\$375.00 – \$550.00** | **4 Mallas Activas** | Cobertura amplia de canales laterales. |
| **> \$550.00** | **Hasta 6 Mallas** | Escalamiento compuesto institucional. |

### 3. 🕸️ Malla Neutral Dinámica de 6 a 7 Líneas (Micro-Cuentas de $80)
* En cuentas de **$80 USDT**, el bot concentra su capital en **6 a 7 líneas** (3-4 compras límite escalonadas y 3 ventas límite escalonadas).
* **Tamaño por Orden:** ~\$10.50 a \$12.50 USDT por línea, superando holgadamente los límites mínimos de intercambio (`minNotional` de \$5 a \$10 USDT).
* **Paso Dinámico (Dynamic Step):** Entre **0.95% y 1.35%** adaptado al ATR y al spread, reduciendo la distancia al primer rebote para acelerar las ejecuciones y generar flujo de caja frecuente.

### 4. 🌾 Mecanismo "Victoria Total" (Auto-Harvest)
* Cuando una malla alcanza el techo de su rango y liquida el 100% de sus órdenes de venta (`active_sells == 0`):
  1. El supervisor ejecuta el cierre inmediato de la malla.
  2. Cancela órdenes límite de compra sobrantes.
  3. Devuelve todo el capital bloqueado a la caja líquida en USDT.
  4. La cuenta queda libre y lista para desplegar una nueva malla en el siguiente activo líder del radar.

### 5. 🔬 Filtros Cuantitativos de Microestructura
* **Kaufman Efficiency Ratio (KER):** Discrimina entre mercados en rango lateral (óptimos para mallas) y rupturas direccionales agresivas.
* **Order Book Imbalance (OBI):** Mide la presión relativa de liquidez entre bids y asks en el libro de órdenes.
* **Filtro Anti-Cresta:** Prohíbe compras cuando el RSI supera niveles de sobrecompra o cuando el precio está extendido.
* **Régimen Macro de Bitcoin:** Ajusta el nivel de exposición según la tendencia y volatilidad de BTC (4h / 1d).

---

## 🔌 Puntos de Unión y Adaptador para Cuenta Real (Pionex)

El repositorio incluye [`pionex_bridge.py`](pionex_bridge.py), un módulo desacoplado diseñado específicamente para conectar el motor con la **API Spot de Pionex**:

* **Autenticación HMAC-SHA256**: Generación de firmas y marcas de tiempo en milisegundos conforme a los estándares de Pionex.
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
* **Curva de Equity Histórica Completa**: Representación desde el génesis (\$80.00) hasta el tick actual sin recortes de datos.
* **Inspector con Crosshair & Tooltip Flotante**: Al pasar el ratón sobre cualquier punto del gráfico, muestra:
  - ⏱️ Timestamp real registrado.
  - 💰 Equity exacto en ese instante.
  - 📈 Ganancia neta y porcentaje acumulado vs el depósito inicial.
* **Auditoría PnL Sincronizada 1:1**: Refleja cada ciclo completado y cada malla en curso como `⚡ EN VIVO` con su rendimiento flotante y comisiones deducidas.

---

## 📁 Estructura del Proyecto

```
bot grok/
├── paper_trading_agent.py     # Motor cuantitativo principal, gestor de mallas y servidor HTTP
├── pionex_bridge.py           # Adaptador de integración directa con Pionex Spot API
├── dashboard_spa.py           # Interfaz gráfica reactiva (HTML5 / Tailwind CSS / JS)
├── self_eval.py               # Motor de auto-evaluación y auditoría PnL por ciclo
├── agent_committee.py         # Módulo colegiado de reglas cuantitativas de entrada
├── macro_radar.py             # Detección de régimen macro de BTC y volatilidad
├── meta_labeling.py           # Filtro clasificador Machine Learning para falsas rupturas
├── paper_logs/                # Logs persistentes, estado del portafolio y transacciones
│   ├── portfolio_state.json   # Estado vivo de balance, mallas activas y tenencias
│   ├── equity_history.csv     # Historial cronológico de equity desde el génesis
│   └── trades.csv             # Registro contable de órdenes ejecutadas
├── .env.example               # Plantilla de configuración de credenciales y parámetros
└── README.md                  # Documentación institucional y operativa
```

---

## ⚙️ Configuración y Puesta en Marcha

### 1. Clonar el Repositorio
```bash
git clone https://github.com/shaklinedj/bot-grok.git
cd bot-grok
```

### 2. Instalar Dependencias
```bash
pip install requests python-dotenv pandas numpy
```

### 3. Configurar `.env`
Copia el archivo de ejemplo y ajusta tus preferencias:
```bash
cp .env.example .env
```

Parámetros en `.env`:
```env
# Modo Operativo: 'paper' (simulación realista) | 'live' (ejecución real en Pionex)
TRADING_MODE=paper
EXCHANGE=pionex

# Credenciales Pionex Spot (Para cuando decidas conectar tu cuenta real)
PIONEX_API_KEY=tu_api_key_de_pionex
PIONEX_API_SECRET=tu_api_secret_de_pionex

# Parámetros de Capital e Interés Compuesto
INITIAL_CAPITAL=80.0
MIN_ORDER_USDT=10.0
COMPOUND_INTEREST=true

HTTP_PORT=8888
```

---

## 🚀 Comandos de Ejecución

### Ejecución Ordinaria (Preserva Historial)
```bash
python paper_trading_agent.py
```

### Reinicio Limpio a Génesis ($80.00 USDT)
Para reiniciar el portafolio y los registros desde cero con \$80.00:
```bash
python paper_trading_agent.py --reset
```

### Probar Conexión con Pionex
Para verificar que tus claves de Pionex sean válidas antes de operar en real:
```bash
python pionex_bridge.py
```

### Abrir el Dashboard en Vivo
Ingresa en tu navegador a:
```
http://localhost:8888
```
