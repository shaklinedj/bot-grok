# 🚀 The Adaptive Swing Sniper & Bounded Micro-Grid Engine (v2)
### Motor Cuantitativo Autónomo Multi-Régimen con Fuerza Relativa, Ignición de Momentum y Autoaprendizaje Anti-Overfitting

---

## 📌 Visión y Filosofía Real del Sistema

Este proyecto es un **sistema de trading cuantitativo determinista y matemático** diseñado para operar con alta asimetría positiva en mercados Spot de criptomonedas (Binance y adaptador de telemetría para Pionex).

A diferencia de bots basados en grillas ingenuas que acumulan pérdidas en caídas o agentes lentos dependientes de llamadas LLM por tick, este motor ejecuta **lógica pura de microestructura, order flow y conmutación dinámica de régimen** en milisegundos.

### 📊 Stack Cuantitativo Completo (Pandas + NumPy + CCXT)
El repositorio combina **Pandas** para análisis exploratorio de datos, estimación de procesos Ornstein-Uhlenbeck, meta-labeling y pipelines de backtesting intensivo, junto con **NumPy vectorizado y CCXT** para el motor de ejecución en tiempo real de baja latencia, garantizando consistencia matemática y robustez en la toma de decisiones.

---

## ⚡ Arquitectura Cuantitativa Multi-Régimen

El sistema monitorea continuamente el régimen macro de Bitcoin (15m, 1h, 4h) y conmuta automáticamente entre tres modos de operación:

```
                               ┌────────────────────────────────────────────────────────┐
                               │           CENTINELA MACRO DE BITCOIN (BTC)             │
                               └────────────────────────────────────────────────────────┘
                                                            │
                     ┌──────────────────────────────────────┼──────────────────────────────────────┐
                     ▼                                      ▼                                      ▼
        ┌─────────────────────────┐            ┌─────────────────────────┐            ┌─────────────────────────┐
        │   BULLISH / NEUTRAL     │            │    CHOP COMPRESSION     │            │      BEARISH DUMP       │
        │     (Expansión)         │            │  (Rango 3h < 0.90%)     │            │   (BTC < EMA20 1H)      │
        └─────────────────────────┘            └─────────────────────────┘            └─────────────────────────┘
                     │                                      │                                      │
                     ▼                                      ▼                                      ▼
        ┌─────────────────────────┐            ┌─────────────────────────┐            ┌─────────────────────────┐
        │   MODO SWING SNIPER     │            │   MODO MALLA ACOTADA    │            │     MODO BÚNKER         │
        │ • Rupturas 15m + RS     │            │ • Hurst H < 0.46        │            │ • Caja 100% USDT        │
        │ • Ignición Momentum 3.4R│            │ • Reversión a la Media  │            │ • Compras bloqueadas    │
        │ • Trailing 1.5x ATR     │            │ • Kill-Switch Estricto  │            │ • Cero exposición       │
        └─────────────────────────┘            └─────────────────────────┘            └─────────────────────────┘
```

### 1. Modo Swing Sniper (Expansión Tendencial)
- **Fuerza Relativa (RS vs BTC):** Identifica activos que resisten o lideran la subida frente a Bitcoin.
- **Ruptura 15m + Spike de Volumen:** Exige confirmación de ruptura de micro-resistencia con volumen agresivo ($> 1.2\times$ promedio).
- **Ignición de Momentum (arXiv:2602.11708):** Detecta velas de expansión institucional ($> 2.0\times$ volumen, rango expandido $\ge 1.2\times$ ATR, cuerpo $\ge 55\%$) y proyecta targets asimétricos de **3.4R**.
- **Centinela de Order Flow (Tape & L2):** Verifica en el libro de órdenes (Order Book Imbalance) y cinta de compras agresivas antes de disparar. Si detecta muros de venta o agresiones bajistas, veta el trade defensivamente.
- **Trailing Stop con Oxígeno (1.5x ATR):** No asfixia la posición en el despegue; se activa al superar $+1.8\%$ y da holgura de $1.5\times$ ATR para capturar rallies completos.

### 2. Modo Malla Acotada (Compresión Lateral / Chop)
- **Exponente de Hurst ($H < 0.46$):** Filtra matemáticamente activos con reversión a la media comprobada (anti-persistentes).
- **Canal Horizontal (1.0% a 4.5% de ancho):** Despliega micro-rejillas de 3 niveles en la mitad inferior del canal.
- **Ejecución Inmediata:** Solo se activa si el precio actual está en el suelo del canal, erradicando mallas fantasma.
- **Kill-Switch Estricto:** Si el precio rompe el soporte del canal, liquida de inmediato a mercado para evitar atrapamientos (*bagholding*).
- **Cosecha Inmediata:** Toma beneficios al tocar la resistencia o al superar el punto medio del canal con ganancia neta.

### 3. Modo Búnker (Protección Macro)
- Si Bitcoin entra en corrección agresiva por debajo de su EMA20 horaria, se bloquean preventivamente todas las compras en altcoins, refugiando el 100% del capital en USDT.

---

## 🔬 Autoaprendizaje Adaptativo Anti-Overfitting

Para evitar el sobreajuste (*parameter thrashing*) tras un solo trade adverso:
1. **Ventana Móvil de 20 Trades:** Los parámetros de riesgo (distancia de trailing, multiplicador de stop, score mínimo) solo se ajustan si un patrón clínico (asfixia prematura o stops por ruido) supera el **25% de frecuencia** en los últimos 20 trades.
2. **Tasa de Aprendizaje Decreciente:**
   $$\eta_t = \frac{\eta_0}{1 + 0.05 \cdot t}$$
   A medida que el bot acumula experiencia ($t$ trades cerrados en SQLite), los ajustes se vuelven más pequeños y suaves, forzando la convergencia matemática.
3. **Trazabilidad Unívoca (`parent_trade_id`):** Cada trade de entrada (`BUY`) y salida (`SELL`) se vincula determinísticamente en SQLite, permitiendo auditorías de rentabilidad, comisiones y tiempo de retención.

---

## 🏛️ Monitoreo Seguro de la Malla Real Pionex

El sistema incluye telemetría en **modo SOLO LECTURA** de la malla real de DOGE en Pionex:
- Consulta en segundo plano el bot con ID `215617258385481728`.
- Reporta inversión, ganancias de arbitraje emparejadas y rango en el dashboard.
- **Garantía de Seguridad:** Ninguna orden en cuenta real es creada, modificada o cancelada por este agente.

---

## 📁 Arquitectura Modular del Repositorio

```
bot grok/
├── config.py                  # Única fuente de verdad: constantes, comisiones, rutas y CCXT
├── database.py                # SwingDatabase: persistencia SQLite WAL y parent_trade_id
├── hourly_swing_agent.py      # Fachada y punto de entrada principal
├── quantum_terminal.html      # Terminal de simulación cuántica Monte Carlo (1,000 runs)
├── requirements.txt           # Dependencias completas del ecosistema (Pandas, NumPy, CCXT, etc.)
├── engine/
│   ├── bot_models.py          # Dataclasses: SwingTrade, GridLevel, BoundedMicroGrid
│   ├── swing_bot.py           # Contenedor de estado, telemetría y persistencia
│   └── swing_engine.py        # Orquestador del ciclo de control y escáner de mercado
├── scoring/
│   ├── indicators.py          # Indicadores puros: EMA, RSI, ATR, Hurst y Canales
│   ├── market_scanner.py      # Escáner L1/L2, contexto BTC y telemetría Pionex
│   ├── order_flow.py          # Centinela de Tape y Order Book Imbalance (L2)
│   └── breakout.py            # Detector de Rupturas 15m e Ignición de Momentum
├── risk/
│   ├── risk_manager.py        # Trailing Stop 1.5x ATR, Break-Even dinámico y salidas
│   └── adaptive.py            # Motor de autopsias con ventana de 20 trades y decaying LR
├── grid/
│   └── bounded_grid.py        # Lógica de Malla Acotada en Chop con Kill-Switch
├── server/
│   ├── routes.py              # Rutas HTTP, API REST (/api/status, /api/history, /api/settings)
│   └── templates.py           # Dashboard SPA reactivo completo (HTML5 / Canvas)
└── tests/
    ├── test_hourly_swing.py   # 20 tests unitarios cuantitativos
    └── test_integration_http.py # 7 tests de integración HTTP contra servidor efímero
```

---

## 💻 Requisitos y Puesta en Marcha

### 1. Requisitos de Entorno
- Python 3.12 (`py -3.12` en Windows, `python3` en Linux/macOS).
- Dependencias mínimas y reales:

```bash
pip install -r requirements.txt
```

*(Dependencias clave: `ccxt`, `numpy`, `pandas`, `python-dotenv`, `requests`, `pytest`).*

### 2. Ejecutar el Bot en Producción
```bash
py -3.12 -u hourly_swing_agent.py
```

### 3. Ejecutar la Suite de Pruebas Automatizadas
Todos los 27 tests unitarios y de integración HTTP se ejecutan con:
```bash
py -3.12 -m pytest tests/test_hourly_swing.py tests/test_integration_http.py -v
```

---

## 📊 Dashboards y Terminales en Vivo

Una vez iniciado el bot, los siguientes accesos locales quedan disponibles en tu navegador:

- **Cockpit Dashboard Principal:** [http://localhost:8900](http://localhost:8900)
  - Curva de Patrimonio acumulada en tiempo real.
  - Modal interactivo con historial completo de trades emparejados.
  - Telemetría en vivo del radar de mercado, estado de BTC y posiciones abiertas.
  - Faders de control para reconfigurar umbrales en caliente vía API REST.
- **Terminal Cuántica Monte Carlo:** [http://localhost:8900/quantum](http://localhost:8900/quantum)
  - Proyección probabilística de 1,000 caminos Monte Carlo sobre el capital real en cartera.
  - Métricas de Value-at-Risk (VaR 95%), Expected Shortfall y distribución de retornos.
