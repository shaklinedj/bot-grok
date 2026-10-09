# 🤖 Binance Spot Quantitative Trading Bot (v12)
### Sistema Institucional de Trading Cuantitativo Autónomo con Mallas Adaptativas, Escalado Dinámico por Capital y Comité Multi-Agente con IA (NVIDIA NIM)

---

## 📌 Visión General

El **Binance Spot Quantitative Trading Bot v12** es un motor autónomo de alta frecuencia y trading cuantitativo diseñado específicamente para el mercado al contado (**Spot**) de **Binance**. Su arquitectura combina:

1. **Malla Neutral Adaptativa Pionex-Style** de alta rotación con protección contra caídas y amortiguación elástica.
2. **Escalabilidad Orgánica de Capital**: Gobernanza estricta de concurrencia que permite arrancar desde micro-cuentas de **$80.00 USDT** con **1 solo bot** y escalar de forma compuesta conforme el equity crece.
3. **Supervisor Cuantitativo "Victoria Total" (Auto-Harvest)**: Cosecha instantánea del capital cuando se completan todos los ciclos de venta, reincorporando la liquidez a caja para rotar hacia el activo más prometedor del mercado.
4. **Comité Multi-Agente con IA (NVIDIA NIM)**: Deliberación institucional previa a cada orden entre Centinela Macro, Arquitecto de Mallas, Jefe de Riesgo y Francotirador de Ejecución.
5. **Dashboard Reactivo SPA en Vivo**: Cockpit visual en tiempo real en `http://localhost:8888` con curva de equity histórica completa desde el génesis, inspector interactivo con mira telescópica (crosshair) y sincronización auditada 1:1.

---

## ⚙️ Arquitectura de Capital y Escalabilidad Dinámica

Para garantizar la supervivencia matemática y evitar la dispersión de liquidez, el sistema ajusta la cantidad máxima de mallas activas en función del equity actual:

| Equity Actual (USDT) | Límite de Mallas Concurrentes | Capital por Malla (Aprox.) | Líneas por Malla | Tamaño por Orden (USDT) |
|---|:---:|:---:|:---:|:---:|
| **\$80.00 – \$125.00** | **1 Malla Activa** | ~$50 – $60 USDT | 3 a 5 líneas | **\$11 – \$15 USDT** |
| **\$125.00 – \$250.00** | **2 Mallas Activas** | ~$55 – $65 USDT c/u | 4 a 6 líneas | **\$12 – \$16 USDT** |
| **\$250.00 – \$375.00** | **3 Mallas Activas** | ~$60 – $75 USDT c/u | 5 a 6 líneas | **\$14 – \$18 USDT** |
| **\$375.00 – \$550.00** | **4 Mallas Activas** | ~$70 – $90 USDT c/u | 5 a 7 líneas | **\$18 – \$25 USDT** |
| **> \$550.00** | **Hasta 6 Mallas** | Escalamiento compuesto | 6 a 8 líneas | **\$25+ USDT** |

* Todos los tamaños de orden superan estrictamente el requisito mínimo `minNotional` de Binance Spot (\$5.00 a \$10.00 USDT), evitando órdenes rechazadas por el motor de calce.

---

## 🚀 Innovaciones Clave del Motor v12

### 1. 🌾 Cosecha Total Automática ("Victoria Total")
* Cuando las órdenes de venta activas de una malla se reducen a cero (`active_sells == 0`), el supervisor interpreta que la moneda completó todo su recorrido alcista.
* En ese milisegundo exacto, cancela las órdenes residuales de compra, devuelve el 100% del capital bloqueado a la caja líquida en USDT y finaliza el ciclo en ganancia absoluta.

### 2. 🎯 Paso Dinámico Anti-Cresta (Dynamic Step)
* El ancho entre escalones se calcula dinámicamente (`0.95% a 1.35%`) a partir del ATR (Average True Range) y la profundidad del libro de órdenes.
* El canal de cobertura abarca un colchón de **±2.5% a ±3.5%**, absorbiendo la volatilidad ordinaria del mercado sin quedar descolgado en techos de precio.

### 3. 🛡️ Protección de Fricción Realista (Binance Spot)
* Cada operación simula comisiones reales (0.10% Maker/Taker o BNB discount).
* Slippage dinámico basado en liquidez de libro (spread bid-ask).
* Se prohíbe el despliegue de órdenes de venta sin margen positivo verificable.

### 4. 🧠 Comité Multi-Agente con IA (NVIDIA NIM / Llama 3.3 70B)
* **Centinela Macro**: Monitorea el régimen de Bitcoin (4h / 1d) y suspende aperturas si el mercado experimenta caídas abruptas.
* **Arquitecto de Mallas**: Determina los niveles de soporte, resistencia y concentración de volumen para posicionar la malla.
* **Jefe de Gestión de Riesgo**: Asigna el multiplicador de capital prudente basándose en la memoria de pérdidas y ganancias pasadas.
* **Coordinador Francotirador**: Define la táctica óptima de entrada (Maker pasivo vs Taker agresivo).

### 5. 📈 Dashboard SPA con Curva Histórica y Crosshair Interactivo
* **Historial Completo desde Génesis**: Muestra la evolución desde el depósito inicial de \$80.00 hasta el último tick sin omisiones.
* **Inspector con Crosshair & Tooltip Flotante**: Al pasar el mouse por cualquier instante del gráfico, visualiza:
  - ⏱️ Fecha y hora exacta registrada.
  - 💰 Equity en ese instante.
  - 📈 Rendimiento porcentual y monetario acumulado frente al balance inicial.
* **Sincronización 1:1 en Auditoría**: Cada malla activa se refleja en tiempo real como `⚡ EN VIVO` en la tabla de auditoría financiera, garantizando transparencia absoluta entre lo reportado y el balance real.

---

## 📁 Estructura del Código

```
bot grok/
├── paper_trading_agent.py     # Motor cuantitativo principal, gestor de mallas y servidor HTTP
├── dashboard_spa.py           # Dashboard interactivo en tiempo real (SPA HTML5/Tailwind/JS)
├── self_eval.py               # Motor de auto-evaluación y auditoría PnL por ciclo
├── agent_committee.py         # Comité de 4 agentes con deliberación e inferencia de IA
├── ai_auditor.py              # Auditor forense post-trade (NVIDIA NIM)
├── news_sentinel.py           # Centinela de noticias y análisis de sentimiento macro
├── macro_radar.py             # Detección de régimen macro de BTC y volatilidad
├── meta_labeling.py           # Filtro clasificador Machine Learning
├── paper_logs/                # Logs persistentes, estado del portafolio y datasets
│   ├── portfolio_state.json   # Estado vivo de caja, mallas y tenencias
│   ├── equity_history.csv     # Registro cronológico del equity desde el génesis
│   ├── trades.csv             # Libro contable de operaciones ejecutadas
│   └── live_state.json        # Snapshot de transmisión para el dashboard
└── README.md                  # Documentación del proyecto
```

---

## 🛠️ Instalación y Configuración

### 1. Clonar el Repositorio
```bash
git clone https://github.com/shaklinedj/bot-grok.git
cd bot-grok
```

### 2. Instalar Dependencias de Python
Requiere Python 3.10 o superior:
```bash
pip install requests python-dotenv pandas numpy
```

### 3. Configurar Variables de Entorno (Opcional para IA)
Crea un archivo `.env` en la raíz del proyecto para habilitar los diagnósticos avanzados con NVIDIA NIM:
```env
NVIDIA_API_KEY=tu_api_key_de_nvidia_nim_aqui
```
*(Si no se proporciona clave de IA, el bot utiliza reglas heurísticas y modelos cuantitativos locales sin interrumpir su operativa).*

---

## ▶️ Ejecución

### Iniciar el Bot en Modo Normal
Para continuar con la sesión y preservar el historial acumulado:
```bash
python paper_trading_agent.py
```

### Reiniciar desde Cero (Génesis en $80.00 USDT)
Para limpiar el historial y arrancar un portafolio fresco con $80.00 USDT:
```bash
python paper_trading_agent.py --reset
```

### Acceder al Dashboard en Tiempo Real
Abre tu navegador en:
```
http://localhost:8888
```

---

## 📊 Métricas Operativas en Vivo

* **Depósito Base Inicial:** \$80.00 USDT
* **Tasa de Riesgo de Supervivencia:** Equity &ge; 60% (\$48.00 USDT)
* **Frecuencia de Ticks:** 1.5 segundos
* **Escaneo de Candidatos (Radar):** Cada 20 segundos
* **Sincronización de Auditoría:** Cada 15 segundos
* **Modo de Red:** Binance Spot API (Lectura de datos públicos en vivo sin saturación de endpoints)
