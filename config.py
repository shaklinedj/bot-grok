"""
Configuración unificada y constantes del sistema Swing Sniper & Grid Desk.
Única fuente de verdad para parámetros, comisiones, rutas y calibración cuantitativa.
"""
import os
import sys
import ccxt

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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SWING_LOGS_DIR = os.path.join(BASE_DIR, "swing_logs", "paper")
SWING_DIR = SWING_LOGS_DIR
os.makedirs(SWING_LOGS_DIR, exist_ok=True)
SWING_DB_FILE = os.path.join(SWING_LOGS_DIR, "swing_vault.db")
SWING_STATE_FILE = os.path.join(SWING_LOGS_DIR, "swing_state.json")

# Parámetros Operativos
PAPER_INITIAL_CAPITAL = 70.00

# Parámetros de Red y Servidor
SWING_HTTP_PORT = 8900
REAL_GRID_CACHE_TTL = 30  # segundos
REAL_DOGE_GRID_BOT_ID = "215617258385481728"

# Comisiones y Asignación de Capital
FEE_RATE = 0.00075  # 0.075% Binance Spot con BNB / standard
MAX_CONCURRENT_TRADES = 1  # 1 trade simultáneo para cuentas < $120 USDT

# Filtros de Escáner de Mercado
RS_MIN_THRESHOLD = 1.0
MIN_VOLUME_USDT = 3_000_000  # $3M mínimo para evitar iliquidez
IGNORE_SYMBOLS = [
    "USDC/USDT", "FDUSD/USDT", "TUSD/USDT", "EUR/USDT", "BUSD/USDT",
    "USDP/USDT", "AEUR/USDT"
]

# Calibración Cuantitativa por Defecto (Opción B: Asimetría con Oxígeno)
DEFAULT_SETTINGS = {
    "auto_atr_mode": True,               # Modo Automático ATR ON/OFF
    "be_trigger_pct": 0.016,             # +1.60% activa Break-Even
    "be_stop_pct": 0.0020,               # +0.20% asegura comisiones en BE
    "stop_atr_mult": 1.2,                # Stop Loss: Multiplicador ATR base
    "target_atr_mult": 3.0,              # Target: 3.0x ATR 15m (R:R ~ 2.5:1)
    "trail_distance_atr": 1.5,           # Trailing holgado 1.5x ATR (Oxígeno para buscar +3.0x)
    "min_score": 70.0,                   # Score mínimo base
    "vol_spike_min": 1.2,                # Pico de volumen mínimo (1.2x media)
    "post_stop_cooldown_s": 180,         # Cooldown base tras stop
    "post_stop_extra_score": 15.0        # Penalización temporal tras stop
}

# Constantes Derivadas
MIN_SCORE_V2 = DEFAULT_SETTINGS["min_score"]
POST_STOP_COOLDOWN_S = DEFAULT_SETTINGS["post_stop_cooldown_s"]
POST_STOP_EXTRA_SCORE = DEFAULT_SETTINGS["post_stop_extra_score"]
TRAIL_TRIGGER_ATR = 1.8
TRAIL_DISTANCE_ATR = DEFAULT_SETTINGS["trail_distance_atr"]

# Instancia Global de CCXT Binance
exchange = ccxt.binance({
    "enableRateLimit": True,
    "options": {"defaultType": "spot"}
})
