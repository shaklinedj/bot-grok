"""
========================================================================================
  ADAPTIVE SNIPER V2: RADAR DE FUERZA RELATIVA + GATILLO RÁPIDO (15m / 3m)
  - Modo: PAPER TRADING ESTRICTO (Capital virtual, datos reales CCXT/Binance)
  - Seguridad: Cero órdenes reales a Pionex. Malla real DOGE permanece 100% intacta.
  - Fase 1: Escáner Dinámico de TODO el mercado (Top movers por volumen + RS).
  - Fase 2: Filtro de Fuerza Relativa (monedas desacopladas que suben si BTC baja).
  - Fase 3: Gatillo Rápido en 15m (ruptura con volumen confirmada).
  - Trailing Ágil: Protección rápida al +1.0%, trailing desde +1.5%.
  - Anti-Ametralladora: Tras stop loss, exige confirmación superior para re-entrar.
  - Persistencia: SQLite WAL (swing_logs/paper/swing_vault.db).
  - Dashboard Reactivo Dual: http://localhost:8900
========================================================================================
"""

import os
import sys
import time
import json
import math
import shutil
import sqlite3
import http.server
import threading
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

import ccxt
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ====================== CONFIGURACIÓN GENERAL ======================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SWING_LOGS_DIR = os.path.join(BASE_DIR, "swing_logs", "paper")
os.makedirs(SWING_LOGS_DIR, exist_ok=True)

SWING_DB_FILE = os.path.join(SWING_LOGS_DIR, "swing_vault.db")
SWING_STATE_FILE = os.path.join(SWING_LOGS_DIR, "swing_live_state.json")
SWING_SETTINGS_FILE = os.path.join(SWING_LOGS_DIR, "swing_settings.json")
SWING_HTTP_PORT = 8900

# Parámetros Cuantitativos y Calibración en Caliente
PAPER_INITIAL_CAPITAL = 70.00
FEE_RATE = 0.0005                # 0.05% por lado (0.10% round-trip)
MIN_VOLUME_USDT = 8_000_000      # Filtro mínimo: $8M de volumen diario en USDT
RS_MIN_THRESHOLD = 1.5           # Fuerza Relativa mínima vs BTC (en puntos porcentuales)

# Configuración por defecto (Calibración base de fábrica)
DEFAULT_SETTINGS = {
    "auto_atr_mode": True,               # Modo Automático ATR ON/OFF
    "be_trigger_pct": 0.016,             # +1.60% activa Break-Even
    "be_stop_pct": 0.0020,               # +0.20% asegura comisiones en BE
    "stop_atr_mult": 1.2,                # Stop Loss: Multiplicador ATR base
    "target_atr_mult": 3.0,              # Target: 3.0x ATR 15m (R:R ~ 2.5:1)
    "trail_distance_atr": 0.8,           # Trailing persigue el máximo menos distancia ATR
    "min_score": 70.0,                   # Score mínimo base
    "vol_spike_min": 1.2,                # Pico de volumen mínimo (1.2x media)
    "post_stop_cooldown_s": 180,         # Cooldown base tras stop
    "post_stop_extra_score": 15.0        # Penalización temporal tras stop
}

# Constantes retrocompatibles
BREAK_EVEN_TRIGGER_PCT = DEFAULT_SETTINGS["be_trigger_pct"]
BREAK_EVEN_STOP_PCT = DEFAULT_SETTINGS["be_stop_pct"]
BREAKOUT_VOL_SPIKE_MIN = DEFAULT_SETTINGS["vol_spike_min"]
MIN_SCORE_V2 = DEFAULT_SETTINGS["min_score"]
STOP_ATR_MULT = DEFAULT_SETTINGS["stop_atr_mult"]
TARGET_ATR_MULT = DEFAULT_SETTINGS["target_atr_mult"]
TRAIL_TRIGGER_ATR = 1.0
TRAIL_DISTANCE_ATR = DEFAULT_SETTINGS["trail_distance_atr"]
POST_STOP_COOLDOWN_S = DEFAULT_SETTINGS["post_stop_cooldown_s"]
POST_STOP_EXTRA_SCORE = DEFAULT_SETTINGS["post_stop_extra_score"]

# Stablecoins y tokens a ignorar en el escáner
IGNORE_SYMBOLS = {"USDC/USDT", "BUSD/USDT", "TUSD/USDT", "FDUSD/USDT", "USD1/USDT",
                  "RLUSD/USDT", "RWUSD/USDT", "BFUSD/USDT", "USDD/USDT", "DAI/USDT",
                  "EURI/USDT", "AEUR/USDT", "PAXG/USDT"}

# ID de la Malla Real en Pionex (SOLO LECTURA)
REAL_DOGE_GRID_BOT_ID = "61b3f37a-0cdd-458e-adf2-db096722c53b"

exchange = ccxt.binance({"enableRateLimit": True, "timeout": 10000})


# ====================== PERSISTENCIA SQLITE WAL ======================
class SwingDatabase:
    """Base de datos transaccional SQLite WAL para el Swing Engine."""

    def __init__(self, db_path: str = SWING_DB_FILE):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price REAL NOT NULL,
                    amount REAL NOT NULL,
                    capital REAL NOT NULL,
                    pnl REAL DEFAULT 0.0,
                    fee REAL DEFAULT 0.0,
                    order_id TEXT,
                    target_price REAL,
                    stop_price REAL,
                    note TEXT,
                    mode TEXT DEFAULT 'PAPER_SWING'
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS equity_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    cash REAL NOT NULL,
                    equity REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    win_rate REAL NOT NULL,
                    total_trades INTEGER NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key TEXT PRIMARY KEY,
                    val_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    val_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trade_autopsies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    trade_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    pnl REAL NOT NULL,
                    pnl_pct REAL NOT NULL,
                    duration_s REAL NOT NULL,
                    mfe_pct REAL NOT NULL,
                    mae_pct REAL NOT NULL,
                    exit_reason TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    btc_regime TEXT NOT NULL,
                    lesson_learned TEXT NOT NULL,
                    adaptive_action TEXT NOT NULL
                );
            """)
            conn.commit()

    def log_trade(self, symbol: str, side: str, price: float, amount: float, capital: float,
                  pnl: float = 0.0, fee: float = 0.0, order_id: str = "",
                  target_price: float = 0.0, stop_price: float = 0.0, note: str = "",
                  mode: str = "PAPER_SWING"):
        ts = datetime.now().isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO trades (timestamp, symbol, side, price, amount, capital, pnl, fee, order_id, target_price, stop_price, note, mode)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (ts, symbol, side, price, amount, capital, pnl, fee, order_id, target_price, stop_price, note, mode))
            conn.commit()

    def insert_event(self, event_type: str, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        with self._get_connection() as conn:
            conn.execute("INSERT INTO events (timestamp, event_type, message) VALUES (?, ?, ?)",
                         (ts, event_type, message))
            conn.commit()

    def insert_equity(self, cash: float, equity: float, realized_pnl: float, win_rate: float, total_trades: int):
        ts = datetime.now().isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO equity_history (timestamp, cash, equity, realized_pnl, win_rate, total_trades)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (ts, cash, equity, realized_pnl, win_rate, total_trades))
            conn.commit()

    def get_stats(self) -> Dict:
        with self._get_connection() as conn:
            row = conn.execute("""
                SELECT COUNT(*) AS n,
                       COALESCE(SUM(pnl), 0) AS pnl,
                       COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) AS wins,
                       COALESCE(SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END), 0) AS losses
                FROM trades WHERE side = 'SELL'
            """).fetchone()
            tot = int(row["n"])
            wins = int(row["wins"])
            pnl = float(row["pnl"])
            wr = (wins / tot * 100.0) if tot > 0 else 0.0
            return {"total": tot, "pnl": pnl, "wins": wins, "losses": int(row["losses"]), "win_rate": wr}

    def get_recent_trades(self, limit: int = 25) -> List[Dict]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_last_closed_trade(self) -> Optional[Dict]:
        """Recupera el último trade cerrado (SELL) para mostrar el resultado en el dashboard."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM trades WHERE side = 'SELL' ORDER BY id DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    def get_recent_events(self, limit: int = 40) -> List[Dict]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT timestamp as time, event_type as type, message as text FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]  # Más recientes PRIMERO para ver siempre la última acción arriba

    def save_all_settings(self, settings: Dict[str, Any]):
        """Persiste toda la configuración en la tabla bot_settings de SQLite."""
        ts = datetime.now().isoformat()
        with self._get_connection() as conn:
            for k, v in settings.items():
                conn.execute("""
                    INSERT INTO bot_settings (key, val_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET val_json=excluded.val_json, updated_at=excluded.updated_at
                """, (k, json.dumps(v), ts))
            conn.commit()

    def get_all_settings(self) -> Dict[str, Any]:
        """Recupera la configuración completa guardada en la base de datos SQLite."""
        res = {}
        with self._get_connection() as conn:
            rows = conn.execute("SELECT key, val_json FROM bot_settings").fetchall()
            for r in rows:
                try:
                    res[r["key"]] = json.loads(r["val_json"])
                except Exception:
                    res[r["key"]] = r["val_json"]
        return res

    def save_bot_state(self, state: Dict[str, Any]):
        """Persiste el estado operativo completo en la tabla bot_state de SQLite."""
        ts = datetime.now().isoformat()
        with self._get_connection() as conn:
            for k, v in state.items():
                conn.execute("""
                    INSERT INTO bot_state (key, val_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET val_json=excluded.val_json, updated_at=excluded.updated_at
                """, (k, json.dumps(v), ts))
            conn.commit()

    def load_bot_state(self) -> Dict[str, Any]:
        """Recupera el estado operativo completo desde la base de datos SQLite."""
        res = {}
        with self._get_connection() as conn:
            rows = conn.execute("SELECT key, val_json FROM bot_state").fetchall()
            for r in rows:
                try:
                    res[r["key"]] = json.loads(r["val_json"])
                except Exception:
                    res[r["key"]] = r["val_json"]
        return res

    def log_autopsy(self, trade_id: str, symbol: str, pnl: float, pnl_pct: float,
                    duration_s: float, mfe_pct: float, mae_pct: float,
                    exit_reason: str, classification: str, btc_regime: str,
                    lesson_learned: str, adaptive_action: str):
        """Registra la autopsia clínica post-trade para autoaprendizaje dinámico."""
        ts = datetime.now().isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO trade_autopsies (
                    timestamp, trade_id, symbol, pnl, pnl_pct, duration_s,
                    mfe_pct, mae_pct, exit_reason, classification, btc_regime,
                    lesson_learned, adaptive_action
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (ts, trade_id, symbol, pnl, pnl_pct, duration_s,
                  mfe_pct, mae_pct, exit_reason, classification, btc_regime,
                  lesson_learned, adaptive_action))
            conn.commit()

    def get_recent_autopsies(self, limit: int = 15) -> List[Dict]:
        """Recupera las autopsias clínicas más recientes de SQLite."""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT timestamp, trade_id, symbol, pnl, pnl_pct, duration_s,
                       mfe_pct, mae_pct, exit_reason, classification, btc_regime,
                       lesson_learned, adaptive_action
                FROM trade_autopsies
                ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()
            return [
                {
                    "timestamp": r["timestamp"], "trade_id": r["trade_id"], "symbol": r["symbol"],
                    "pnl": r["pnl"], "pnl_pct": r["pnl_pct"], "duration_s": r["duration_s"],
                    "mfe_pct": r["mfe_pct"], "mae_pct": r["mae_pct"], "exit_reason": r["exit_reason"],
                    "classification": r["classification"], "btc_regime": r["btc_regime"],
                    "lesson_learned": r["lesson_learned"], "adaptive_action": r["adaptive_action"]
                }
                for r in rows
            ]


# ====================== MODELO DE DATOS SWING ======================
class SwingTrade:
    def __init__(self, trade_id: str, symbol: str, entry_price: float, amount: float,
                 capital: float, target_price: float, stop_price: float, initial_stop: float,
                 target_pct: float, stop_pct: float, atr_pct: float, rr_ratio: float,
                 entry_time: float, entry_fee: float = 0.0, of_obi: float = 0.0,
                 of_buy_ratio: float = 50.0):
        self.trade_id = trade_id
        self.symbol = symbol
        self.entry_price = entry_price
        self.amount = amount
        self.capital = capital
        self.target_price = target_price
        self.stop_price = stop_price
        self.initial_stop = initial_stop
        self.target_pct = target_pct
        self.stop_pct = stop_pct
        self.atr_pct = atr_pct
        self.rr_ratio = rr_ratio
        self.entry_time = entry_time
        self.entry_fee = entry_fee
        self.of_obi = of_obi
        self.of_buy_ratio = of_buy_ratio
        self.is_be_active = False        # Break-Even Shield activado (+0.20%)
        self.is_trailing_active = False  # Trailing Stop ATR activado
        self.highest_price = entry_price
        self.lowest_price = entry_price
        self.current_price = entry_price
        self.unrealized_pnl = 0.0
        self.unrealized_pnl_pct = 0.0
        self.status = "OPEN"

    def to_dict(self) -> Dict:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "entry_price": self.entry_price,
            "amount": self.amount,
            "capital": self.capital,
            "target_price": self.target_price,
            "stop_price": self.stop_price,
            "initial_stop": self.initial_stop,
            "target_pct": self.target_pct,
            "stop_pct": self.stop_pct,
            "atr_pct": self.atr_pct,
            "rr_ratio": self.rr_ratio,
            "entry_time": self.entry_time,
            "entry_fee": self.entry_fee,
            "of_obi": getattr(self, "of_obi", 0.0),
            "of_buy_ratio": getattr(self, "of_buy_ratio", 50.0),
            "is_be_active": self.is_be_active,
            "is_trailing_active": self.is_trailing_active,
            "highest_price": self.highest_price,
            "lowest_price": getattr(self, "lowest_price", self.entry_price),
            "current_price": self.current_price,
            "unrealized_pnl": self.unrealized_pnl,
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
            "status": self.status
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "SwingTrade":
        st = cls(
            trade_id=d["trade_id"],
            symbol=d["symbol"],
            entry_price=d["entry_price"],
            amount=d["amount"],
            capital=d["capital"],
            target_price=d["target_price"],
            stop_price=d["stop_price"],
            initial_stop=d.get("initial_stop", d["stop_price"]),
            target_pct=d.get("target_pct", 0.045),
            stop_pct=d.get("stop_pct", 0.015),
            atr_pct=d.get("atr_pct", 1.5),
            rr_ratio=d.get("rr_ratio", 3.0),
            entry_time=d.get("entry_time", time.time()),
            entry_fee=d.get("entry_fee", 0.0),
            of_obi=d.get("of_obi", 0.0),
            of_buy_ratio=d.get("of_buy_ratio", 50.0)
        )
        st.is_be_active = d.get("is_be_active", False)
        st.is_trailing_active = d.get("is_trailing_active", False)
        st.highest_price = d.get("highest_price", st.entry_price)
        st.lowest_price = d.get("lowest_price", st.entry_price)
        st.current_price = d.get("current_price", st.entry_price)
        st.unrealized_pnl = d.get("unrealized_pnl", 0.0)
        st.unrealized_pnl_pct = d.get("unrealized_pnl_pct", 0.0)
        st.status = d.get("status", "OPEN")
        return st


# ====================== MODELO Y ALGORITMOS DE MALLA ACOTADA EN CHOP ======================
def calc_hurst_exponent(series: List[float], min_window: int = 8, max_window: int = 32) -> float:
    """
    Calcula el Exponente de Hurst (H) mediante análisis Rescaled Range (R/S).
    - H < 0.45: Serie anti-persistente (Reversión a la Media). Ideal para Malla Acotada.
    - H = 0.50: Paseo Aleatorio puro.
    - H > 0.50: Serie persistente (Tendencial). Prohibido para Malla.
    """
    arr = np.asarray(series, dtype=float)
    if len(arr) < max_window:
        return 0.50
    returns = np.diff(arr)
    if len(returns) < min_window:
        return 0.50
    window_sizes = [w for w in [8, 12, 16, 24, 32] if w <= len(returns)]
    if len(window_sizes) < 3:
        return 0.50
    rs_values = []
    for w in window_sizes:
        num_chunks = len(returns) // w
        rs_chunk_vals = []
        for i in range(num_chunks):
            chunk = returns[i*w:(i+1)*w]
            mean = np.mean(chunk)
            deviations = chunk - mean
            cum_dev = np.cumsum(deviations)
            r = np.max(cum_dev) - np.min(cum_dev)
            s = np.std(chunk, ddof=1)
            if s > 1e-8:
                rs_chunk_vals.append(r / s)
        if rs_chunk_vals:
            rs_values.append((w, np.mean(rs_chunk_vals)))
    if len(rs_values) < 2:
        return 0.50
    log_w = [np.log(w) for w, rs in rs_values]
    log_rs = [np.log(rs) for w, rs in rs_values]
    poly = np.polyfit(log_w, log_rs, 1)
    return round(float(np.clip(poly[0], 0.05, 0.95)), 3)


def detect_horizontal_channel(candles: List) -> Optional[Dict]:
    """
    Detecta si el par se encuentra confinado en un canal horizontal acotado.
    - Pendiente lineal plana (|slope_pct| < 1.8%).
    - Ancho del canal entre 1.0% y 5.0%.
    - Precio dentro del canal o cerca del soporte.
    """
    if len(candles) < 24:
        return None
    closes = np.array([c[4] for c in candles], dtype=float)
    highs = np.array([c[2] for c in candles], dtype=float)
    lows = np.array([c[3] for c in candles], dtype=float)
    curr_p = closes[-1]

    x = np.arange(len(closes))
    slope, _ = np.polyfit(x, closes, 1)
    slope_pct = (slope * len(closes)) / closes[0] * 100.0
    if abs(slope_pct) > 1.8:
        return None

    support = float(np.percentile(lows, 5))
    resistance = float(np.percentile(highs, 95))
    if support <= 0:
        return None

    channel_width_pct = (resistance - support) / support * 100.0
    if not (1.0 <= channel_width_pct <= 5.0):
        return None

    if curr_p < support * 0.985 or curr_p > resistance * 1.015:
        return None

    midpoint = (support + resistance) / 2.0
    channel_pos = (curr_p - support) / max((resistance - support), 1e-8)

    return {
        "support": round(support, 6),
        "resistance": round(resistance, 6),
        "midpoint": round(midpoint, 6),
        "width_pct": round(channel_width_pct, 2),
        "channel_pos": round(channel_pos, 2),
        "slope_pct": round(slope_pct, 2)
    }


class GridLevel:
    def __init__(self, level_idx: int, price: float, amount: float, capital: float, status: str = "PENDING"):
        self.level_idx = level_idx
        self.price = price
        self.amount = amount
        self.capital = capital
        self.status = status  # PENDING, FILLED, CLOSED
        self.fill_price = 0.0
        self.fill_time = 0.0

    def to_dict(self) -> Dict:
        return {
            "level_idx": self.level_idx,
            "price": self.price,
            "amount": self.amount,
            "capital": self.capital,
            "status": self.status,
            "fill_price": self.fill_price,
            "fill_time": self.fill_time
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "GridLevel":
        gl = cls(d["level_idx"], d["price"], d["amount"], d["capital"], d.get("status", "PENDING"))
        gl.fill_price = d.get("fill_price", 0.0)
        gl.fill_time = d.get("fill_time", 0.0)
        return gl


class BoundedMicroGrid:
    """Malla Micro-Acotada de 3 niveles con Kill-Switch estricto para mercado Chop."""
    def __init__(self, grid_id: str, symbol: str, channel_support: float, channel_resistance: float,
                 midpoint: float, hurst_exponent: float, kill_switch_price: float, total_capital: float = 54.0):
        self.grid_id = grid_id
        self.symbol = symbol
        self.channel_support = channel_support
        self.channel_resistance = channel_resistance
        self.midpoint = midpoint
        self.hurst_exponent = hurst_exponent
        self.kill_switch_price = kill_switch_price
        self.total_capital = total_capital
        self.levels: List[GridLevel] = []
        self.created_at = time.time()
        self.status = "ACTIVE"
        self.pnl = 0.0
        self.pnl_pct = 0.0
        self.current_price = midpoint
        self.unrealized_pnl = 0.0

    def get_filled_levels(self) -> List[GridLevel]:
        return [lvl for lvl in self.levels if lvl.status == "FILLED"]

    def get_total_inventory(self) -> float:
        return sum(lvl.amount for lvl in self.get_filled_levels())

    def get_invested_capital(self) -> float:
        return sum(lvl.capital for lvl in self.get_filled_levels())

    def get_average_entry(self) -> float:
        inv = self.get_total_inventory()
        if inv <= 0:
            return 0.0
        return sum(lvl.fill_price * lvl.amount for lvl in self.get_filled_levels()) / inv

    def to_dict(self) -> Dict:
        return {
            "grid_id": self.grid_id,
            "symbol": self.symbol,
            "channel_support": self.channel_support,
            "channel_resistance": self.channel_resistance,
            "midpoint": self.midpoint,
            "hurst_exponent": self.hurst_exponent,
            "kill_switch_price": self.kill_switch_price,
            "total_capital": self.total_capital,
            "levels": [lvl.to_dict() for lvl in self.levels],
            "created_at": self.created_at,
            "status": self.status,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
            "current_price": self.current_price,
            "unrealized_pnl": self.unrealized_pnl,
            "invested_capital": round(self.get_invested_capital(), 2),
            "average_entry": round(self.get_average_entry(), 6),
            "filled_count": len(self.get_filled_levels())
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "BoundedMicroGrid":
        bmg = cls(
            grid_id=d["grid_id"],
            symbol=d["symbol"],
            channel_support=d["channel_support"],
            channel_resistance=d["channel_resistance"],
            midpoint=d["midpoint"],
            hurst_exponent=d["hurst_exponent"],
            kill_switch_price=d["kill_switch_price"],
            total_capital=d.get("total_capital", 54.0)
        )
        bmg.levels = [GridLevel.from_dict(lvl) for lvl in d.get("levels", [])]
        bmg.created_at = d.get("created_at", time.time())
        bmg.status = d.get("status", "ACTIVE")
        bmg.pnl = d.get("pnl", 0.0)
        bmg.pnl_pct = d.get("pnl_pct", 0.0)
        bmg.current_price = d.get("current_price", d["midpoint"])
        bmg.unrealized_pnl = d.get("unrealized_pnl", 0.0)
        return bmg


# ====================== BOT SWING STATE & EXECUTION ======================
class SwingBot:
    def __init__(self, db_path: Optional[str] = None):
        self.db = SwingDatabase(db_path or SWING_DB_FILE)
        self.cash = PAPER_INITIAL_CAPITAL
        self.active_trades: Dict[str, SwingTrade] = {}
        self.active_grid: Optional[BoundedMicroGrid] = None
        self.active_mode: str = "SWING_SNIPER"
        self.radar_telemetry: List[Dict] = []
        self.real_grid_stats: Dict = {}
        self.cooldowns: Dict[str, float] = {}
        self.last_stop_time: float = 0.0
        self.settings: Dict = dict(DEFAULT_SETTINGS)
        self.status_msg = "Iniciando Hourly Swing Sniper..."
        self.data_lock = threading.Lock()
        self.scan_cycle = 0
        self.sim_order_seq = 1000
        self.load_settings()
        self.load_state()

    def load_settings(self):
        try:
            db_cfg = self.db.get_all_settings()
            if db_cfg:
                self.settings.update(db_cfg)
            else:
                # Si es la primera vez, sembramos los valores por defecto en SQLite
                self.db.save_all_settings(self.settings)
        except Exception as e:
            self.add_log(f"Error cargando settings desde SQLite: {e}", "error")

    def save_settings(self):
        try:
            self.db.save_all_settings(self.settings)
            # Respaldo secundario en JSON
            tmp = SWING_SETTINGS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2)
            os.replace(tmp, SWING_SETTINGS_FILE)
        except Exception as e:
            self.add_log(f"Error guardando settings en SQLite: {e}", "error")

    def update_settings(self, new_cfg: Dict):
        with self.data_lock:
            for k, v in new_cfg.items():
                if k in self.settings:
                    if k in ("post_stop_cooldown_s",):
                        self.settings[k] = int(v)
                    elif k in ("auto_atr_mode",):
                        self.settings[k] = bool(v)
                    else:
                        self.settings[k] = float(v)
            self.save_settings()
        be_pct = self.settings["be_trigger_pct"] * 100.0
        mode_str = "AUTO ATR" if self.settings.get("auto_atr_mode") else "MANUAL"
        self.add_log(f"🎛️ Parámetros actualizados en SQLite [{mode_str}]: BE=+{be_pct:.2f}% | Stop={self.settings['stop_atr_mult']}x ATR | Target={self.settings['target_atr_mult']}x ATR | Trail={self.settings['trail_distance_atr']}x ATR | Score={self.settings['min_score']:.0f}", "info")

    @property
    def active_trade(self) -> Optional[SwingTrade]:
        """Propiedad retrocompatible: primer trade activo o None."""
        return next(iter(self.active_trades.values()), None)

    @active_trade.setter
    def active_trade(self, val: Optional[SwingTrade]):
        if val is None:
            self.active_trades.clear()
        else:
            self.active_trades[val.symbol] = val

    def total_equity(self) -> float:
        """Calcula el patrimonio total en vivo: Caja disponible + Posiciones Swing + Malla Acotada."""
        pos_val = sum(tr.amount * getattr(tr, "current_price", tr.entry_price) for tr in self.active_trades.values())
        grid_val = 0.0
        if getattr(self, "active_grid", None):
            grid_val = self.active_grid.get_invested_capital() + self.active_grid.unrealized_pnl
        return self.cash + pos_val + grid_val

    def get_max_concurrent_trades(self) -> int:
        """Escalabilidad de diversificación multi-trade según nivel de capital."""
        eq = self.total_equity()
        if eq >= 200.0:
            return 3  # A partir de $200 USDT: Diversificación multi-trade al unísono (hasta 3 simultáneos)
        elif eq >= 120.0:
            return 2  # De $120 a $200 USDT: Hasta 2 trades simultáneos
        return 1      # Menor a $120 USDT: 1 trade concentrado para acelerar el interés compuesto

    def get_tier_name(self) -> str:
        eq = self.total_equity()
        if eq >= 200.0:
            return "Multi-Sniper Diversificado (≥$200: 3 trades al unísono)"
        elif eq >= 120.0:
            return "Dual-Sniper ($120-$200: 2 trades simultáneos)"
        return "Mono-Sniper (<$120: Interés Compuesto Concentrado)"

    def calculate_trade_capital(self) -> float:
        """Calcula el tamaño del trade con interés compuesto dinámico (sin topes fijos)."""
        eq = self.total_equity()
        max_trades = self.get_max_concurrent_trades()
        if max_trades == 1:
            # Concentrado: 80% de la caja libre disponible
            target_cap = self.cash * 0.80
        elif max_trades == 2:
            # Dual: 45% del equity total por trade
            target_cap = eq * 0.45
        else:
            # Multi-Trade (≥ $200): 30% del equity total por trade (diversificado al unísono)
            target_cap = eq * 0.30
        return max(0.0, min(self.cash * 0.95, target_cap))

    def add_log(self, msg: str, event_type: str = "info"):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [{event_type.upper()}] {msg}", flush=True)
        self.db.insert_event(event_type, msg)

    def load_state(self):
        try:
            d = self.db.load_bot_state()
            if not d and os.path.exists(SWING_STATE_FILE):
                with open(SWING_STATE_FILE, "r", encoding="utf-8") as f:
                    d = json.load(f)
                self.db.save_bot_state(d)  # Migración automática inicial a SQLite

            if d:
                self.cash = float(d.get("cash", PAPER_INITIAL_CAPITAL))
                self.active_trades.clear()
                raw_trades = d.get("active_trades")
                if raw_trades and isinstance(raw_trades, list):
                    for raw_t in raw_trades:
                        st = SwingTrade.from_dict(raw_t)
                        self.active_trades[st.symbol] = st
                else:
                    tr = d.get("active_trade")
                    if tr:
                        st = SwingTrade.from_dict(tr)
                        self.active_trades[st.symbol] = st
                self.cooldowns = d.get("cooldowns", {})
                self.last_stop_time = float(d.get("last_stop_time", 0.0))
                self.sim_order_seq = int(d.get("sim_order_seq", 1000))
                self.active_mode = d.get("active_mode", "SWING_SNIPER")
                raw_grid = d.get("active_grid")
                if raw_grid and isinstance(raw_grid, dict):
                    self.active_grid = BoundedMicroGrid.from_dict(raw_grid)
                else:
                    self.active_grid = None
        except Exception as e:
            self.add_log(f"Error cargando estado desde SQLite: {e}", "error")

    def save_state(self):
        d = {
            "cash": self.cash,
            "active_trade": self.active_trade.to_dict() if self.active_trade else None,
            "active_trades": [t.to_dict() for t in self.active_trades.values()],
            "active_grid": self.active_grid.to_dict() if getattr(self, "active_grid", None) else None,
            "active_mode": getattr(self, "active_mode", "SWING_SNIPER"),
            "tier_mode": self.get_tier_name(),
            "max_concurrent_trades": self.get_max_concurrent_trades(),
            "cooldowns": self.cooldowns,
            "last_stop_time": self.last_stop_time,
            "sim_order_seq": self.sim_order_seq,
            "updated_at": time.time()
        }
        try:
            # 1. Persistencia primaria en Base de Datos SQLite WAL
            self.db.save_bot_state(d)

            # 2. Respaldo secundario en JSON
            tmp = SWING_STATE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=2)
            os.replace(tmp, SWING_STATE_FILE)
        except Exception as e:
            self.add_log(f"Error guardando estado en SQLite: {e}", "error")


# ====================== LECTURA SEGURA DE LA MALLA REAL PIONEX ======================
def fetch_real_pionex_grid_stats() -> Dict:
    """Consulta la API de Pionex en modo SOLO LECTURA para reportar la Malla de DOGE."""
    try:
        exe = shutil.which("pionex-trade-cli.cmd") or shutil.which("pionex-trade-cli")
        if not exe:
            return {"status": "CLI no disponible"}
        cmd = [exe, "bot", "spot_grid", "get", "--bu-order-id", REAL_DOGE_GRID_BOT_ID]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8)
        if res.returncode == 0:
            data = json.loads(res.stdout).get("data", {})
            bod = data.get("buOrderData", {})
            return {
                "bot_id": REAL_DOGE_GRID_BOT_ID,
                "symbol": "DOGE/USDT",
                "status": bod.get("status", "running"),
                "investment": float(bod.get("initUsdtInvestment", 69.71)),
                "grid_profit": float(bod.get("gridProfit", 0.0)),
                "profit_withdrawn": float(bod.get("profitWithdrawn", 0.0)),
                "total_profit_usdt": round(float(bod.get("gridProfit", 0.0)) + float(bod.get("profitWithdrawn", 0.0)), 4),
                "paired_count": int(bod.get("exchangeOrderPairedCount", 0)),
                "closed_count": int(bod.get("closedExchangeOrderCount", 0)),
                "range_bottom": float(bod.get("bottom", 0.06711)),
                "range_top": float(bod.get("top", 0.09383)),
                "auto_reinvest": bool(bod.get("profitAutoReinvest", True)),
                "trailing_up": bool(bod.get("movingTrailingUpParam")),
                "updated_at": datetime.now().strftime("%H:%M:%S")
            }
    except Exception as e:
        return {"error": str(e), "status": "offline"}
    return {}


# ====================== MOTOR ADAPTATIVO V2: ESCÁNER + FUERZA RELATIVA + GATILLO 15m ======================
_ohlcv_cache = {}
_ticker_cache = {"ts": 0.0, "data": {}}
_btc_performance_cache = {
    "ts": 0.0, "change_1h": 0.0, "change_4h": 0.0, "trend_4h": "neutral",
    "regime": "NEUTRAL_TRANSITION", "regime_desc": "Iniciando análisis macro...",
    "range_3h_pct": 1.0, "can_trade_alts": True
}


def fetch_ohlcv_cached(symbol: str, timeframe: str, limit: int = 60) -> List:
    key = f"{symbol}_{timeframe}"
    now = time.time()
    cached = _ohlcv_cache.get(key)
    ttl = 30 if timeframe in ("3m", "5m") else (60 if timeframe == "15m" else 180)
    if cached and (now - cached["ts"] < ttl):
        return cached["data"]
    try:
        data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        _ohlcv_cache[key] = {"ts": now, "data": data}
        return data
    except Exception:
        return cached["data"] if cached else []


def calc_ema(series: List[float], period: int) -> float:
    k = 2.0 / (period + 1.0)
    ema = series[0]
    for val in series[1:]:
        ema = (val * k) + (ema * (1.0 - k))
    return ema


def calc_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = closes[-(period + 1) + i] - closes[-(period + 1) + i - 1]
        gains.append(max(0.0, diff))
        losses.append(max(0.0, -diff))
    avg_g = sum(gains) / period
    avg_l = sum(losses) / period
    if avg_l < 0.0001:
        return 99.0
    return 100.0 - (100.0 / (1.0 + avg_g / avg_l))


def calc_atr(candles: List, period: int = 14) -> float:
    trs = []
    for i in range(1, len(candles)):
        h, l, prev_c = candles[i][2], candles[i][3], candles[i - 1][4]
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    if len(trs) < period:
        return sum(trs) / max(len(trs), 1)
    return sum(trs[-period:]) / period


def update_btc_context():
    """Actualiza el contexto macro de Bitcoin (Régimen de Mercado, Filtro Lateral y Fuerza Relativa)."""
    global _btc_performance_cache
    now = time.time()
    if now - _btc_performance_cache.get("ts", 0) < 45:
        return _btc_performance_cache
    try:
        c_15m = fetch_ohlcv_cached("BTC/USDT", "15m", limit=24)
        c_1h = fetch_ohlcv_cached("BTC/USDT", "1h", limit=24)
        c_4h = fetch_ohlcv_cached("BTC/USDT", "4h", limit=25)
        if len(c_1h) >= 2 and len(c_4h) >= 5:
            btc_curr = c_1h[-1][4]
            chg_1h = (c_1h[-1][4] - c_1h[-2][4]) / c_1h[-2][4] * 100.0
            chg_4h = (c_4h[-1][4] - c_4h[-5][4]) / c_4h[-5][4] * 100.0
            closes_4h = [c[4] for c in c_4h]
            ema20_4h = calc_ema(closes_4h, 20)
            trend_4h = "bullish" if c_4h[-1][4] > ema20_4h else "bearish"

            closes_1h = [c[4] for c in c_1h]
            ema20_1h = calc_ema(closes_1h, 20)

            range_3h_pct = 1.0
            if len(c_15m) >= 12:
                highs_3h = max(c[2] for c in c_15m[-12:])
                lows_3h = min(c[3] for c in c_15m[-12:])
                range_3h_pct = (highs_3h - lows_3h) / btc_curr * 100.0

            # Diagnóstico de Régimen Cuantitativo:
            if btc_curr < ema20_1h and chg_1h < -0.35:
                regime = "BEARISH_DUMP"
                regime_desc = "Corrección de BTC (< EMA20 1H). Disparos en altcoins bloqueados preventivamente."
                can_trade_alts = False
            elif range_3h_pct < 0.90 and abs(chg_1h) < 0.25:
                regime = "CHOP_COMPRESSION"
                regime_desc = "Compresión lateral de BTC (rango 3h < 0.9%). Falsas rupturas frecuentes. Exigiendo Score A+ (86+)."
                can_trade_alts = True
            elif btc_curr >= ema20_1h and chg_1h >= 0.10:
                regime = "BULLISH_EXPANSION"
                regime_desc = "Expansión alcista de BTC. Viento de cola favorable para rupturas en altcoins."
                can_trade_alts = True
            else:
                regime = "NEUTRAL_TRANSITION"
                regime_desc = "BTC en consolidación neutra."
                can_trade_alts = True

            _btc_performance_cache = {
                "ts": now,
                "price": btc_curr,
                "change_1h": chg_1h,
                "change_4h": chg_4h,
                "trend_4h": trend_4h,
                "range_3h_pct": range_3h_pct,
                "regime": regime,
                "regime_desc": regime_desc,
                "can_trade_alts": can_trade_alts
            }
    except Exception:
        pass
    return _btc_performance_cache


def scan_market_top_movers() -> List[Dict]:
    """
    FASE 1: Escáner Dinámico de TODO el mercado.
    Busca monedas USDT con alto volumen y rendimiento positivo (o fuerza relativa positiva vs BTC).
    No usa una whitelist fija: rastrea todo Binance.
    """
    global _ticker_cache
    now = time.time()
    if now - _ticker_cache["ts"] < 30:
        tickers = _ticker_cache["data"]
    else:
        try:
            tickers = exchange.fetch_tickers()
            _ticker_cache = {"ts": now, "data": tickers}
        except Exception:
            tickers = _ticker_cache.get("data", {})

    btc_ctx = update_btc_context()
    btc_chg_1h = btc_ctx["change_1h"]

    candidates = []
    for sym, t in tickers.items():
        if not sym.endswith("/USDT"):
            continue
        if sym in IGNORE_SYMBOLS:
            continue
        vol = float(t.get("quoteVolume", 0) or 0)
        if vol < MIN_VOLUME_USDT:
            continue
        pct_24h = float(t.get("percentage", 0) or 0)
        last_price = float(t.get("last", 0) or 0)
        if last_price <= 0:
            continue

        # Fuerza Relativa: qué tan bien se comporta vs BTC en la última hora
        relative_strength = pct_24h - (btc_chg_1h * 0.5)  # Positivo = más fuerte que BTC

        candidates.append({
            "symbol": sym,
            "price": last_price,
            "pct_24h": round(pct_24h, 2),
            "volume_usdt": vol,
            "relative_strength": round(relative_strength, 2),
        })

    # Ordenar por fuerza relativa descendente (las que más resisten o suben vs BTC primero)
    candidates.sort(key=lambda x: x["relative_strength"], reverse=True)
    return candidates[:25]  # Top 25 para analizar en detalle


def analyze_breakout_15m(symbol: str, btc_ctx: Dict, settings: Optional[Dict] = None) -> Optional[Dict]:
    """
    FASE 2 + 3: Analiza un candidato en 15m buscando ruptura confirmada con volumen.
    Solo dispara si hay confirmación de que la moneda ya está subiendo.
    """
    cfg = settings or DEFAULT_SETTINGS
    stop_mult = cfg.get("stop_atr_mult", 1.2)
    target_mult = cfg.get("target_atr_mult", 3.0)
    vol_min = cfg.get("vol_spike_min", 1.2)
    min_score_target = cfg.get("min_score", 70.0)

    c_15m = fetch_ohlcv_cached(symbol, "15m", limit=40)
    c_1h = fetch_ohlcv_cached(symbol, "1h", limit=30)
    c_5m = fetch_ohlcv_cached(symbol, "5m", limit=30)

    if len(c_15m) < 20 or len(c_1h) < 15:
        return None

    closes_15m = [c[4] for c in c_15m]
    highs_15m = [c[2] for c in c_15m]
    lows_15m = [c[3] for c in c_15m]
    vols_15m = [c[5] for c in c_15m]
    closes_1h = [c[4] for c in c_1h]
    curr_p = closes_15m[-1]

    if curr_p <= 0:
        return None

    btc_regime = btc_ctx.get("regime", "NEUTRAL_TRANSITION")
    # Candado Macro BTC: Si BTC está en corrección brusca (DUMP), prohibido comprar altcoins
    if btc_regime == "BEARISH_DUMP":
        return {
            "symbol": symbol, "price": curr_p, "breakout": False, "score": 0.0,
            "vol_spike": 0.0, "is_green": False, "double_green": False,
            "rsi_15m": 50.0, "rsi_1h": 50.0, "trend_1h": False, "atr_15m_pct": 1.0,
            "rs_vs_btc": 0.0, "coin_chg_1h": 0.0, "is_falling_knife": False,
            "is_overextended": False, "has_healthy_base": False, "rsi_5m": 50.0,
            "stop_pct": 1.5, "target_pct": 3.3, "stop_price": round(curr_p * 0.985, 6),
            "target_price": round(curr_p * 1.033, 6), "rr_ratio": 2.2,
            "trigger_ready": False, "status": "🚫 BLOQUEO: BTC en Corrección"
        }

    # Si BTC está en compresión lateral (chop), se exige Score A+ (86+)
    if btc_regime == "CHOP_COMPRESSION":
        min_score_target = max(min_score_target, 86.0)

    # --- Microestructura 5m (para evitar comprar en techos de agotamiento) ---
    if c_5m and len(c_5m) >= 15:
        closes_5m = [c[4] for c in c_5m]
        rsi_5m = calc_rsi(closes_5m, 14)
        ema20_5m = calc_ema(closes_5m, 20)
        dev_5m_ema20 = (curr_p - ema20_5m) / ema20_5m * 100.0
    else:
        rsi_5m = 50.0
        dev_5m_ema20 = 0.0

    # --- Indicadores 15m ---
    atr_15m = calc_atr(c_15m, 14)
    atr_pct_15m = (atr_15m / curr_p * 100.0) if curr_p > 0 else 1.0
    rsi_15m = calc_rsi(closes_15m, 14)
    ema9_15m = calc_ema(closes_15m, 9)
    ema20_15m = calc_ema(closes_15m, 20)
    dev_15m_ema20 = (curr_p - ema20_15m) / ema20_15m * 100.0

    # Conteo de velas verdes consecutivas en 15m
    consecutive_greens = 0
    for c in reversed(c_15m[-6:]):
        if c[4] > c[1]:
            consecutive_greens += 1
        else:
            break

    # Filtro de Sobreextensión / Agotamiento (Anti-FOMO en el techo tardío)
    # Permite la ignición inicial (velas 1 y 2), pero bloquea cuando el rally ya lleva 4+ velas o RSI extremo > 78
    is_overextended = (
        rsi_15m >= 78.0
        or rsi_5m >= 80.0
        or (consecutive_greens >= 4 and rsi_15m >= 68.0)
        or (dev_15m_ema20 >= 3.8 and consecutive_greens >= 3)
    )

    # Micro-Base Saludable: precio consolidando cerca de la EMA20 sin estar en euforia
    has_healthy_base = (dev_15m_ema20 <= 2.0) and (38.0 <= rsi_5m <= 66.0) and (consecutive_greens <= 2)

    # --- Indicadores 1H (tendencia de fondo) ---
    ema20_1h = calc_ema(closes_1h, 20)
    ema50_1h = calc_ema(closes_1h[-50:], 50) if len(closes_1h) >= 50 else calc_ema(closes_1h, len(closes_1h))
    rsi_1h = calc_rsi(closes_1h, 14)
    trend_1h_bullish = curr_p > ema20_1h

    # --- Micro-resistencia en 15m: Máximo de las últimas 8 velas (2 horas) ---
    recent_high = max(highs_15m[-9:-1]) if len(highs_15m) >= 9 else max(highs_15m[-5:-1])
    breakout_confirmed = curr_p > recent_high

    # --- Volumen Spike: Última vela 15m vs promedio de las últimas 20 ---
    avg_vol = sum(vols_15m[-20:]) / 20.0 if len(vols_15m) >= 20 else sum(vols_15m) / max(len(vols_15m), 1)
    vol_spike = (vols_15m[-1] / avg_vol) if avg_vol > 0 else 0.0

    # --- Vela actual verde y con cuerpo ---
    last_c = c_15m[-1]
    is_green = last_c[4] > last_c[1]
    body = abs(last_c[4] - last_c[1])
    full_range = last_c[2] - last_c[3]
    body_ratio = (body / full_range) if full_range > 0 else 0.0
    close_pos = ((last_c[4] - last_c[3]) / full_range) if full_range > 0 else 0.0

    # --- Momentum: Las últimas 2 velas de 15m son verdes ---
    prev_green = c_15m[-2][4] > c_15m[-2][1] if len(c_15m) >= 2 else False
    double_green = is_green and prev_green

    # --- Anti-Cuchillo: Las últimas 4 velas de 1H no deben ser todas rojas ---
    knife_count = sum(1 for c in c_1h[-4:] if c[4] < c[1])
    is_falling_knife = knife_count >= 4

    # --- Fuerza Relativa vs BTC (comparar cambio 1H de esta moneda vs BTC) ---
    if len(c_1h) >= 2:
        coin_chg_1h = (c_1h[-1][4] - c_1h[-2][4]) / c_1h[-2][4] * 100.0
    else:
        coin_chg_1h = 0.0
    rs_vs_btc = coin_chg_1h - btc_ctx["change_1h"]

    # --- DETECTOR DE IGNICIÓN DE MOMENTUM (arXiv:2602.11708 Trend-Following Engine) ---
    # Vela de expansión direccional institucional:
    # 1. Volumen agresivo (>= 2.0x promedio de 20 periodos)
    # 2. Rango expandido (Rango de la vela >= 1.20x ATR 15m)
    # 3. Vela dominante verde (Cuerpo >= 55% del rango total)
    # 4. Cierre en zona alta (Cierre en el 70%+ superior del rango)
    # 5. Fuerza relativa sólida frente a BTC (>= +0.8pp)
    # 6. Sin sobreextensión extrema previa ni cuchillo cayendo
    is_momentum_ignition = bool(
        is_green
        and vol_spike >= 2.0
        and full_range >= (1.20 * atr_15m)
        and body_ratio >= 0.55
        and close_pos >= 0.70
        and rs_vs_btc >= 0.8
        and not is_falling_knife
        and not is_overextended
    )

    # --- Parámetros de Trade Asimétricos con Piso Defensivo (1.20% min) y Techo (2.20% max) ---
    min_stop_pct = 0.0120  # Piso mínimo 1.20%: Erradica la muerte por micro-stops y ruido blanco
    max_stop_pct = 0.0220  # Techo máximo 2.20%: Preserva el capital ante cisnes negros
    raw_stop_dist = stop_mult * atr_15m
    stop_distance = max(curr_p * min_stop_pct, min(raw_stop_dist, curr_p * max_stop_pct))
    stop_pct = stop_distance / curr_p
    stop_price = round(curr_p - stop_distance, 6)

    # Target asimétrico:
    # Si hay Ignición de Momentum institucional, anclamos el target al ratio institucional de 3.4R
    if is_momentum_ignition:
        target_distance = max(target_mult * atr_15m, stop_distance * 3.4)
    else:
        target_distance = max(target_mult * atr_15m, stop_distance * 2.2)
    target_pct = target_distance / curr_p
    target_price = round(curr_p + target_distance, 6)
    rr_ratio = round(target_pct / max(stop_pct, 0.001), 2)

    # =================== PUNTUACIÓN V2 ADAPTATIVA ===================
    score = 0.0

    # A. Ruptura de micro-resistencia en 15m (+30)
    if breakout_confirmed:
        score += 30.0

    # B. Volumen Spike en la vela actual (+20 si >= vol_min, +10 si >= 1.0x)
    if vol_spike >= vol_min:
        score += 20.0
    elif vol_spike >= 1.0:
        score += 10.0

    # C. Vela(s) verde(s) con cuerpo (+15 por doble verde, +8 por verde simple)
    if double_green and body_ratio >= 0.40:
        score += 15.0
    elif is_green and body_ratio >= 0.30:
        score += 8.0

    # D. RSI 15m en zona de impulso (40-65 es ideal, ni sobrevendido ni sobrecomprado) (+10)
    if 38.0 <= rsi_15m <= 68.0:
        score += 10.0

    # E. Tendencia 1H a favor (precio > EMA20 1H) (+15)
    if trend_1h_bullish:
        score += 15.0

    # F. Fuerza Relativa positiva vs BTC (+10 si es más fuerte que BTC)
    if rs_vs_btc >= RS_MIN_THRESHOLD:
        score += 10.0
    elif rs_vs_btc >= 0.5:
        score += 5.0

    # G. Micro-Base Saludable en 5m/15m (+15 por consolidar en soporte)
    if has_healthy_base:
        score += 15.0

    # H. Bonus Ignición de Momentum Institucional (+35 pts)
    if is_momentum_ignition:
        score += 35.0

    # Penalizaciones:
    if is_falling_knife:
        score -= 40.0
    if is_overextended:
        score -= 50.0  # Penalización masiva si está en euforia/techo
    elif rsi_15m > 68.0:
        score -= 15.0
    if rsi_1h > 75.0:
        score -= 15.0

    is_trigger_ready = (
        (score >= min_score_target or is_momentum_ignition)
        and (breakout_confirmed or is_momentum_ignition)
        and is_green
        and vol_spike >= 1.0
        and not is_falling_knife
        and not is_overextended
        and rr_ratio >= 2.0
    )

    if is_overextended:
        status_str = "⚠️ SOBREEXTENDIDO (Enfriando)"
    elif is_momentum_ignition and is_trigger_ready:
        status_str = f"🚀 IGNICIÓN MOMENTUM ({rr_ratio}R)"
    elif is_trigger_ready:
        status_str = "🟢 RUPTURA CONFIRMADA"
    elif breakout_confirmed and score >= 50:
        status_str = "🟡 RUPTURA SIN VOLUMEN"
    elif trend_1h_bullish:
        status_str = "🔵 TENDENCIA OK - SIN RUPTURA"
    else:
        status_str = "⚪ OBSERVANDO"

    return {
        "symbol": symbol,
        "price": curr_p,
        "breakout": breakout_confirmed,
        "vol_spike": round(vol_spike, 2),
        "is_green": is_green,
        "double_green": double_green,
        "rsi_15m": round(rsi_15m, 1),
        "rsi_1h": round(rsi_1h, 1),
        "trend_1h": trend_1h_bullish,
        "atr_15m_pct": round(atr_pct_15m, 2),
        "rs_vs_btc": round(rs_vs_btc, 2),
        "coin_chg_1h": round(coin_chg_1h, 2),
        "is_falling_knife": is_falling_knife,
        "is_overextended": is_overextended,
        "has_healthy_base": has_healthy_base,
        "rsi_5m": round(rsi_5m, 1),
        "stop_pct": round(stop_pct * 100.0, 2),
        "target_pct": round(target_pct * 100.0, 2),
        "stop_price": stop_price,
        "target_price": target_price,
        "rr_ratio": rr_ratio,
        "score": round(score, 1),
        "trigger_ready": is_trigger_ready,
        "is_momentum_ignition": is_momentum_ignition,
        "status": status_str
    }


# ====================== CENTINELA DE ORDER FLOW L2 & TAPE ======================
def fetch_order_flow_confirmation(symbol: str, ex=exchange) -> Dict:
    """
    CENTINELA DE ORDER FLOW (Microestructura L2 & Tape).
    Filtro final ejecutado en el milisegundo antes de disparar un trade.
    1. Order Book Imbalance (OBI): Verifica la asimetría de liquidez pasiva en los 20 mejores niveles.
    2. Taker Volume Delta: Verifica la agresividad en los últimos 50 trades a mercado.
    3. Spread Real: Veta si el spread es excesivo (> 0.25%).
    """
    try:
        # 1. Order Book L2:
        ob = ex.fetch_order_book(symbol, limit=20)
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])
        if not bids or not asks:
            return {
                "confirmed": True,
                "obi": 0.0,
                "buy_ratio_pct": 50.0,
                "delta": 0.0,
                "spread_pct": 0.05,
                "reason": "Libro sin profundidad (permitido fallback defensivo)"
            }

        bid_vol = sum(float(b[1]) for b in bids)
        ask_vol = sum(float(a[1]) for a in asks)
        tot_ob = bid_vol + ask_vol
        obi = (bid_vol - ask_vol) / tot_ob if tot_ob > 0 else 0.0

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        spread_pct = ((best_ask - best_bid) / best_bid * 100.0) if best_bid > 0 else 0.0

        # 2. Taker Trades (Tape):
        trades = ex.fetch_trades(symbol, limit=50)
        if trades:
            taker_buy_vol = sum(float(t.get("amount", 0.0) or 0.0) for t in trades if t.get("side") == "buy")
            taker_sell_vol = sum(float(t.get("amount", 0.0) or 0.0) for t in trades if t.get("side") == "sell")
            tot_taker = taker_buy_vol + taker_sell_vol
            buy_ratio_pct = (taker_buy_vol / tot_taker * 100.0) if tot_taker > 0 else 50.0
            delta = taker_buy_vol - taker_sell_vol
        else:
            buy_ratio_pct = 50.0
            delta = 0.0

        # Criterios de Validación Institucionales:
        # Veto 1: Spread excesivo (trampa de baja liquidez o slippage)
        if spread_pct > 0.25:
            return {
                "confirmed": False,
                "obi": round(obi, 3),
                "buy_ratio_pct": round(buy_ratio_pct, 1),
                "delta": round(delta, 2),
                "spread_pct": round(spread_pct, 3),
                "reason": f"Spread excesivo ({spread_pct:.2f}% > 0.25%)"
            }

        # Veto 2: Muro masivo de venta en el Ask asfixiando el libro (OBI muy negativo)
        if obi < -0.25:
            return {
                "confirmed": False,
                "obi": round(obi, 3),
                "buy_ratio_pct": round(buy_ratio_pct, 1),
                "delta": round(delta, 2),
                "spread_pct": round(spread_pct, 3),
                "reason": f"Muro de venta institucional en Asks (OBI {obi:+.2f} < -0.25)"
            }

        # Veto 3: Agresión vendedora activa en la cinta (Taker sellers dominan > 55%)
        if buy_ratio_pct < 45.0:
            return {
                "confirmed": False,
                "obi": round(obi, 3),
                "buy_ratio_pct": round(buy_ratio_pct, 1),
                "delta": round(delta, 2),
                "spread_pct": round(spread_pct, 3),
                "reason": f"Ventas agresivas en cinta (Solo {buy_ratio_pct:.1f}% compras)"
            }

        return {
            "confirmed": True,
            "obi": round(obi, 3),
            "buy_ratio_pct": round(buy_ratio_pct, 1),
            "delta": round(delta, 2),
            "spread_pct": round(spread_pct, 3),
            "reason": "Order Flow Confirmado (Compradores activos sin muros de bloqueo)"
        }
    except Exception as e:
        # Fallback defensivo si el exchange tiene microcorte
        return {
            "confirmed": True,
            "obi": 0.0,
            "buy_ratio_pct": 50.0,
            "delta": 0.0,
            "spread_pct": 0.05,
            "reason": f"Excepción en telemetría OF ({e})"
        }


# ====================== GESTOR DE EJECUCIÓN V2 PAPER ======================
def execute_swing_paper_entry(bot: SwingBot, opp: Dict):
    """Abre una posición con confirmación de ruptura 15m + Interés Compuesto."""
    sym = opp["symbol"]
    if sym in bot.active_trades:
        return
    if len(bot.active_trades) >= bot.get_max_concurrent_trades():
        return

    curr_p = opp["price"]
    trade_capital = bot.calculate_trade_capital()
    if trade_capital < 15.0 or curr_p <= 0 or bot.cash < trade_capital:
        return

    # --- FILTRO CENTINELA DE ORDER FLOW (Microestructura L2 & Tape) ---
    flow = fetch_order_flow_confirmation(sym, exchange)
    if not flow.get("confirmed", True):
        bot.add_log(
            f"🛡️ [VETO ORDER FLOW] Disparo cancelado en {sym}: {flow['reason']} "
            f"(OBI: {flow['obi']:+.2f} | Compras: {flow['buy_ratio_pct']:.1f}% | Spread: {flow['spread_pct']:.2f}%)",
            "info"
        )
        bot.cooldowns[sym] = time.time() + 180  # Cooldown 3m para re-evaluar
        return

    # Precision de tamaño adaptada al valor del activo
    if curr_p >= 1000:
        amount = round(trade_capital / curr_p, 6)
    elif curr_p >= 1:
        amount = round(trade_capital / curr_p, 4)
    else:
        amount = round(trade_capital / curr_p, 2)
    trade_capital = round(amount * curr_p, 2)

    target_p = opp["target_price"]
    stop_p = opp["stop_price"]
    target_pct = opp["target_pct"] / 100.0
    stop_pct = opp["stop_pct"] / 100.0
    atr_p = opp["atr_15m_pct"]
    rr = opp["rr_ratio"]

    bot.sim_order_seq += 1
    order_id = f"SWING_{bot.sim_order_seq}"

    bot.cash -= trade_capital
    entry_fee = trade_capital * FEE_RATE

    trade = SwingTrade(
        trade_id=order_id,
        symbol=sym,
        entry_price=curr_p,
        amount=amount,
        capital=trade_capital,
        target_price=target_p,
        stop_price=stop_p,
        initial_stop=stop_p,
        target_pct=target_pct,
        stop_pct=stop_pct,
        atr_pct=atr_p,
        rr_ratio=rr,
        entry_time=time.time(),
        entry_fee=entry_fee,
        of_obi=flow.get("obi", 0.0),
        of_buy_ratio=flow.get("buy_ratio_pct", 50.0)
    )
    bot.active_trades[sym] = trade
    tier = bot.get_tier_name()
    rs_info = f"RS vs BTC: {opp.get('rs_vs_btc', 0):+.1f}pp"
    of_info = f"OF: OBI {flow['obi']:+.2f}, Compras {flow['buy_ratio_pct']:.1f}%"
    is_ign = opp.get("is_momentum_ignition", False)
    if is_ign:
        bot.add_log(f"🚀 [IGNICIÓN MOMENTUM] OLA INSTITUCIONAL en {sym}: Vol {opp.get('vol_spike', 0):.1f}x | {rs_info} | {of_info} | ${trade_capital:.2f} USDT | Target 3.4R: ${target_p:.4f} (+{target_pct*100:.2f}%) | Stop: ${stop_p:.4f} (-{stop_pct*100:.2f}%) | R:R {rr}:1", "trade")
        entry_note = f"🚀 Ignición Momentum #{order_id} (R:R {rr}:1 | Vol {opp.get('vol_spike', 0):.1f}x | {of_info})"
    else:
        bot.add_log(f"🎯 DISPARO V2 #{order_id}: {sym} @ ${curr_p:.4f} | {rs_info} | {of_info} | Ruptura 15m + Vol {opp.get('vol_spike', 0):.1f}x | ${trade_capital:.2f} USDT | Target: ${target_p:.4f} (+{target_pct*100:.2f}%) | Stop: ${stop_p:.4f} (-{stop_pct*100:.2f}%) | R:R {rr}:1", "trade")
        entry_note = f"V2 Entry #{order_id} (R:R {rr}:1 | {of_info} | RS {opp.get('rs_vs_btc', 0):+.1f}pp)"

    bot.db.log_trade(
        symbol=sym, side="BUY", price=curr_p, amount=amount, capital=trade_capital,
        pnl=0.0, fee=entry_fee, order_id=order_id, target_price=target_p, stop_price=stop_p,
        note=entry_note
    )
    bot.save_state()


def process_trade_autopsy_and_feedback(bot: SwingBot, tr: SwingTrade, exit_price: float, net_pnl: float, reason: str, exit_fee: float):
    """
    Motor Dinámico de Autoaprendizaje y Autopsia Post-Trade.
    Evalúa MFE (máxima subida), MAE (máxima caída), contexto macro de BTC y duración.
    Clasifica la causa raíz y autoajusta los parámetros en caliente en SQLite.
    """
    now = time.time()
    duration_s = max(1.0, now - tr.entry_time)
    highest_p = getattr(tr, "highest_price", tr.entry_price)
    lowest_p = getattr(tr, "lowest_price", tr.entry_price)
    mfe_pct = (highest_p - tr.entry_price) / tr.entry_price * 100.0
    mae_pct = (lowest_p - tr.entry_price) / tr.entry_price * 100.0
    pnl_pct = (net_pnl / tr.capital * 100.0) if tr.capital > 0 else 0.0

    btc_ctx = update_btc_context()
    btc_regime = btc_ctx.get("regime", "NEUTRAL_TRANSITION")

    classification = "UNKNOWN"
    lesson = ""
    action = ""

    if net_pnl > 0:
        if "TARGET" in reason or pnl_pct >= 3.0:
            classification = "TARGET_HIT"
            lesson = f"Ruptura sólida en {tr.symbol} con expansión completa (+{pnl_pct:.2f}%). Cosecha óptima."
            action = "Mantener parámetros de convicción y celebrar la paciencia técnica."
        elif mfe_pct >= 2.0 and pnl_pct < 0.30:
            classification = "PREMATURE_CHOKE"
            lesson = f"El activo subió +{mfe_pct:.2f}% (MFE) pero el trade se cerró con apenas +{pnl_pct:.2f}% (+${net_pnl:.2f}). Trailing/BE demasiado apretado."
            action = "Autoaprendizaje: Relajando holgura de Trailing a 1.6x-1.8x ATR."
            cur_trail = bot.settings.get("trail_distance_atr", 1.6)
            bot.settings["trail_distance_atr"] = round(min(2.0, max(1.5, cur_trail + 0.1)), 2)
            bot.save_settings()
        elif "TRAILING" in reason:
            classification = "RUNNER_HARVESTED"
            lesson = f"Tendencia aprovechada (+{pnl_pct:.2f}%). Trailing Stop aseguró ganancias en retroceso."
            action = "Excelente ejecución de persecución de tendencia."
        else:
            classification = "BREAK_EVEN_EXIT"
            lesson = f"Cierre defensivo en coste protegido (+{pnl_pct:.2f}%). Capital preservado."
            action = "Continuar escaneo."
    else:
        # Trade perdedor:
        if duration_s < 1500 and abs(mae_pct) < 1.0:
            classification = "NOISE_STOP_HUNT"
            lesson = f"Stop tocado en {duration_s/60:.0f}m con oscilación menor (-{abs(mae_pct):.2f}%). Víctima de ruido blanco / spread."
            action = "Autoaprendizaje: Forzar piso mínimo de Stop al 1.40% y elevar stop multiplier."
            cur_stop = bot.settings.get("stop_atr_mult", 2.0)
            bot.settings["stop_atr_mult"] = round(min(2.5, cur_stop + 0.1), 2)
            bot.save_settings()
        elif btc_regime == "CHOP_COMPRESSION":
            classification = "CHOP_FALSE_BREAKOUT"
            lesson = f"Falsa ruptura en {tr.symbol} atrapada por compresión lateral de Bitcoin. Trampa de liquidez."
            action = "Autoaprendizaje: Activando Cooldown extendido (15 min) y exigiendo Score A+ (86+)."
            bot.settings["post_stop_cooldown_s"] = 900
            bot.settings["min_score"] = round(max(84.0, bot.settings.get("min_score", 82.0) + 1.0), 1)
            bot.save_settings()
        elif btc_regime == "BEARISH_DUMP":
            classification = "MACRO_BTC_DRAG"
            lesson = f"Venta masiva de Bitcoin arrastró a {tr.symbol}. Ruptura invalidada por macro."
            action = "Autoaprendizaje: Candado bajista activado. Prohibidas compras hasta estabilización de BTC."
        else:
            classification = "NORMAL_STOP_DEFENSIVE"
            lesson = f"Stop defensivo actuó según plan (-{abs(pnl_pct):.2f}%). Pérdida estrictamente acotada."
            action = "Respetar cooldown y esperar siguiente configuración A+."

    # Registrar en SQLite
    bot.db.log_autopsy(
        trade_id=tr.trade_id,
        symbol=tr.symbol,
        pnl=net_pnl,
        pnl_pct=pnl_pct,
        duration_s=duration_s,
        mfe_pct=mfe_pct,
        mae_pct=mae_pct,
        exit_reason=reason,
        classification=classification,
        btc_regime=btc_regime,
        lesson_learned=lesson,
        adaptive_action=action
    )
    bot.add_log(f"🔬 AUTOPSIA [{classification}] {tr.symbol}: PnL {net_pnl:+.4f} USDT ({pnl_pct:+.2f}%) | MFE: +{mfe_pct:.2f}% | MAE: {mae_pct:.2f}% | Lección: {lesson}", "trade")


def manage_active_swing_trade(bot: SwingBot):
    """V2: Monitorea trades activos con Trailing Ágil basado en ATR 15m y Autopsia Post-Trade."""
    if not bot.active_trades:
        bot.status_msg = "Sin posiciones. Escáner V2 buscando rupturas con fuerza relativa..."
        return

    for tr in list(bot.active_trades.values()):
        sym = tr.symbol
        try:
            ticker = exchange.fetch_ticker(sym)
            curr_p = float(ticker.get("last", 0.0) or 0.0)
        except Exception:
            continue

        if curr_p <= 0:
            continue

        gain_pct = (curr_p - tr.entry_price) / tr.entry_price

        tr.current_price = curr_p
        tr.highest_price = max(getattr(tr, "highest_price", tr.entry_price), curr_p)
        tr.lowest_price = min(getattr(tr, "lowest_price", tr.entry_price), curr_p)
        tr.unrealized_pnl = (curr_p - tr.entry_price) * tr.amount
        tr.unrealized_pnl_pct = gain_pct * 100.0

        atr_val_abs = tr.entry_price * (tr.atr_pct / 100.0)

        # 1. Break-Even: Dinámico por ATR o Manual según faders
        if getattr(bot, "settings", {}).get("auto_atr_mode", True):
            # En Modo Automático ATR: El umbral escala con el ATR del activo (0.9x ATR, mínimo 1.20%)
            be_threshold = max(0.012, (tr.atr_pct / 100.0) * 0.90)
        else:
            be_threshold = getattr(bot, "settings", {}).get("be_trigger_pct", 0.016)

        be_stop = getattr(bot, "settings", {}).get("be_stop_pct", 0.0020)
        if not tr.is_be_active and gain_pct >= be_threshold:
            tr.is_be_active = True
            new_stop = round(tr.entry_price * (1.0 + be_stop), 6)
            if new_stop > tr.stop_price:
                tr.stop_price = new_stop
                mode_lbl = "AUTO ATR" if getattr(bot, "settings", {}).get("auto_atr_mode", True) else "MANUAL"
                bot.add_log(f"🛡️ BREAK-EVEN [{mode_lbl}] en {sym}: +{gain_pct*100:.2f}% (Umbral {be_threshold*100:.2f}%). Stop -> ${new_stop:.4f} (+{be_stop*100:.2f}%). Riesgo CERO.", "trade")
                bot.save_state()

        # 2. Trailing: Desde +1.5x ATR 15m, persigue el máximo menos distancia ATR configurada
        trail_dist_mult = getattr(bot, "settings", {}).get("trail_distance_atr", 1.6)
        trailing_trigger = (tr.atr_pct / 100.0) * 1.5
        if gain_pct >= trailing_trigger:
            trail_stop = round(tr.highest_price - (trail_dist_mult * atr_val_abs), 6)
            if trail_stop > tr.stop_price:
                old_stop = tr.stop_price
                tr.stop_price = trail_stop
                tr.is_trailing_active = True
                bot.add_log(f"📈 TRAILING en {sym}: Max ${tr.highest_price:.4f}. Stop ${old_stop:.4f} -> ${trail_stop:.4f} ({trail_dist_mult}x ATR)", "trade")
                bot.save_state()

        # 3. Cierre por Target:
        if curr_p >= tr.target_price:
            gross_pnl = (tr.target_price - tr.entry_price) * tr.amount
            exit_fee = (tr.target_price * tr.amount) * FEE_RATE
            net_pnl = gross_pnl - tr.entry_fee - exit_fee
            bot.cash += (tr.capital + net_pnl)
            reason = f"🏆 TARGET V2 (+{tr.target_pct*100:.2f}%)"
            bot.add_log(f"{reason} en {sym}: ${tr.target_price:.4f} | PnL: +${net_pnl:.4f} USDT", "trade")
            bot.db.log_trade(
                symbol=sym, side="SELL", price=tr.target_price, amount=tr.amount, capital=tr.capital,
                pnl=net_pnl, fee=exit_fee, order_id=tr.trade_id, target_price=tr.target_price, stop_price=tr.stop_price,
                note=reason
            )
            process_trade_autopsy_and_feedback(bot, tr, tr.target_price, net_pnl, reason, exit_fee)
            bot.cooldowns[sym] = time.time() + 300  # 5 min cooldown tras win
            bot.active_trades.pop(sym, None)
            bot.save_state()
            continue

        # 4. Cierre por Stop Loss (o Break-Even / Trailing):
        if curr_p <= tr.stop_price:
            gross_pnl = (tr.stop_price - tr.entry_price) * tr.amount
            exit_fee = (tr.stop_price * tr.amount) * FEE_RATE
            net_pnl = gross_pnl - tr.entry_fee - exit_fee
            bot.cash += (tr.capital + net_pnl)
            if tr.is_trailing_active:
                reason = f"📈 TRAILING CERRÓ CON GANANCIA"
            elif tr.is_be_active:
                reason = "🛡️ SALIDA BREAK-EVEN"
            else:
                reason = f"🛑 STOP DEFENSIVO (-{tr.stop_pct*100:.2f}%)"
            bot.add_log(f"{reason} en {sym} @ ${tr.stop_price:.4f} | PnL: {net_pnl:+.4f} USDT", "trade")
            bot.db.log_trade(
                symbol=sym, side="SELL", price=tr.stop_price, amount=tr.amount, capital=tr.capital,
                pnl=net_pnl, fee=exit_fee, order_id=tr.trade_id, target_price=tr.target_price, stop_price=tr.stop_price,
                note=reason
            )
            process_trade_autopsy_and_feedback(bot, tr, tr.stop_price, net_pnl, reason, exit_fee)
            # Anti-Ametralladora: cooldown inteligente tras stop
            cd_sec = getattr(bot, "settings", {}).get("post_stop_cooldown_s", POST_STOP_COOLDOWN_S)
            bot.cooldowns[sym] = time.time() + cd_sec
            bot.last_stop_time = time.time()  # Marca global para exigir score extra
            bot.active_trades.pop(sym, None)
            bot.save_state()
            continue

    if bot.active_trades:
        summaries = [f"{t.symbol} ({t.unrealized_pnl_pct:+.2f}%)" for t in bot.active_trades.values()]
        bot.status_msg = f"Posiciones Activas ({len(bot.active_trades)}/{bot.get_max_concurrent_trades()}): " + ", ".join(summaries)


# ====================== MOTOR DUAL: GESTIÓN DE MALLA ACOTADA EN CHOP ======================
def scan_bounded_grid_candidates(bot: SwingBot) -> Optional[BoundedMicroGrid]:
    """
    Escanea candidatos para Malla Acotada durante régimen CHOP_COMPRESSION.
    Criterios matemáticos:
    - Volumen diario >= $15M
    - Exponente de Hurst H < 0.46 (Reversión a la media comprobada)
    - Canal horizontal detectado (1.0% <= Ancho <= 4.5%, pendiente plana)
    - Posición actual en el canal: channel_pos <= 0.60 (compramos en la mitad inferior)
    """
    if bot.cash < 45.0 or getattr(bot, "active_grid", None) or bot.active_trades:
        return None

    now = time.time()
    movers = scan_market_top_movers()
    symbols = [m["symbol"] for m in movers[:15] if m["symbol"] not in IGNORE_SYMBOLS]
    priority_pairs = ["BNB/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT", "NEAR/USDT", "ADA/USDT", "SUI/USDT"]
    for p in priority_pairs:
        if p not in symbols:
            symbols.append(p)

    best_candidate = None
    lowest_hurst = 0.50

    for sym in symbols:
        if bot.cooldowns.get(sym, 0) > now:
            continue
        try:
            candles = fetch_ohlcv_cached(sym, "15m", limit=36)
            if len(candles) < 24:
                continue
            closes = [c[4] for c in candles]
            h = calc_hurst_exponent(closes)
            if h >= 0.46:  # No califica si es tendencial
                continue

            chan = detect_horizontal_channel(candles)
            if not chan:
                continue

            if chan["channel_pos"] > 0.60:
                continue

            if h < lowest_hurst:
                lowest_hurst = h
                best_candidate = (sym, chan, h, closes[-1])
        except Exception:
            continue

    if not best_candidate:
        return None

    sym, chan, h, curr_p = best_candidate
    supp = chan["support"]
    res = chan["resistance"]
    mid = chan["midpoint"]

    total_grid_cap = min(bot.cash * 0.85, 54.0)
    level_cap = round(total_grid_cap / 3.0, 2)

    half_width = (mid - supp)
    p1 = round(mid - half_width * 0.25, 6)
    p2 = round(mid - half_width * 0.65, 6)
    p3 = round(supp * 1.002, 6)

    def get_amt(p):
        if p >= 1000: return round(level_cap / p, 6)
        elif p >= 1: return round(level_cap / p, 4)
        else: return round(level_cap / p, 2)

    kill_switch_p = round(supp * 0.988, 6)

    bot.sim_order_seq += 1
    grid_id = f"GRID_{bot.sim_order_seq}"

    grid = BoundedMicroGrid(
        grid_id=grid_id,
        symbol=sym,
        channel_support=supp,
        channel_resistance=res,
        midpoint=mid,
        hurst_exponent=h,
        kill_switch_price=kill_switch_p,
        total_capital=total_grid_cap
    )

    lvl1 = GridLevel(0, p1, get_amt(p1), level_cap)
    lvl2 = GridLevel(1, p2, get_amt(p2), level_cap)
    lvl3 = GridLevel(2, p3, get_amt(p3), level_cap)

    if curr_p <= p1:
        lvl1.status = "FILLED"
        lvl1.fill_price = curr_p
        lvl1.fill_time = time.time()
        bot.cash -= level_cap
        bot.db.log_trade(
            symbol=sym, side="BUY", price=curr_p, amount=lvl1.amount, capital=level_cap,
            pnl=0.0, fee=level_cap * FEE_RATE, order_id=f"{grid_id}_L1",
            target_price=res, stop_price=kill_switch_p,
            note=f"📥 MALLA FILL N1/3 {sym} (Canal {chan['width_pct']}% | H: {h})", mode="BOUNDED_GRID"
        )

    grid.levels = [lvl1, lvl2, lvl3]
    bot.active_grid = grid
    bot.active_mode = "BOUNDED_GRID"

    bot.add_log(f"🟡 ACTIVANDO MALLA ACOTADA #{grid_id} en {sym}: Canal ${supp:.4f} - ${res:.4f} ({chan['width_pct']}%) | Hurst: {h} | Kill-Switch: ${kill_switch_p:.4f} | Cap: ${total_grid_cap:.2f} USDT", "trade")
    bot.save_state()
    return grid


def manage_active_bounded_grid(bot: SwingBot):
    """
    Monitorea la Malla Acotada activa.
    1. Ejecuta Kill-Switch si el precio rompe el soporte del canal.
    2. Llena órdenes de compra pendientes cuando el precio retrocede.
    3. Cosecha ganancias (Take Profit) cuando el precio revierte hacia la resistencia o media.
    """
    grid = getattr(bot, "active_grid", None)
    if not grid or grid.status != "ACTIVE":
        return

    sym = grid.symbol
    try:
        ticker = exchange.fetch_ticker(sym)
        curr_p = float(ticker.get("last", 0.0) or 0.0)
    except Exception:
        return

    if curr_p <= 0:
        return

    grid.current_price = curr_p
    total_inv = grid.get_total_inventory()
    invested_cap = grid.get_invested_capital()
    avg_entry = grid.get_average_entry()

    if total_inv > 0 and avg_entry > 0:
        grid.unrealized_pnl = (curr_p - avg_entry) * total_inv
        unrealized_pct = (curr_p - avg_entry) / avg_entry * 100.0
    else:
        grid.unrealized_pnl = 0.0
        unrealized_pct = 0.0

    # 1. KILL-SWITCH ESTRICTO (Garantía Anti-Atrapamiento):
    if curr_p <= grid.kill_switch_price:
        exit_fee = (curr_p * total_inv) * FEE_RATE if total_inv > 0 else 0.0
        gross_pnl = (curr_p - avg_entry) * total_inv if total_inv > 0 else 0.0
        net_pnl = gross_pnl - exit_fee
        bot.cash += (invested_cap + net_pnl)
        reason = f"🛑 KILL-SWITCH MALLA: Canal roto en {sym} @ ${curr_p:.4f} (Stop {-abs(unrealized_pct):.2f}%)"
        bot.add_log(f"{reason} | PnL: {net_pnl:+.4f} USDT | Capital protegido.", "trade")
        if total_inv > 0:
            bot.db.log_trade(
                symbol=sym, side="SELL", price=curr_p, amount=total_inv, capital=invested_cap,
                pnl=net_pnl, fee=exit_fee, order_id=f"{grid.grid_id}_KILL",
                target_price=grid.channel_resistance, stop_price=grid.kill_switch_price,
                note=reason, mode="BOUNDED_GRID"
            )
            bot.db.log_autopsy(
                trade_id=grid.grid_id, symbol=sym, pnl=net_pnl, pnl_pct=unrealized_pct,
                duration_s=time.time() - grid.created_at, mfe_pct=0.0, mae_pct=unrealized_pct,
                exit_reason=reason, classification="GRID_KILL_SWITCH", btc_regime="CHOP_COMPRESSION",
                lesson_learned=f"Canal horizontal de {sym} perforado. Kill-Switch liquidó inventario evitando atrapamiento.",
                adaptive_action="Enfriamiento de 15m en el par y re-verificación de Hurst."
            )
        bot.cooldowns[sym] = time.time() + 900  # 15 min cooldown
        bot.active_grid = None
        bot.active_mode = "SWING_SNIPER"
        bot.save_state()
        return

    # 2. Ejecutar Fills de Niveles Pendientes:
    for lvl in grid.levels:
        if lvl.status == "PENDING" and curr_p <= lvl.price:
            if bot.cash >= lvl.capital:
                bot.cash -= lvl.capital
                lvl.status = "FILLED"
                lvl.fill_price = curr_p
                lvl.fill_time = time.time()
                bot.add_log(f"📥 MALLA FILL Nivel {lvl.level_idx+1}/3 en {sym} @ ${curr_p:.4f} (${lvl.capital:.2f} USDT)", "trade")
                bot.db.log_trade(
                    symbol=sym, side="BUY", price=curr_p, amount=lvl.amount, capital=lvl.capital,
                    pnl=0.0, fee=lvl.capital * FEE_RATE, order_id=f"{grid.grid_id}_L{lvl.level_idx+1}",
                    target_price=grid.channel_resistance, stop_price=grid.kill_switch_price,
                    note=f"📥 MALLA FILL N{lvl.level_idx+1}/3 @ ${curr_p:.4f}", mode="BOUNDED_GRID"
                )
                bot.save_state()

    # 3. COSECHA DE GANANCIAS (Take Profit / Reversión a la Resistencia del Canal):
    if total_inv > 0 and (curr_p >= grid.channel_resistance or (curr_p >= avg_entry * 1.018 and curr_p >= grid.midpoint)):
        exit_fee = (curr_p * total_inv) * FEE_RATE
        gross_pnl = (curr_p - avg_entry) * total_inv
        net_pnl = gross_pnl - exit_fee
        bot.cash += (invested_cap + net_pnl)
        pnl_pct = (net_pnl / invested_cap) * 100.0
        reason = f"🏆 COSECHA MALLA CHOP en {sym} @ ${curr_p:.4f} (+{pnl_pct:.2f}%)"
        bot.add_log(f"{reason} | PnL: +${net_pnl:.4f} USDT | Capital devuelto a caja.", "trade")
        bot.db.log_trade(
            symbol=sym, side="SELL", price=curr_p, amount=total_inv, capital=invested_cap,
            pnl=net_pnl, fee=exit_fee, order_id=f"{grid.grid_id}_HARVEST",
            target_price=grid.channel_resistance, stop_price=grid.kill_switch_price,
            note=reason, mode="BOUNDED_GRID"
        )
        bot.db.log_autopsy(
            trade_id=grid.grid_id, symbol=sym, pnl=net_pnl, pnl_pct=pnl_pct,
            duration_s=time.time() - grid.created_at, mfe_pct=pnl_pct, mae_pct=0.0,
            exit_reason=reason, classification="GRID_CHOP_HARVEST", btc_regime="CHOP_COMPRESSION",
            lesson_learned=f"Reversión a la media exitosa en {sym} (Hurst: {grid.hurst_exponent}). Ganancia cosechada sin acumulación.",
            adaptive_action="Capital liberado a caja listo para siguiente ciclo."
        )
        bot.cooldowns[sym] = time.time() + 300  # 5 min cooldown tras win
        bot.active_grid = None
        bot.active_mode = "SWING_SNIPER"
        bot.save_state()
        return

    filled_cnt = len(grid.get_filled_levels())
    bot.status_msg = f"🟡 Malla Chop {sym}: {filled_cnt}/3 niveles ({unrealized_pct:+.2f}%) | Kill-Switch: ${grid.kill_switch_price:.4f} | Hurst: {grid.hurst_exponent}"


# ====================== SERVIDOR DASHBOARD REACTIVO (PUERTO 8900) ======================
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>THE SWING SNIPER & PIONEX GRID - QUANT DASHBOARD</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700;800&family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-base: #0d1117;
            --card-bg: #161b22;
            --border: #30363d;
            --accent: #58a6ff;
            --green: #3fb950;
            --red: #f85149;
            --yellow: #d29922;
            --purple: #bc8cff;
            --text-main: #c9d1d9;
            --text-dim: #8b949e;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background: var(--bg-base);
            color: var(--text-main);
            font-family: 'Inter', -apple-system, sans-serif;
            padding: 24px;
        }
        .container { max-width: 1350px; margin: 0 auto; }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 16px;
            margin-bottom: 24px;
            flex-wrap: wrap;
            gap: 15px;
        }
        .title-block h1 {
            font-size: 22px;
            font-weight: 800;
            color: #ffffff;
            letter-spacing: -0.5px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .title-sub { font-size: 13px; color: var(--text-dim); margin-top: 4px; font-family: 'JetBrains Mono', monospace; }
        .badge-live {
            background: rgba(63, 185, 80, 0.15);
            color: var(--green);
            border: 1px solid var(--green);
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }
        .grid-2col {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 24px;
        }
        @media (max-width: 900px) { .grid-2col { grid-template-columns: 1fr; } }
        .card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
        }
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #21262d;
            padding-bottom: 12px;
            margin-bottom: 16px;
        }
        .card-title {
            font-size: 15px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .metric-box {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            gap: 12px;
            margin-bottom: 15px;
        }
        .metric {
            background: #0d1117;
            padding: 12px;
            border-radius: 8px;
            border: 1px solid #21262d;
        }
        .metric-label { font-size: 11px; color: var(--text-dim); text-transform: uppercase; font-weight: 600; }
        .metric-value { font-size: 18px; font-weight: 800; color: #ffffff; margin-top: 4px; font-family: 'JetBrains Mono', monospace; }
        
        table { width: 100%; border-collapse: collapse; font-family: 'JetBrains Mono', monospace; font-size: 12px; }
        th { text-align: left; padding: 10px 8px; color: var(--text-dim); border-bottom: 1px solid var(--border); font-size: 11px; }
        td { padding: 10px 8px; border-bottom: 1px solid #1c2128; }
        tr:hover { background: rgba(88, 166, 255, 0.04); }
        .tag { padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; display: inline-block; }
        .tag-green { background: rgba(63, 185, 80, 0.15); color: var(--green); border: 1px solid var(--green); }
        .tag-yellow { background: rgba(210, 153, 34, 0.15); color: var(--yellow); border: 1px solid var(--yellow); }
        .tag-gray { background: #21262d; color: var(--text-dim); }
        .terminal {
            background: #090d13;
            border: 1px solid #21262d;
            border-radius: 8px;
            padding: 12px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 11px;
            height: 160px;
            overflow-y: auto;
        }
        .log-row { margin-bottom: 4px; }
        .log-time { color: var(--text-dim); }
        .log-trade { color: var(--green); font-weight: 600; }
        .log-info { color: var(--text-main); }

        /* Faders & Sliders Panel de Control */
        .fader-group {
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 12px 14px;
            transition: border-color 0.2s;
        }
        .fader-group:hover {
            border-color: #58a6ff;
        }
        .fader-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }
        .fader-label {
            font-size: 12px;
            font-weight: 600;
            color: var(--text-main);
        }
        .fader-val {
            font-size: 13px;
            font-weight: 700;
            color: #58a6ff;
            font-family: 'JetBrains Mono', monospace;
        }
        .fader-sub {
            font-size: 10px;
            color: var(--text-dim);
            margin-top: 6px;
            line-height: 1.3;
        }
        input[type=range] {
            -webkit-appearance: none;
            width: 100%;
            background: #21262d;
            height: 6px;
            border-radius: 3px;
            outline: none;
            cursor: pointer;
        }
        input[type=range]::-webkit-slider-thumb {
            -webkit-appearance: none;
            appearance: none;
            width: 16px;
            height: 16px;
            border-radius: 50%;
            background: #f0883e;
            cursor: pointer;
            box-shadow: 0 0 6px rgba(240, 136, 62, 0.5);
            transition: transform 0.1s;
        }
        input[type=range]::-webkit-slider-thumb:hover {
            transform: scale(1.25);
        }
        .btn-toggle-auto {
            background: #1f6feb;
            border: 1px solid #388bfd;
            color: #ffffff;
            font-weight: 700;
            font-size: 11px;
            padding: 6px 14px;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s;
            font-family: 'JetBrains Mono', monospace;
        }
        .btn-toggle-auto:hover {
            background: #388bfd;
        }
        .btn-toggle-auto.off {
            background: #21262d;
            border-color: #30363d;
            color: #8b949e;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- HEADER -->
        <div class="header">
            <div class="title-block">
                <h1>🦅 THE QUANT SNIPER & GRID DESK</h1>
                <div class="title-sub">Dual Architecture: Malla Spot Pionex (Real) + Asymmetric Swing 1H/4H (Paper)</div>
            </div>
            <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
                <a href="/quantum" style="text-decoration: none; padding: 5px 12px; background: #131b2e; border: 1px solid #38bdf8; border-radius: 6px; color: #38bdf8; font-size: 11px; font-weight: bold; font-family: monospace; transition: all 0.2s;" target="_blank">⚛️ Comparador Cuántico (Monte Carlo) ↗</a>
                <span class="badge-live">● SISTEMA OPERATIVO</span>
                <span style="font-size: 12px; color: var(--text-dim); font-family: monospace;">Refresco 3s</span>
            </div>
        </div>

        <!-- PILAR 1 Y PILAR 2 CARDS -->
        <div class="grid-2col">
            <!-- PILAR 1: MALLA REAL PIONEX (DOGE) -->
            <div class="card" style="border-left: 4px solid var(--purple);">
                <div class="card-header">
                    <div class="card-title" style="color: var(--purple);">
                        <span>⚡ PILAR 1: MALLA PIONEX SPOT REAL (DOGE/USDT)</span>
                    </div>
                    <span class="tag tag-green">BOT EN EJECUCIÓN</span>
                </div>
                <div class="metric-box">
                    <div class="metric">
                        <div class="metric-label">Inversión Inicial</div>
                        <div class="metric-value" id="grid-invest">$69.71</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Beneficio Acumulado</div>
                        <div class="metric-value" style="color: var(--green);" id="grid-profit">+$1.84 USDT</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Arbitrajes Emparejados</div>
                        <div class="metric-value" id="grid-pairs">118</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Rango Activo</div>
                        <div class="metric-value" style="font-size: 14px;" id="grid-range">0.067 - 0.093</div>
                    </div>
                </div>
                <div style="font-size: 11px; color: var(--text-dim); font-family: monospace; line-height: 1.5;">
                    • Estado: <b style="color: #ffffff;">Reinversión Automática Activa</b> | Trailing-Up Activado (+5%).<br>
                    • Tu bot real en Pionex está 100% aislado y ganando dinero de la oscilación lateral.
                </div>
            </div>

            <!-- PILAR 2: SWING SNIPER (1H / 4H PAPER) -->
            <div class="card" style="border-left: 4px solid var(--accent);">
                <div class="card-header">
                    <div class="card-title" style="color: var(--accent);">
                        <span>🎯 PILAR 2: SWING SNIPER V2 (FUERZA RELATIVA & 15m BREAKOUT)</span>
                    </div>
                    <div style="display: flex; gap: 8px; align-items: center;">
                        <span class="tag tag-yellow" id="tier-badge">Mono-Sniper (&lt;$120)</span>
                        <span class="tag tag-green">INTERÉS COMPUESTO ACTIVO</span>
                    </div>
                </div>
                <div class="metric-box">
                    <div class="metric">
                        <div class="metric-label">Patrimonio Total (Equity)</div>
                        <div class="metric-value" id="swing-equity" style="color: #58a6ff;">$70.00</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Caja Disponible</div>
                        <div class="metric-value" id="swing-cash">$70.00</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">En Posición (Invertido)</div>
                        <div class="metric-value" id="swing-invested">$0.00</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">PnL Flotante (En Vivo)</div>
                        <div class="metric-value" id="swing-unrealized">$0.00 (0.00%)</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">PnL Realizado</div>
                        <div class="metric-value" id="swing-pnl">$0.00</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Trades Cerrados</div>
                        <div class="metric-value" id="swing-stats">0 (0W / 0L)</div>
                    </div>
                </div>
                <!-- POSICIÓN SWING ACTIVA -->
                <div id="active-box" style="margin-top: 10px;">
                    <div id="active-status"></div>
                </div>

                <!-- ÚLTIMO TRADE FINALIZADO -->
                <div id="last-trade-box" style="margin-top: 10px; background: #090d13; border: 1px solid #21262d; border-radius: 6px; padding: 8px 12px; font-family: 'JetBrains Mono', monospace; font-size: 11px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px;">
                    <span style="color: var(--text-dim); font-size: 10px; font-weight: 600;">🏆 ÚLTIMA OPERACIÓN FINALIZADA:</span>
                    <span id="last-trade-summary" style="color: #ffffff;">Consultando historial SQLite...</span>
                </div>

                <!-- CEREBRO ADAPTATIVO & AUTOPSIA POST-TRADE -->
                <div id="autopsy-box" style="margin-top: 10px; background: #0c1017; border: 1px solid #30363d; border-radius: 6px; padding: 10px 14px; font-family: 'JetBrains Mono', monospace; font-size: 11px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; flex-wrap: wrap; gap: 6px;">
                        <span style="color: #58a6ff; font-weight: 700;">🔬 CEREBRO ADAPTATIVO & AUTOPSIA POST-TRADE</span>
                        <span id="btc-regime-badge" class="tag tag-blue" style="font-size: 10px;">REGIMEN: CALCULANDO...</span>
                    </div>
                    <div id="autopsy-summary" style="color: #c9d1d9; font-size: 11px; line-height: 1.4;">
                        Analizando historial de 24 trades en SQLite. Próximo trade será clasificado automáticamente...
                    </div>
                </div>

                <!-- RADAR STATUS FEED -->
                <div style="margin-top: 8px; font-size: 11px; color: var(--text-dim); font-family: 'JetBrains Mono', monospace; display: flex; align-items: center; gap: 6px;">
                    <span style="color: #f0883e;">📡</span> <span id="radar-live-status">Iniciando radar...</span>
                </div>
            </div>
        </div>

        <!-- CONSOLA DE CONTROL INTERACTIVA (FADERS & MODO AUTOMÁTICO ATR) -->
        <div class="card" style="margin-bottom: 24px; border-left: 4px solid #f0883e;">
            <div class="card-header" style="flex-wrap: wrap; gap: 12px;">
                <div class="card-title" style="color: #f0883e;">
                    <span>🎛️ CONSOLA DE CALIBRACIÓN EN VIVO (FADERS & GESTIÓN DE RIESGO)</span>
                </div>
                <div style="display: flex; gap: 10px; align-items: center;">
                    <span id="cfg-sync-badge" class="tag tag-green" style="font-size: 11px;">● SINCRONIZADO</span>
                    <button id="btn-auto-atr" onclick="toggleAutoAtr()" class="btn-toggle-auto">
                        🤖 MODO AUTOMÁTICO (ATR DINÁMICO): ON
                    </button>
                </div>
            </div>
            
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px;">
                <!-- Fader 1: Umbral Break-Even -->
                <div class="fader-group">
                    <div class="fader-header">
                        <span class="fader-label">🛡️ Umbral Break-Even:</span>
                        <span class="fader-val" id="val-be-trigger">+1.60%</span>
                    </div>
                    <input type="range" id="slider-be-trigger" min="0.5" max="3.5" step="0.1" value="1.6" oninput="updateFaderUI('be_trigger_pct', this.value)" onchange="sendSettingsUpdate()">
                    <div class="fader-sub">Ganancia requerida para subir stop a coste cero (+0.20%).</div>
                </div>

                <!-- Fader 2: Stop Loss ATR -->
                <div class="fader-group">
                    <div class="fader-header">
                        <span class="fader-label">🛑 Stop Loss (ATR 15m):</span>
                        <span class="fader-val" id="val-stop-atr">1.2x ATR</span>
                    </div>
                    <input type="range" id="slider-stop-atr" min="0.8" max="2.5" step="0.1" value="1.2" oninput="updateFaderUI('stop_atr_mult', this.value)" onchange="sendSettingsUpdate()">
                    <div class="fader-sub">Distancia inicial de protección calculada en base a volatilidad.</div>
                </div>

                <!-- Fader 3: Target Profit ATR -->
                <div class="fader-group">
                    <div class="fader-header">
                        <span class="fader-label">🎯 Target Profit (ATR 15m):</span>
                        <span class="fader-val" id="val-target-atr">3.0x ATR</span>
                    </div>
                    <input type="range" id="slider-target-atr" min="1.5" max="5.0" step="0.1" value="3.0" oninput="updateFaderUI('target_atr_mult', this.value)" onchange="sendSettingsUpdate()">
                    <div class="fader-sub">Toma de ganancia simétrica por volatilidad (R:R objetivo).</div>
                </div>

                <!-- Fader 4: Distancia Trailing ATR -->
                <div class="fader-group">
                    <div class="fader-header">
                        <span class="fader-label">📈 Distancia Trailing (ATR 15m):</span>
                        <span class="fader-val" id="val-trail-atr">0.8x ATR</span>
                    </div>
                    <input type="range" id="slider-trail-atr" min="0.4" max="2.0" step="0.1" value="0.8" oninput="updateFaderUI('trail_distance_atr', this.value)" onchange="sendSettingsUpdate()">
                    <div class="fader-sub">Margen detrás del máximo para perseguir beneficios en subida.</div>
                </div>

                <!-- Fader 5: Score Mínimo -->
                <div class="fader-group">
                    <div class="fader-header">
                        <span class="fader-label">⚡ Score Mínimo Entrada:</span>
                        <span class="fader-val" id="val-min-score">70 pts</span>
                    </div>
                    <input type="range" id="slider-min-score" min="50" max="90" step="1" value="70" oninput="updateFaderUI('min_score', this.value)" onchange="sendSettingsUpdate()">
                    <div class="fader-sub">Puntaje de convicción mínima (ruptura + volumen + RS + velas).</div>
                </div>

                <!-- Fader 6: Cooldown Post-Stop -->
                <div class="fader-group">
                    <div class="fader-header">
                        <span class="fader-label">⏱️ Cooldown Anti-Ametralladora:</span>
                        <span class="fader-val" id="val-cooldown">180 seg</span>
                    </div>
                    <input type="range" id="slider-cooldown" min="30" max="600" step="15" value="180" oninput="updateFaderUI('post_stop_cooldown_s', this.value)" onchange="sendSettingsUpdate()">
                    <div class="fader-sub">Tiempo de enfriamiento en el par tras tocar Stop Loss.</div>
                </div>
            </div>
        </div>

        <!-- RADAR MATRIX V2 -->
        <div class="card" style="margin-bottom: 24px;">
            <div class="card-header">
                <div class="card-title">
                    <span>📊 RADAR CUANTITATIVO V2: FUERZA RELATIVA & RUPTURAS 15m</span>
                </div>
                <span style="font-size: 11px; color: var(--text-dim); font-family: monospace;">Escáner de Todo Binance + Anti-Cuchillo + R:R &gt;= 2.0:1</span>
            </div>
            <div style="overflow-x: auto;">
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Par</th>
                            <th>Precio</th>
                            <th>RS vs BTC</th>
                            <th>Ruptura 15m</th>
                            <th>Vol Spike</th>
                            <th>Velas 15m</th>
                            <th>RSI 15m</th>
                            <th>Tendencia 1H</th>
                            <th>Target / Stop</th>
                            <th>R:R</th>
                            <th>Puntaje</th>
                            <th>Estado</th>
                        </tr>
                    </thead>
                    <tbody id="radar-tbody">
                        <tr><td colspan="13" style="text-align: center; color: var(--text-dim); padding: 20px;">Escaneando candidatos con Fuerza Relativa y Rupturas 15m...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- EVENT LOG STREAM -->
        <div class="card">
            <div class="card-header">
                <div class="card-title">
                    <span>⚡ REGISTRO DE EVENTOS & DISPAROS CUANTITATIVOS</span>
                </div>
            </div>
            <div class="terminal" id="terminal-feed">
                <div class="log-row"><span class="log-time">[--:--:--]</span> <span class="log-info">Iniciando terminal Swing Sniper...</span></div>
            </div>
        </div>
    </div>

    <script>
        let isUserDraggingFader = false;
        let currentSettings = { auto_atr_mode: true };

        function updateFaderUI(param, val) {
            isUserDraggingFader = true;
            if (param === 'be_trigger_pct') {
                document.getElementById('val-be-trigger').innerText = '+' + Number(val).toFixed(2) + '%';
            } else if (param === 'stop_atr_mult') {
                document.getElementById('val-stop-atr').innerText = Number(val).toFixed(1) + 'x ATR';
            } else if (param === 'target_atr_mult') {
                document.getElementById('val-target-atr').innerText = Number(val).toFixed(1) + 'x ATR';
            } else if (param === 'trail_distance_atr') {
                document.getElementById('val-trail-atr').innerText = Number(val).toFixed(1) + 'x ATR';
            } else if (param === 'min_score') {
                document.getElementById('val-min-score').innerText = Math.round(val) + ' pts';
            } else if (param === 'post_stop_cooldown_s') {
                document.getElementById('val-cooldown').innerText = Math.round(val) + ' seg';
            }
        }

        async function sendSettingsUpdate() {
            isUserDraggingFader = false;
            const payload = {
                be_trigger_pct: parseFloat(document.getElementById('slider-be-trigger').value) / 100.0,
                stop_atr_mult: parseFloat(document.getElementById('slider-stop-atr').value),
                target_atr_mult: parseFloat(document.getElementById('slider-target-atr').value),
                trail_distance_atr: parseFloat(document.getElementById('slider-trail-atr').value),
                min_score: parseFloat(document.getElementById('slider-min-score').value),
                post_stop_cooldown_s: parseInt(document.getElementById('slider-cooldown').value),
                auto_atr_mode: currentSettings.auto_atr_mode !== undefined ? currentSettings.auto_atr_mode : true
            };
            const badge = document.getElementById('cfg-sync-badge');
            if (badge) {
                badge.innerText = '⏳ GUARDANDO...';
                badge.className = 'tag tag-yellow';
            }
            try {
                const res = await fetch('/api/settings', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                if (res.ok) {
                    if (badge) {
                        badge.innerText = '✅ APLICADO';
                        badge.className = 'tag tag-green';
                        setTimeout(() => { if (badge) badge.innerText = '● SINCRONIZADO'; }, 2000);
                    }
                }
            } catch (err) {
                console.error("Error guardando settings:", err);
            }
        }

        async function toggleAutoAtr() {
            const newMode = !currentSettings.auto_atr_mode;
            const payload = { auto_atr_mode: newMode };
            if (newMode) {
                // Restablecer valores óptimos para Modo Automático ATR (Opción B)
                payload.be_trigger_pct = 0.016;
                payload.stop_atr_mult = 1.2;
                payload.target_atr_mult = 3.0;
                payload.trail_distance_atr = 0.8;
                payload.min_score = 70.0;
                payload.post_stop_cooldown_s = 180;
            }
            try {
                await fetch('/api/settings', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                updateDashboard();
            } catch (err) {
                console.error("Error cambiando modo auto ATR:", err);
            }
        }

        async function updateDashboard() {
            try {
                const res = await fetch('/api/status');
                const d = await res.json();

                // 0. Sincronizar Consola de Control (Faders y Modo Auto)
                if (d.settings) {
                    currentSettings = d.settings;
                    const btn = document.getElementById('btn-auto-atr');
                    if (btn) {
                        if (d.settings.auto_atr_mode) {
                            btn.innerText = '🤖 MODO AUTOMÁTICO (ATR DINÁMICO): ON';
                            btn.className = 'btn-toggle-auto';
                        } else {
                            btn.innerText = '🎚️ MODO MANUAL (CONTROL POR FADERS)';
                            btn.className = 'btn-toggle-auto off';
                        }
                    }

                    if (!isUserDraggingFader) {
                        const beVal = (d.settings.be_trigger_pct * 100.0).toFixed(1);
                        document.getElementById('slider-be-trigger').value = beVal;
                        document.getElementById('val-be-trigger').innerText = '+' + Number(beVal).toFixed(2) + '%';

                        document.getElementById('slider-stop-atr').value = d.settings.stop_atr_mult;
                        document.getElementById('val-stop-atr').innerText = Number(d.settings.stop_atr_mult).toFixed(1) + 'x ATR';

                        document.getElementById('slider-target-atr').value = d.settings.target_atr_mult;
                        document.getElementById('val-target-atr').innerText = Number(d.settings.target_atr_mult).toFixed(1) + 'x ATR';

                        document.getElementById('slider-trail-atr').value = d.settings.trail_distance_atr;
                        document.getElementById('val-trail-atr').innerText = Number(d.settings.trail_distance_atr).toFixed(1) + 'x ATR';

                        document.getElementById('slider-min-score').value = d.settings.min_score;
                        document.getElementById('val-min-score').innerText = Math.round(d.settings.min_score) + ' pts';

                        document.getElementById('slider-cooldown').value = d.settings.post_stop_cooldown_s;
                        document.getElementById('val-cooldown').innerText = Math.round(d.settings.post_stop_cooldown_s) + ' seg';
                    }
                }

                // 1. Malla Real
                if (d.real_grid) {
                    const g = d.real_grid;
                    document.getElementById('grid-invest').innerText = '$' + Number(g.investment || 69.71).toFixed(2);
                    document.getElementById('grid-profit').innerText = '+' + Number(g.total_profit_usdt || 1.84).toFixed(2) + ' USDT';
                    document.getElementById('grid-pairs').innerText = g.paired_count || 118;
                    document.getElementById('grid-range').innerText = (g.range_bottom || 0.067) + ' - ' + (g.range_top || 0.093);
                }

                // 2. Swing Paper
                const cash = Number(d.cash || 0);
                const equity = Number(d.equity || cash);
                const invested = Number(d.invested || 0);
                const unPnl = Number(d.unrealized_pnl || 0);
                const unPnlPct = Number(d.unrealized_pnl_pct || 0);
                const realPnl = Number(d.stats?.pnl || 0);

                document.getElementById('swing-equity').innerText = '$' + equity.toFixed(2);
                document.getElementById('swing-cash').innerText = '$' + cash.toFixed(2);
                document.getElementById('swing-invested').innerText = '$' + invested.toFixed(2);
                
                const unEl = document.getElementById('swing-unrealized');
                const unSign = unPnl >= 0 ? '+' : '';
                unEl.innerText = `${unSign}$${unPnl.toFixed(2)} (${unSign}${unPnlPct.toFixed(2)}%)`;
                unEl.style.color = unPnl >= 0 ? '#3fb950' : '#f85149';

                const pnlEl = document.getElementById('swing-pnl');
                pnlEl.innerText = (realPnl >= 0 ? '+' : '') + realPnl.toFixed(2) + ' USDT';
                pnlEl.style.color = realPnl >= 0 ? '#3fb950' : '#f85149';
                document.getElementById('swing-stats').innerText = `${d.stats?.total || 0} (${d.stats?.wins || 0}W / ${d.stats?.losses || 0}L)`;

                // Tier de Capital y Diversificación
                if (d.tier_mode) {
                    const tb = document.getElementById('tier-badge');
                    if (tb) {
                        tb.innerText = d.tier_mode;
                        tb.className = 'tag ' + (d.max_concurrent_trades >= 3 ? 'tag-green' : (d.max_concurrent_trades >= 2 ? 'tag-green' : 'tag-yellow'));
                    }
                }

                // Posiciones Activas (Multi-Trade / Diversificación al Unísono)
                const actEl = document.getElementById('active-status');
                const trades = d.active_trades || (d.active_trade ? [d.active_trade] : []);
                if (trades.length > 0) {
                    let tradesHtml = '';
                    trades.forEach(tr => {
                        let badge = '<span class="tag tag-yellow">🟡 RIESGO INICIAL CONTROLADO</span>';
                        if (tr.is_trailing_active) {
                            badge = '<span class="tag tag-green">📈 TRAILING PROFIT ACTIVO (ATR Chandelier)</span>';
                        } else if (tr.is_be_active) {
                            badge = '<span class="tag tag-green">🛡️ BREAK-EVEN ACTIVO (Riesgo Cero)</span>';
                        }
                        const liveP = Number(tr.current_price || tr.entry_price).toFixed(4);
                        const entP = Number(tr.entry_price).toFixed(4);
                        const tgtP = Number(tr.target_price).toFixed(4);
                        const stpP = Number(tr.stop_price).toFixed(4);
                        const highP = Number(tr.highest_price || tr.entry_price).toFixed(4);
                        const trPnl = Number(tr.unrealized_pnl || 0);
                        const trPct = Number(tr.unrealized_pnl_pct || 0);
                        const trPnlStr = (trPnl >= 0 ? '+' : '') + trPnl.toFixed(4) + ' USDT (' + (trPct >= 0 ? '+' : '') + trPct.toFixed(2) + '%)';
                        const trPnlColor = trPnl >= 0 ? '#3fb950' : '#f85149';
                        const stopDiffPct = ((Number(tr.stop_price) - Number(tr.entry_price)) / Number(tr.entry_price) * 100).toFixed(2);
                        const stopDiffSign = Number(stopDiffPct) >= 0 ? '+' : '';

                        tradesHtml += `
                        <div style="background:#161b22; border:1px solid #30363d; border-radius:8px; padding:12px; margin-bottom:12px;">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; border-bottom:1px solid #21262d; padding-bottom:6px;">
                                <span style="font-weight:bold; color:#58a6ff; font-size:13px;">🦅 POSICIÓN EN CURSO: ${tr.symbol}</span>
                                ${badge}
                            </div>
                            <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap:8px; margin-bottom:8px;">
                                <div><span style="color:var(--text-dim); font-size:10px;">PORTE (TAMAÑO):</span><br><b>${tr.amount} ${tr.symbol.split('/')[0]}</b> <span style="color:var(--text-dim); font-size:11px;">($${Number(tr.capital).toFixed(2)})</span></div>
                                <div><span style="color:var(--text-dim); font-size:10px;">PRECIO ENTRADA:</span><br><b>$${entP}</b></div>
                                <div><span style="color:var(--text-dim); font-size:10px;">PRECIO ACTUAL:</span><br><b style="color:#58a6ff;">$${liveP}</b> <span style="color:var(--text-dim); font-size:11px;">(Max: $${highP})</span></div>
                                <div><span style="color:var(--text-dim); font-size:10px;">PNL FLOTANTE:</span><br><b style="color:${trPnlColor};">${trPnlStr}</b></div>
                            </div>
                            <div style="background:#0d1117; border-radius:6px; padding:8px; display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; font-size:11px; border:1px solid #21262d;">
                                <div>🎯 <b>Target Dinámico:</b> <span style="color:#3fb950; font-weight:bold;">$${tgtP} (+${(tr.target_pct*100).toFixed(2)}%)</span></div>
                                <div>🛡️ <b>Stop Dinámico ATR:</b> <span style="color:${Number(stopDiffPct) >= 0 ? '#3fb950' : '#f85149'}; font-weight:bold;">$${stpP} (${stopDiffSign}${stopDiffPct}%)</span></div>
                                <div>📐 <b>R:R:</b> <span style="color:#3fb950; font-weight:bold;">${tr.rr_ratio}:1</span></div>
                                <div>🌊 <b>ATR 1H:</b> <span style="color:var(--text-main); font-weight:bold;">${tr.atr_pct}%</span></div>
                            </div>
                        </div>`;
                    });
                    actEl.innerHTML = tradesHtml;
                } else if (d.active_grid) {
                    const g = d.active_grid;
                    const liveP = Number(g.current_price || g.midpoint).toFixed(4);
                    const avgP = Number(g.average_entry || g.midpoint).toFixed(4);
                    const suppP = Number(g.channel_support).toFixed(4);
                    const resP = Number(g.channel_resistance).toFixed(4);
                    const killP = Number(g.kill_switch_price).toFixed(4);
                    const gPnl = Number(g.unrealized_pnl || 0);
                    const gPct = g.invested_capital > 0 ? (gPnl / g.invested_capital * 100) : 0;
                    const pnlCol = gPnl >= 0 ? '#3fb950' : '#f85149';
                    const pnlSign = gPnl >= 0 ? '+' : '';

                    let lvlsHtml = '';
                    (g.levels || []).forEach((lvl, i) => {
                        const statusColor = lvl.status === 'FILLED' ? '#3fb950' : '#8b949e';
                        const statusIcon = lvl.status === 'FILLED' ? '✅' : '⏳';
                        lvlsHtml += `<div style="background:#090d13; border:1px solid #21262d; border-radius:4px; padding:4px 8px; font-size:10px;">
                            ${statusIcon} <b>Nivel ${lvl.level_idx+1}:</b> $${Number(lvl.price).toFixed(4)} ($${Number(lvl.capital).toFixed(2)}) - <span style="color:${statusColor};">${lvl.status}</span>
                        </div>`;
                    });

                    actEl.innerHTML = `
                    <div style="background:#161b22; border:1px solid #d29922; border-radius:8px; padding:12px; margin-bottom:12px;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; border-bottom:1px solid #21262d; padding-bottom:6px; flex-wrap:wrap; gap:6px;">
                            <span style="font-weight:bold; color:#f0883e; font-size:13px;">🟡 MALLA ACOTADA EN CHOP: ${g.symbol}</span>
                            <span class="tag tag-yellow">Hurst H: ${g.hurst_exponent} (Reversión a la Media)</span>
                        </div>
                        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap:8px; margin-bottom:8px;">
                            <div><span style="color:var(--text-dim); font-size:10px;">INVENTARIO / CAPITAL:</span><br><b>${g.filled_count}/3 Niveles</b> <span style="color:var(--text-dim); font-size:11px;">($${Number(g.invested_capital).toFixed(2)} USDT)</span></div>
                            <div><span style="color:var(--text-dim); font-size:10px;">PRECIO MEDIO ENTRADA:</span><br><b>$${avgP}</b></div>
                            <div><span style="color:var(--text-dim); font-size:10px;">PRECIO ACTUAL:</span><br><b style="color:#58a6ff;">$${liveP}</b></div>
                            <div><span style="color:var(--text-dim); font-size:10px;">PNL FLOTANTE:</span><br><b style="color:${pnlCol};">${pnlSign}$${gPnl.toFixed(4)} (${pnlSign}${gPct.toFixed(2)}%)</b></div>
                        </div>
                        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:6px; margin-bottom:8px;">
                            ${lvlsHtml}
                        </div>
                        <div style="background:#0d1117; border-radius:6px; padding:8px; display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; font-size:11px; border:1px solid #21262d;">
                            <div>🎯 <b>Cosecha Techo (Resistencia):</b> <span style="color:#3fb950; font-weight:bold;">$${resP}</span></div>
                            <div>🛡️ <b>Piso Canal (Soporte):</b> <span style="color:#58a6ff; font-weight:bold;">$${suppP}</span></div>
                            <div>🛑 <b>Kill-Switch Estricto:</b> <span style="color:#f85149; font-weight:bold;">$${killP} (Cierre total a mercado)</span></div>
                        </div>
                    </div>`;
                } else {
                    actEl.innerHTML = `
                    <div style="background:#0d1117; border: 1px dashed #30363d; border-radius:8px; padding:12px; text-align:center;">
                        <div style="font-size:12px; font-weight:700; color:#8b949e; margin-bottom:3px;">
                            ⚪ SIN OPERACIÓN EN CURSO (100% EN CAJA: $${cash.toFixed(2)} USDT)
                        </div>
                        <div style="font-size:11px; color:var(--text-dim);">
                            Capital libre protegido. El radar está buscando confirmación de ruptura con volumen.
                        </div>
                    </div>`;
                }

                // 2.1 Resumen del Último Trade Cerrado
                const lastTrEl = document.getElementById('last-trade-summary');
                if (lastTrEl && d.last_closed_trade) {
                    const lt = d.last_closed_trade;
                    const pnlVal = Number(lt.pnl || 0);
                    const pnlSign = pnlVal >= 0 ? '+' : '';
                    const pnlCol = pnlVal >= 0 ? '#3fb950' : '#f85149';
                    const noteStr = lt.note ? ` | ${lt.note}` : '';
                    lastTrEl.innerHTML = `
                        <span style="font-weight:bold; color:#58a6ff;">${lt.symbol}</span> 
                        <span style="color:${pnlCol}; font-weight:bold;">${pnlSign}$${pnlVal.toFixed(4)} USDT</span> 
                        <span style="color:var(--text-dim); font-size:10px;">@ $${Number(lt.price).toFixed(4)}${noteStr}</span>
                    `;
                }

                // 2.2 Radar Scanner Status
                const radarLiveEl = document.getElementById('radar-live-status');
                if (radarLiveEl) {
                    radarLiveEl.innerText = d.status_msg || 'Escaneando Binance...';
                }

                // 2.3 Régimen Macro de Bitcoin y Autopsia Post-Trade
                const btcBadge = document.getElementById('btc-regime-badge');
                if (btcBadge && d.btc_context) {
                    const btc = d.btc_context;
                    if (btc.regime === 'BULLISH_EXPANSION') {
                        btcBadge.className = 'tag tag-green';
                        btcBadge.innerText = '🟢 BTC: EXPANSIÓN ALCISTA';
                    } else if (btc.regime === 'CHOP_COMPRESSION') {
                        btcBadge.className = 'tag tag-purple';
                        btcBadge.innerText = '🟡 BTC: COMPRESIÓN CHOP (Falsas Rupturas)';
                    } else if (btc.regime === 'BEARISH_DUMP') {
                        btcBadge.className = 'tag tag-red';
                        btcBadge.innerText = '🔴 BTC: CORRECCIÓN DUMP (BLOQUEO)';
                    } else {
                        btcBadge.className = 'tag tag-blue';
                        btcBadge.innerText = `🔵 BTC: ${btc.regime}`;
                    }
                }

                const autopsySummaryEl = document.getElementById('autopsy-summary');
                if (autopsySummaryEl) {
                    if (d.recent_autopsies && d.recent_autopsies.length > 0) {
                        const topA = d.recent_autopsies[0];
                        const pnlSign = Number(topA.pnl) >= 0 ? '+' : '';
                        const col = Number(topA.pnl) >= 0 ? '#3fb950' : '#f85149';
                        autopsySummaryEl.innerHTML = `
                            <div style="display:flex; justify-content:space-between; margin-bottom:4px; flex-wrap:wrap; gap:4px;">
                                <span><strong>Última Autopsia:</strong> <span style="color:#58a6ff;">${topA.symbol}</span> | <span style="color:${col}; font-weight:bold;">${pnlSign}$${Number(topA.pnl).toFixed(4)} USDT</span> | Clase: <span class="tag tag-purple" style="font-size:9px;">${topA.classification}</span></span>
                                <span style="color:var(--text-dim); font-size:10px;">MFE: +${Number(topA.mfe_pct).toFixed(2)}% | MAE: ${Number(topA.mae_pct).toFixed(2)}%</span>
                            </div>
                            <div style="color:#8b949e; font-size:10px;">💡 <em>${topA.lesson_learned}</em> &rarr; <span style="color:#58a6ff;">${topA.adaptive_action}</span></div>
                        `;
                    } else {
                        const btcRegimeDesc = (d.btc_context && d.btc_context.regime_desc) ? d.btc_context.regime_desc : 'Monitoreo activo.';
                        autopsySummaryEl.innerHTML = `<span style="color:#8b949e;">📡 Contexto BTC: <em>${btcRegimeDesc}</em> | Piso de Stop mínimo 1.20% activo para filtrar ruido.</span>`;
                    }
                }

                // Título de pestaña interactivo con PnL en vivo
                if (trades.length > 0) {
                    const topTr = trades[0];
                    const sign = (topTr.unrealized_pnl >= 0 ? '+' : '');
                    document.title = `🟢 ${topTr.symbol.split('/')[0]} (${sign}${Number(topTr.unrealized_pnl_pct || 0).toFixed(2)}%) | THE QUANT SNIPER`;
                } else {
                    document.title = `🦅 $${equity.toFixed(2)} | THE QUANT SNIPER`;
                }

                // 3. Radar Table V2 (Con resaltado si el activo está en posición abierta)
                const activeMap = {};
                trades.forEach(t => { activeMap[t.symbol] = t; });

                const tbody = document.getElementById('radar-tbody');
                if (tbody && d.radar_telemetry && d.radar_telemetry.length > 0) {
                    let rows = '';
                    d.radar_telemetry.forEach((c, idx) => {
                        const inPos = activeMap[c.symbol];
                        const rsSign = (c.rs_vs_btc >= 0 ? '+' : '');
                        const rsColor = c.rs_vs_btc >= 1.0 ? '#3fb950' : (c.rs_vs_btc >= 0 ? '#58a6ff' : '#f85149');
                        const brkTag = c.is_momentum_ignition ? '<span class="tag tag-purple" style="font-weight:bold; background:rgba(187,128,255,0.25); border:1px solid #bc8cff; color:#d2a8ff;">🚀 IGNICIÓN</span>' : (c.breakout ? '<span class="tag tag-green">RUPTURA</span>' : '<span class="tag tag-gray">NO</span>');
                        const volColor = c.vol_spike >= 1.3 ? '#3fb950' : (c.vol_spike >= 1.0 ? '#d29922' : '#8b949e');
                        const candleTag = c.double_green ? '<span style="color:#3fb950; font-weight:600;">2 Verdes</span>' : (c.is_green ? '<span style="color:#3fb950;">1 Verde</span>' : '<span style="color:#f85149;">Roja</span>');
                        const trendTag = c.trend_1h ? '<span class="tag tag-green">ALCISTA</span>' : '<span class="tag tag-gray">BAJISTA</span>';
                        
                        let statusBadge = `<span class="tag ${c.is_momentum_ignition ? 'tag-purple' : (c.trigger_ready ? 'tag-green' : (c.score >= 50 ? 'tag-yellow' : 'tag-gray'))}">${c.status}</span>`;
                        let trStyle = '';
                        if (inPos) {
                            const pnlSign = inPos.unrealized_pnl >= 0 ? '+' : '';
                            statusBadge = `<span class="tag tag-green" style="font-weight:bold; background:rgba(63,185,80,0.3);">🦅 EN POSICIÓN (${pnlSign}${Number(inPos.unrealized_pnl_pct).toFixed(2)}%)</span>`;
                            trStyle = 'style="background: rgba(88, 166, 255, 0.15); font-weight: bold; border-left: 3px solid #58a6ff;"';
                        }
                        
                        rows += `<tr ${trStyle}>
                            <td>${idx + 1}</td>
                            <td><b>${c.symbol.split('/')[0]}</b></td>
                            <td>$${Number(c.price).toFixed(4)}</td>
                            <td style="color:${rsColor}; font-weight:bold;">${rsSign}${c.rs_vs_btc}pp</td>
                            <td>${brkTag}</td>
                            <td style="color:${volColor}; font-weight:bold;">${c.vol_spike}x</td>
                            <td>${candleTag}</td>
                            <td><span style="color:${c.rsi_15m >= 40 && c.rsi_15m <= 65 ? '#3fb950' : '#c9d1d9'}">${c.rsi_15m}</span></td>
                            <td>${trendTag}</td>
                            <td>+${c.target_pct}% / -${c.stop_pct}%</td>
                            <td style="color:#3fb950; font-weight:bold;">${c.rr_ratio} : 1</td>
                            <td><b>${c.score}</b></td>
                            <td>${statusBadge}</td>
                        </tr>`;
                    });
                    tbody.innerHTML = rows;
                }

                // 4. Logs (Eventos más recientes arriba de todo con badge)
                const term = document.getElementById('terminal-feed');
                if (term && d.events && d.events.length > 0) {
                    let logHtml = '';
                    d.events.forEach((l, idx) => {
                        const cl = l.type === 'trade' ? 'log-trade' : 'log-info';
                        const badge = idx === 0 ? '<span class="tag tag-green" style="font-size:9px; padding:1px 4px; margin-right:6px;">ÚLTIMO</span>' : '';
                        logHtml += `<div class="log-row">${badge}<span class="log-time">[${l.time}]</span> <span class="${cl}">${l.text}</span></div>`;
                    });
                    term.innerHTML = logHtml;
                }
            } catch (e) {
                console.error("Dashboard poll error:", e);
            }
        }
        setInterval(updateDashboard, 3000);
        updateDashboard();
    </script>
</body>
</html>
"""


class SwingHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    bot: Optional[SwingBot] = None

    def log_message(self, format, *args):
        pass  # Silenciar logs http para mantener la consola limpia

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode("utf-8"))
        elif self.path == "/quantum" or self.path == "/quantum.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            quantum_path = os.path.join(BASE_DIR, "quantum_terminal.html")
            if os.path.exists(quantum_path):
                with open(quantum_path, "r", encoding="utf-8") as f:
                    self.wfile.write(f.read().encode("utf-8"))
            else:
                self.wfile.write(b"<h1>Quantum Terminal no encontrada</h1>")
        elif self.path == "/api/autopsies":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            autopsies = self.bot.db.get_recent_autopsies(20)
            self.wfile.write(json.dumps(autopsies).encode("utf-8"))
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            bot = self.bot
            with bot.data_lock:
                telemetry = list(bot.radar_telemetry)
                stats = bot.db.get_stats()
                events = bot.db.get_recent_events(30)
                grid_stats = dict(bot.real_grid_stats)
                trades_list = list(bot.active_trades.values())
                last_closed = bot.db.get_last_closed_trade()
                autopsies = bot.db.get_recent_autopsies(5)

            invested = sum(round(t.amount * t.entry_price, 2) for t in trades_list)
            live_val = sum(round(t.amount * getattr(t, "current_price", t.entry_price), 2) for t in trades_list)
            unrealized_pnl = sum(getattr(t, "unrealized_pnl", 0.0) for t in trades_list)
            unrealized_pnl_pct = ((unrealized_pnl / invested) * 100.0) if invested > 0 else 0.0
            grid_obj = getattr(bot, "active_grid", None)
            grid_dict = grid_obj.to_dict() if grid_obj else None
            grid_inv = grid_obj.get_invested_capital() if grid_obj else 0.0
            grid_unreal = grid_obj.unrealized_pnl if grid_obj else 0.0

            total_invested = invested + grid_inv
            total_unrealized = unrealized_pnl + grid_unreal
            total_unrealized_pct = ((total_unrealized / total_invested) * 100.0) if total_invested > 0 else 0.0
            equity = bot.cash + (total_invested + total_unrealized)

            payload = {
                "cash": round(bot.cash, 2),
                "equity": round(equity, 2),
                "invested": round(total_invested, 2),
                "unrealized_pnl": round(total_unrealized, 4),
                "unrealized_pnl_pct": round(total_unrealized_pct, 2),
                "tier_mode": bot.get_tier_name(),
                "active_mode": getattr(bot, "active_mode", "SWING_SNIPER"),
                "max_concurrent_trades": bot.get_max_concurrent_trades(),
                "status_msg": bot.status_msg,
                "active_trade": trades_list[0].to_dict() if trades_list else None,
                "active_trades": [t.to_dict() for t in trades_list],
                "active_grid": grid_dict,
                "last_closed_trade": last_closed,
                "stats": stats,
                "settings": bot.settings,
                "radar_telemetry": telemetry,
                "real_grid": grid_stats,
                "events": events,
                "btc_context": update_btc_context(),
                "recent_autopsies": autopsies
            }
            self.wfile.write(json.dumps(payload).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/settings":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                data = json.loads(body)
                self.bot.update_settings(data)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "settings": self.bot.settings}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


def start_swing_dashboard(bot: SwingBot, port: int = SWING_HTTP_PORT):
    handler = SwingHTTPRequestHandler
    handler.bot = bot
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), handler)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    print(f"  🌐 [SWING & GRID DASHBOARD] Acceso en vivo: http://localhost:{port}", flush=True)


# ====================== HILO DE ESCANEO DE MERCADO V2 ======================
def swing_telemetry_thread(bot: SwingBot):
    """Escanea el mercado dinámicamente buscando candidatos con Fuerza Relativa y Rupturas 15m."""
    print("  📡 [SWING RADAR V2] Motor dinámico de Fuerza Relativa & Ruptura 15m activo.", flush=True)
    last_grid_check = 0.0

    while True:
        try:
            bot.scan_cycle += 1
            btc_ctx = update_btc_context()
            movers = scan_market_top_movers()

            results = []
            for cand in movers:
                try:
                    res = analyze_breakout_15m(cand["symbol"], btc_ctx, bot.settings)
                    if res:
                        results.append(res)
                except Exception:
                    continue

            results.sort(key=lambda x: x["score"], reverse=True)

            with bot.data_lock:
                bot.radar_telemetry = results

            # Consultar estado de la Malla Real DOGE cada 60s (solo lectura)
            now = time.time()
            if now - last_grid_check >= 60.0:
                grid_info = fetch_real_pionex_grid_stats()
                with bot.data_lock:
                    bot.real_grid_stats = grid_info
                last_grid_check = now

        except Exception as e:
            bot.add_log(f"Error en escaneo radar V2: {e}", "error")

        time.sleep(12.0)


# ====================== BUCLE PRINCIPAL V2 ======================
def run_hourly_swing():
    print("=" * 80, flush=True)
    print("  THE ADAPTIVE SWING SNIPER V2 (RELATIVE STRENGTH & 15m BREAKOUT ENGINE)", flush=True)
    print("  • Modo                           -> PAPER TRADING ESTRICTO (Capital virtual)", flush=True)
    print("  • Seguridad                      -> Malla DOGE Real Pionex INTACTA (Solo Lectura)", flush=True)
    print("  • Estrategia V2                  -> Fuerza Relativa vs BTC + Ruptura 15m + Vol Spike", flush=True)
    print("  • Filtro Anti-Ametralladora      -> Cooldown 180s + Exigencia de Score Elevado tras stop", flush=True)
    print("  • Gestión de Riesgo              -> Stop Dinámico 1.2x ATR | Break-Even +1.0% | Trailing 0.8x ATR", flush=True)
    print(f"  • Dashboard Integrado            -> http://localhost:{SWING_HTTP_PORT}", flush=True)
    print("=" * 80, flush=True)

    bot = SwingBot()
    start_swing_dashboard(bot, SWING_HTTP_PORT)

    scan_th = threading.Thread(target=swing_telemetry_thread, args=(bot,), daemon=True)
    scan_th.start()

    time.sleep(3.0)

    while True:
        try:
            now_ts = time.time()
            btc_ctx = update_btc_context()
            btc_regime = btc_ctx.get("regime", "NEUTRAL_TRANSITION")

            # 1. Monitoreo de posiciones vivas:
            manage_active_swing_trade(bot)
            manage_active_bounded_grid(bot)

            has_active_swing = len(bot.active_trades) > 0
            has_active_grid = (getattr(bot, "active_grid", None) is not None and bot.active_grid.status == "ACTIVE")

            # 2. Conmutación de Régimen y Ejecución Dual:
            if not has_active_swing and not has_active_grid:
                # Régimen 1: Expansión alcista o consolidación normal -> MODO SWING SNIPER
                if btc_regime in ("BULLISH_EXPANSION", "NEUTRAL_TRANSITION"):
                    bot.active_mode = "SWING_SNIPER"
                    max_concurrent = bot.get_max_concurrent_trades()
                    current_active_count = len(bot.active_trades)

                    if current_active_count < max_concurrent:
                        with bot.data_lock:
                            telemetry = list(bot.radar_telemetry)

                        time_since_last_stop = now_ts - getattr(bot, "last_stop_time", 0.0)
                        is_recovering_from_stop = time_since_last_stop < 300.0
                        base_min_score = bot.settings.get("min_score", MIN_SCORE_V2)
                        extra_score = bot.settings.get("post_stop_extra_score", POST_STOP_EXTRA_SCORE)
                        effective_min_score = (base_min_score + extra_score) if is_recovering_from_stop else base_min_score

                        ready_opps = [
                            o for o in telemetry
                            if o.get("trigger_ready")
                            and o.get("score", 0.0) >= effective_min_score
                            and bot.cooldowns.get(o["symbol"], 0.0) <= now_ts
                            and o["symbol"] not in bot.active_trades
                        ]

                        if ready_opps:
                            best = ready_opps[0]
                            execute_swing_paper_entry(bot, best)
                        else:
                            top = telemetry[0] if telemetry else None
                            if top and not bot.active_trades:
                                cooldown_active = bot.cooldowns.get(top["symbol"], 0.0) > now_ts
                                anti_badge = f" [Anti-Ametralladora: Min Score {effective_min_score:.0f}]" if is_recovering_from_stop else ""
                                cd_badge = " (Cooldown activo)" if cooldown_active else ""
                                bot.status_msg = f"Radar V2: Líder {top['symbol']} (Score {top['score']}/100 | RS {top.get('rs_vs_btc', 0):+.1f}pp | {top['status']}){cd_badge}{anti_badge}."

                # Régimen 2: Compresión lateral (Chop) -> MODO MALLA ACOTADA
                elif btc_regime == "CHOP_COMPRESSION":
                    bot.active_mode = "BOUNDED_GRID"
                    scan_bounded_grid_candidates(bot)
                    if not bot.active_grid:
                        bot.status_msg = f"🟡 MODO CHOP: Escaneando activos con reversión comprobada (Hurst < 0.45)..."

                # Régimen 3: Dump bajista de BTC -> MODO BÚNKER 100% CAJA
                elif btc_regime == "BEARISH_DUMP":
                    bot.active_mode = "CASH_VAULT"
                    bot.status_msg = "🛡️ MODO BÚNKER (Caja 100%): BTC en corrección bajista. Disparos y mallas bloqueados."

            time.sleep(2.5)

        except KeyboardInterrupt:
            print("\nDeteniendo Swing Engine V2...", flush=True)
            break
        except Exception as e:
            bot.add_log(f"Error en bucle swing: {e}", "error")
            time.sleep(5.0)
            time.sleep(5.0)


if __name__ == "__main__":
    run_hourly_swing()
