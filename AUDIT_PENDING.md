# Auditoría: hallazgos pendientes de corrección

Contexto: auditoría manual de `paper_trading_agent.py`. Las correcciones ya aplicadas fueron: cierre prematuro de malla (exigir `fills_count > 0`), conservación del capital reservado al reubicar compras, uso de `buy_price` real en VWAP/relief exit, escritura atómica de `portfolio_state.json` y `brain_state.json`, eliminación de CORS `*`, y textos desactualizados (`/2` → `MAX_RISK_SLOTS`, `$5` → `$10`).

Pendientes, por prioridad:

## Alta
1. **Matemática de la malla** (`paper_trading_agent.py`, creación de malla y supervisor dinámico)
   - `step_pct = step_size / grid_lower` combinado con pasos aritméticos: las ventas reposicionadas (`price * (1 + step_pct)`) quedan desalineadas respecto a las líneas originales. Evaluar paso geométrico o guardar el paso absoluto por línea.
   - El rebalanceo reprecia ventas con `curr_p * (1 + step_pct*(idx+1))`, que puede mover una venta por debajo/encima de lo esperado y rompe la relación compra→venta original.
   - Los fills se evalúan solo contra el precio del tick (`curr_p`); una mecha que cruce varias líneas entre ticks no se simula (un solo fill por línea por tick, sin orden ni parciales). Usar high/low de la vela o procesar líneas ordenadas.
2. **Errores tragados al cargar estado**: `load_state` / `load_portfolio_state` usan `except: pass` en partes (y `from_dict` de longs/grids). Un JSON corrupto hace arrancar con cash=80 silenciosamente. Debe fallar ruidosamente o respaldar el archivo corrupto (`.bak`) y avisar.
3. **Race en logs CSV**: `update_live_state` lee `trades.csv` y `equity_history.csv` mientras el hilo principal escribe, sin lock. Añadir lock compartido o mantener los datos en memoria.

## Media
4. **Ruta hardcodeada de Windows**: `ARTIFACT_DIR = C:\Users\Dell\...`. Hacerla configurable por variable de entorno y opcional; manejar su ausencia sin excepciones.
5. **Lógica de aprendizaje** (`ReinforcementBrain`):
   - `min_score_required` sube +2.5 por pérdida hasta 85 y baja solo 1.0 por ganancia: puede dejar al bot sin operar. Considerar decaimiento temporal.
   - `coin_pnl_memory` crece sin límite; acotar a las últimas N entradas y persistirlo (hoy no se guarda en `brain_state.json`, así que blacklist y memoria se pierden al reiniciar).
   - `load_state` impone suelos (`max(1.80, ...)`, `max(2.50, ...)`) que ignoran valores guardados menores.
6. **Realismo del paper trading**: fills límite instantáneos al tocar precio (sin cola/parciales), slippage de market aleatorio (`random.uniform`, no reproducible; añadir semilla configurable), volumen fijo asumido (20M) en cierres de `manage_longs`, y fallback `15_000_000` si falta `quoteVolume`.
7. **`except Exception: pass` en el handler HTTP** y en `save_state` del cerebro: registrar al menos el error.

## Baja
8. **Higiene del repo**: scripts de parche puntuales (`fix_*.py`, `migrate_*.py`, `update_grids_payload.py`, `center_grid.py`) y dos versiones del agente (`paper_trading_agent.py` / `paper_trading_agent2.py`). Consolidar o mover a `legacy/`.
9. **Docstring del módulo desactualizado** (habla de v11, $25 mínimo, 2 posiciones; el código usa $10 mínimo y hasta 15 posiciones).
10. **No revisados a fondo**: `paper_trading_agent2.py`, `dashboard_spa.py`, `macro_radar.py`, `meta_labeling.py`, `self_eval.py`, `ai_auditor.py`, `agent_committee.py`, `news_sentinel.py`. Auditar las mismas clases de problemas (races, estado, divisiones por cero, tipeo).
11. **Sin tests**: añadir tests unitarios para la lógica de malla (fills, victoria total, stop estructural, trailing) y la contabilidad de equity.

## Seguridad (sin hallazgos críticos)
- API key NVIDIA vía entorno; `.env.example` solo plantilla. Dashboard solo en `127.0.0.1`. Mantener así; no volver a abrir CORS.
