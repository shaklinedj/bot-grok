"""
THE ADAPTIVE SWING SNIPER V2 & BOUNDED GRID ENGINE (Modular Facade & Entrypoint)

Arquitectura Modular:
- config: Constantes unificadas, configuración y cliente CCXT.
- database: SwingDatabase con SQLite WAL, migraciones y logging determinístico.
- engine: Modelos de datos (SwingTrade, GridLevel, BoundedMicroGrid), SwingBot y bucle principal.
- scoring: Indicadores (EMA, RSI, ATR, Hurst, Canales), Escáner L1/L2, Order Flow Tape y Breakout 15m.
- risk: Trailing Stop Ágil (1.5x ATR), Break-Even, Autopsias y Aprendizaje Adaptativo con Decaying LR.
- grid: Malla Acotada (Bounded Micro-Grid) para regímenes laterales (CHOP_COMPRESSION).
- server: Servidor HTTP Dashboard reactivo (puerto 8900) y Terminal Cuántica (/quantum).
"""
import sys

# Configurar encoding UTF-8 seguro para consola Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 1. Configuración y Constantes
from config import (
    BASE_DIR,
    SWING_DIR,
    SWING_DB_FILE,
    SWING_STATE_FILE,
    SWING_HTTP_PORT,
    REAL_DOGE_GRID_BOT_ID,
    FEE_RATE,
    MIN_SCORE_V2,
    POST_STOP_EXTRA_SCORE,
    POST_STOP_COOLDOWN_S,
    RS_MIN_THRESHOLD,
    IGNORE_SYMBOLS,
    MIN_VOLUME_USDT,
    DEFAULT_SETTINGS,
    exchange
)

# 2. Base de Datos
from database import SwingDatabase

# 3. Modelos de Datos y Contenedor de Estado
from engine.bot_models import SwingTrade, GridLevel, BoundedMicroGrid
from engine.swing_bot import SwingBot

# 4. Scoring, Indicadores y Escáner de Mercado
from scoring.indicators import (
    calc_ema,
    calc_rsi,
    calc_atr,
    calc_hurst_exponent,
    detect_horizontal_channel
)
from scoring.market_scanner import (
    fetch_ohlcv_cached,
    update_btc_context,
    scan_market_top_movers,
    fetch_real_pionex_grid_stats
)
from scoring.order_flow import fetch_order_flow_confirmation
from scoring.breakout import analyze_breakout_15m

# 5. Gestión de Riesgo y Autoaprendizaje Adaptativo (Ventana Móvil 20 trades + Decay LR)
from risk.risk_manager import manage_active_swing_trade
from risk.adaptive import (
    process_trade_autopsy_and_feedback,
    calculate_decaying_learning_rate
)

# 6. Malla Acotada en Chop
from grid.bounded_grid import (
    scan_bounded_grid_candidates,
    manage_active_bounded_grid
)

# 7. Servidor HTTP Dashboard y Templates
from server.templates import DASHBOARD_HTML
from server.routes import SwingHTTPRequestHandler, start_swing_dashboard

# 8. Orquestación y Bucle Principal
from engine.swing_engine import (
    execute_swing_paper_entry,
    swing_telemetry_thread,
    run_hourly_swing
)

__all__ = [
    # Config
    "BASE_DIR",
    "SWING_DIR",
    "SWING_DB_FILE",
    "SWING_STATE_FILE",
    "SWING_HTTP_PORT",
    "REAL_DOGE_GRID_BOT_ID",
    "FEE_RATE",
    "MIN_SCORE_V2",
    "POST_STOP_EXTRA_SCORE",
    "POST_STOP_COOLDOWN_S",
    "RS_MIN_THRESHOLD",
    "IGNORE_SYMBOLS",
    "MIN_VOLUME_USDT",
    "DEFAULT_SETTINGS",
    "exchange",
    # Database
    "SwingDatabase",
    # Models
    "SwingTrade",
    "GridLevel",
    "BoundedMicroGrid",
    "SwingBot",
    # Scoring
    "calc_ema",
    "calc_rsi",
    "calc_atr",
    "calc_hurst_exponent",
    "detect_horizontal_channel",
    "fetch_ohlcv_cached",
    "update_btc_context",
    "scan_market_top_movers",
    "fetch_real_pionex_grid_stats",
    "fetch_order_flow_confirmation",
    "analyze_breakout_15m",
    # Risk
    "manage_active_swing_trade",
    "process_trade_autopsy_and_feedback",
    "calculate_decaying_learning_rate",
    # Grid
    "scan_bounded_grid_candidates",
    "manage_active_bounded_grid",
    # Server
    "DASHBOARD_HTML",
    "SwingHTTPRequestHandler",
    "start_swing_dashboard",
    # Engine
    "execute_swing_paper_entry",
    "swing_telemetry_thread",
    "run_hourly_swing"
]

if __name__ == "__main__":
    run_hourly_swing()
