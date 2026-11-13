# BOT GROK: MEMORIA PERMANENTE, REGLAS OPERATIVAS Y PROTOCOLO INSTITUCIONAL

Este archivo define la memoria permanente, filosofía de gestión y directivas inquebrantables del proyecto **Bot Grok**.
Debe ser leído y respetado por el agente en cada turno y nueva sesión sin excepción.

---

## 1. MANDATO INQUEBRANTABLE DE PENSAMIENTO CRÍTICO (SKILL: `critical-thinking-partner`)
- **Prohibido el servilismo cognitivo (Zero Yes-Man):** Nunca adular al usuario ni darle la razón por complacencia. Si una hipótesis del usuario o del agente tiene riesgos ocultos, sesgos o fallas matemáticas, se debe exponer de inmediato con datos forenses.
- **Rigor cuantitativo:** Cada afirmación sobre rendimiento, rentabilidad o fallas debe validarse directamente contra las bases SQLite (`swing_vault.db`), APIs en vivo y logs reales. Nunca asumir ni inventar números.
- **Tamaño de muestra (`N > 1`):** Un solo trade o fill nunca es prueba estadística de nada. Mantener la cautela matemática ante rachas cortas.

---

## 2. REGLAS CONTABLES Y TRANSPARENCIA RADICAL (LEVERAGE VS MARGEN)
- **Equity Real:** El Patrimonio Total (Equity) en Swing Sniper representa **exclusivamente capital propio real** (`cash + tr.capital + unrealized_pnl`).
- **Separación de Apalancamiento:** Queda terminantemente prohibido inflar el equity con el volumen nocional apalancado (`tr.amount * price`). 
- **Presentación en Dashboard y API:** El margen propio invertido (`invested`) y la exposición apalancada (`notional_exposure`) deben mostrarse siempre por separado tanto en el dashboard como en `/api/status`.

---

## 3. LOS 3 PILARES DEL SISTEMA

### PILAR 1: BINANCE CASH & CARRY (`LIVE_BINANCE`)
- Monitoreo de posición delta-neutral en futuros/spot (ej. `XVG/USDT`).
- Fondeo pasivo con cobros periódicos de funding rate (cada 8 horas).
- En vivo es modo pasivo auditado; el bot no rota arbitrariamente la posición viva del usuario sin instrucción explícita.

### PILAR 2: SWING SNIPER V2 (`PAPER_SWING`)
- **Apalancamiento:** `2.0x` sobre capital propio (`SNIPER_LEVERAGE = 2.0`).
- **Salida Asimétrica en 3 Fases:**
  1. **TP1 (50% al +1.5R):** Asegura caja inmediata y sube stop a `+0.5R` (Free Roll).
  2. **TP2 (25% al +3.0R):** Cosecha masiva intermedia y ciñe stop a `+1.8R`.
  3. **Moonbag Runner (25% final):** Corre sin techo fijo guidado por Trailing Stop dinámico acelerado (`1.50x ATR` -> `0.80x ATR` en Fase 2 -> `0.45x ATR` en Fase 3).
- **Filtros Institucionales de Entrada:**
  - **Taker Buy Ratio:** Mínimo `58.0%` de compras a mercado agresivas en la cinta para autorizar trade apalancado (erradica trampas tipo `54.5%`).
  - **Centinela Apertura Wall Street:** Pausa de 10 minutos (10:30 a 10:40 hora local / 14:30 a 14:40 UTC) de lunes a viernes contra barridas de apertura.
  - **Clímax de Agotamiento:** Veto si compras > `78.0%` (anti-FOMO).
  - **Shadow Veto Tracker:** Cada orden vetada se registra en SQLite `veto_autopsies` y se rastrea contrafactualmente durante 1 hora para medir capital salvado y calibración de filtros.

### PILAR 3: BUDA.COM MARKET MAKER (`USDT/CLP` SIMULADOR)
- Cotización bidireccional continua en el libro de Buda.
- **Interés Compuesto Activo:** Cada ganancia incrementa automáticamente el tamaño de las órdenes siguientes.
- **Utilización Agresiva de Capital (70%):** En modo equilibrado o sesgado, coloca órdenes del `70%` del saldo disponible en cada lado (compra/venta) para maximizar la velocidad de rotación sin congelar la cuenta.
- **Protección Break-Even y Costo Promedio:** `avg_cost_price` persistido en SQLite para nunca vender por debajo del costo real más comisiones maker (`0.18%`).

---

## 4. GESTIÓN DE PROCESOS 24/7 EN WINDOWS
- Los tres pilares corren supervisados por [`master_daemon.py`](file:///C:/Users/Dell/Desktop/bot%20grok/master_daemon.py).
- Si un agente se detiene o se modifica, el daemon maestro lo reinicia automáticamente en menos de 15 segundos sin matar los otros procesos.
- Script de arranque maestro en Windows: `INICIAR_BOT_24_7.vbs` y acceso directo en `shell:startup`.
