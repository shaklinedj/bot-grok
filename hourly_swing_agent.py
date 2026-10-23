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

# Configuración por defecto (Calibración Óptima ATR - Opción B)
DEFAULT_SETTINGS = {
    "auto_atr_mode": True,               # Modo Automático ATR ON/OFF
    "be_trigger_pct": 0.016,             # +1.60% activa Break-Even (Opción B equilibrada)
    "be_stop_pct": 0.0020,               # +0.20% asegura comisiones en BE
    "stop_atr_mult": 1.2,                # Stop Loss: 1.2x ATR 15m
    "target_atr_mult": 3.0,              # Target: 3.0x ATR 15m (R:R ~ 2.5:1)
    "trail_distance_atr": 0.8,           # Trailing persigue el máximo menos 0.8x ATR
    "min_score": 70.0,                   # Score mínimo para disparo
    "vol_spike_min": 1.2,                # Pico de volumen mínimo (1.2x media)
    "post_stop_cooldown_s": 180,         # 3 minutos cooldown tras stop
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
            conn.commit()

    def log_trade(self, symbol: str, side: str, price: float, amount: float, capital: float,
                  pnl: float = 0.0, fee: float = 0.0, order_id: str = "",
                  target_price: float = 0.0, stop_price: float = 0.0, note: str = ""):
        ts = datetime.now().isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO trades (timestamp, symbol, side, price, amount, capital, pnl, fee, order_id, target_price, stop_price, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (ts, symbol, side, price, amount, capital, pnl, fee, order_id, target_price, stop_price, note))
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

    def get_recent_events(self, limit: int = 30) -> List[Dict]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT timestamp as time, event_type as type, message as text FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            res = [dict(r) for r in rows]
            res.reverse()
            return res

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


# ====================== MODELO DE DATOS SWING ======================
class SwingTrade:
    def __init__(self, trade_id: str, symbol: str, entry_price: float, amount: float,
                 capital: float, target_price: float, stop_price: float, initial_stop: float,
                 target_pct: float, stop_pct: float, atr_pct: float, rr_ratio: float,
                 entry_time: float, entry_fee: float = 0.0):
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
        self.is_be_active = False        # Break-Even Shield activado (+0.20%)
        self.is_trailing_active = False  # Trailing Stop ATR activado
        self.highest_price = entry_price
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
            "is_be_active": self.is_be_active,
            "is_trailing_active": self.is_trailing_active,
            "highest_price": self.highest_price,
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
            entry_fee=d.get("entry_fee", 0.0)
        )
        st.is_be_active = d.get("is_be_active", False)
        st.is_trailing_active = d.get("is_trailing_active", False)
        st.highest_price = d.get("highest_price", st.entry_price)
        st.current_price = d.get("current_price", st.entry_price)
        st.unrealized_pnl = d.get("unrealized_pnl", 0.0)
        st.unrealized_pnl_pct = d.get("unrealized_pnl_pct", 0.0)
        st.status = d.get("status", "OPEN")
        return st


# ====================== BOT SWING STATE & EXECUTION ======================
class SwingBot:
    def __init__(self, db_path: Optional[str] = None):
        self.db = SwingDatabase(db_path or SWING_DB_FILE)
        self.cash = PAPER_INITIAL_CAPITAL
        self.active_trades: Dict[str, SwingTrade] = {}
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
        """Calcula el patrimonio total en vivo: Caja disponible + Posiciones valoradas."""
        pos_val = sum(tr.amount * getattr(tr, "current_price", tr.entry_price) for tr in self.active_trades.values())
        return self.cash + pos_val

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
        except Exception as e:
            self.add_log(f"Error cargando estado desde SQLite: {e}", "error")

    def save_state(self):
        d = {
            "cash": self.cash,
            "active_trade": self.active_trade.to_dict() if self.active_trade else None,
            "active_trades": [t.to_dict() for t in self.active_trades.values()],
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
_btc_performance_cache = {"ts": 0.0, "change_1h": 0.0, "change_4h": 0.0, "trend_4h": "neutral"}


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
    """Actualiza el contexto macro de Bitcoin (se usa para Fuerza Relativa)."""
    global _btc_performance_cache
    now = time.time()
    if now - _btc_performance_cache["ts"] < 60:
        return _btc_performance_cache
    try:
        c_1h = fetch_ohlcv_cached("BTC/USDT", "1h", limit=6)
        c_4h = fetch_ohlcv_cached("BTC/USDT", "4h", limit=25)
        if len(c_1h) >= 2 and len(c_4h) >= 5:
            chg_1h = (c_1h[-1][4] - c_1h[-2][4]) / c_1h[-2][4] * 100.0
            chg_4h = (c_4h[-1][4] - c_4h[-5][4]) / c_4h[-5][4] * 100.0
            closes_4h = [c[4] for c in c_4h]
            ema20 = calc_ema(closes_4h, 20)
            trend = "bullish" if c_4h[-1][4] > ema20 else "bearish"
            _btc_performance_cache = {"ts": now, "change_1h": chg_1h, "change_4h": chg_4h, "trend_4h": trend}
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

    # --- Indicadores 15m ---
    atr_15m = calc_atr(c_15m, 14)
    atr_pct_15m = (atr_15m / curr_p * 100.0) if curr_p > 0 else 1.0
    rsi_15m = calc_rsi(closes_15m, 14)
    ema9_15m = calc_ema(closes_15m, 9)
    ema20_15m = calc_ema(closes_15m, 20)

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

    # --- Parámetros de Trade Dinámicos por ATR 15m ---
    stop_distance = stop_mult * atr_15m
    stop_pct = stop_distance / curr_p
    stop_price = round(curr_p - stop_distance, 6)
    target_distance = target_mult * atr_15m
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

    # Penalizaciones:
    if is_falling_knife:
        score -= 40.0
    if rsi_15m > 78.0:
        score -= 20.0  # Sobrecomprado extremo
    if rsi_1h > 78.0:
        score -= 15.0

    is_trigger_ready = (
        score >= min_score_target
        and breakout_confirmed
        and is_green
        and vol_spike >= 1.0
        and not is_falling_knife
        and rr_ratio >= 2.0
    )

    if is_trigger_ready:
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
        "stop_pct": round(stop_pct * 100.0, 2),
        "target_pct": round(target_pct * 100.0, 2),
        "stop_price": stop_price,
        "target_price": target_price,
        "rr_ratio": rr_ratio,
        "score": round(score, 1),
        "trigger_ready": is_trigger_ready,
        "status": status_str
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
        entry_fee=entry_fee
    )
    bot.active_trades[sym] = trade
    tier = bot.get_tier_name()
    rs_info = f"RS vs BTC: {opp.get('rs_vs_btc', 0):+.1f}pp"
    bot.add_log(f"🎯 DISPARO V2 #{order_id}: {sym} @ ${curr_p:.4f} | {rs_info} | Ruptura 15m + Vol {opp.get('vol_spike', 0):.1f}x | ${trade_capital:.2f} USDT | Target: ${target_p:.4f} (+{target_pct*100:.2f}%) | Stop: ${stop_p:.4f} (-{stop_pct*100:.2f}%) | R:R {rr}:1", "trade")
    bot.db.log_trade(
        symbol=sym, side="BUY", price=curr_p, amount=amount, capital=trade_capital,
        pnl=0.0, fee=entry_fee, order_id=order_id, target_price=target_p, stop_price=stop_p,
        note=f"V2 Entry #{order_id} (R:R {rr}:1 | ATR 15m {atr_p:.2f}% | RS {opp.get('rs_vs_btc', 0):+.1f}pp)"
    )
    bot.save_state()


def manage_active_swing_trade(bot: SwingBot):
    """V2: Monitorea trades activos con Trailing Ágil basado en ATR 15m."""
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
        tr.unrealized_pnl = (curr_p - tr.entry_price) * tr.amount
        tr.unrealized_pnl_pct = gain_pct * 100.0

        atr_val_abs = tr.entry_price * (tr.atr_pct / 100.0)

        # 1. Break-Even: Dinámico por ATR o Manual según calibración en faders
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

        # 2. Trailing Ágil: Desde +1.5x ATR 15m, persigue el máximo menos distancia ATR configurada
        trail_dist_mult = getattr(bot, "settings", {}).get("trail_distance_atr", 0.8)
        trailing_trigger = (tr.atr_pct / 100.0) * 1.5
        if gain_pct >= trailing_trigger:
            trail_stop = round(tr.highest_price - (trail_dist_mult * atr_val_abs), 6)
            if trail_stop > tr.stop_price:
                old_stop = tr.stop_price
                tr.stop_price = trail_stop
                tr.is_trailing_active = True
                bot.add_log(f"📈 TRAILING ÁGIL en {sym}: Max ${tr.highest_price:.4f}. Stop ${old_stop:.4f} -> ${trail_stop:.4f} ({trail_dist_mult}x ATR)", "trade")
                bot.save_state()

        # 3. Cierre por Target:
        if curr_p >= tr.target_price:
            gross_pnl = (tr.target_price - tr.entry_price) * tr.amount
            exit_fee = (tr.target_price * tr.amount) * FEE_RATE
            net_pnl = gross_pnl - tr.entry_fee - exit_fee
            bot.cash += (tr.capital + net_pnl)
            bot.add_log(f"🏆 TARGET V2 en {sym}: ${tr.target_price:.4f} | PnL: +${net_pnl:.4f} USDT (+{tr.target_pct*100:.2f}%)", "trade")
            bot.db.log_trade(
                symbol=sym, side="SELL", price=tr.target_price, amount=tr.amount, capital=tr.capital,
                pnl=net_pnl, fee=exit_fee, order_id=tr.trade_id, target_price=tr.target_price, stop_price=tr.stop_price,
                note=f"🏆 TARGET V2 (+{tr.target_pct*100:.2f}%)"
            )
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
            <div style="display: flex; gap: 10px; align-items: center;">
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
                <div id="active-box" style="background: #0d1117; border: 1px dashed var(--border); border-radius: 8px; padding: 14px; font-family: monospace; font-size: 12px;">
                    <div id="active-status" style="color: var(--text-dim);">Sin posición Swing activa. Escaneando retrocesos con descuento en 1H...</div>
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
                } else {
                    actEl.innerHTML = `<span style="color:var(--text-dim);">${d.status_msg || 'Sin posición activa. Buscando retrocesos de alta probabilidad...'}</span>`;
                }

                // 3. Radar Table V2
                const tbody = document.getElementById('radar-tbody');
                if (tbody && d.radar_telemetry && d.radar_telemetry.length > 0) {
                    let rows = '';
                    d.radar_telemetry.forEach((c, idx) => {
                        const rsSign = (c.rs_vs_btc >= 0 ? '+' : '');
                        const rsColor = c.rs_vs_btc >= 1.0 ? '#3fb950' : (c.rs_vs_btc >= 0 ? '#58a6ff' : '#f85149');
                        const brkTag = c.breakout ? '<span class="tag tag-green">RUPTURA</span>' : '<span class="tag tag-gray">NO</span>';
                        const volColor = c.vol_spike >= 1.3 ? '#3fb950' : (c.vol_spike >= 1.0 ? '#d29922' : '#8b949e');
                        const candleTag = c.double_green ? '<span style="color:#3fb950; font-weight:600;">2 Verdes</span>' : (c.is_green ? '<span style="color:#3fb950;">1 Verde</span>' : '<span style="color:#f85149;">Roja</span>');
                        const trendTag = c.trend_1h ? '<span class="tag tag-green">ALCISTA</span>' : '<span class="tag tag-gray">BAJISTA</span>';
                        const statusClass = c.trigger_ready ? 'tag-green' : (c.score >= 50 ? 'tag-yellow' : 'tag-gray');
                        
                        rows += `<tr>
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
                            <td><span class="tag ${statusClass}">${c.status}</span></td>
                        </tr>`;
                    });
                    tbody.innerHTML = rows;
                }

                // 4. Logs
                const term = document.getElementById('terminal-feed');
                if (term && d.events && d.events.length > 0) {
                    let logHtml = '';
                    d.events.forEach(l => {
                        const cl = l.type === 'trade' ? 'log-trade' : 'log-info';
                        logHtml += `<div class="log-row"><span class="log-time">[${l.time}]</span> <span class="${cl}">${l.text}</span></div>`;
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

            invested = sum(round(t.amount * t.entry_price, 2) for t in trades_list)
            live_val = sum(round(t.amount * getattr(t, "current_price", t.entry_price), 2) for t in trades_list)
            unrealized_pnl = sum(getattr(t, "unrealized_pnl", 0.0) for t in trades_list)
            unrealized_pnl_pct = ((unrealized_pnl / invested) * 100.0) if invested > 0 else 0.0
            equity = bot.cash + (invested + unrealized_pnl)

            payload = {
                "cash": round(bot.cash, 2),
                "equity": round(equity, 2),
                "invested": round(invested, 2),
                "unrealized_pnl": round(unrealized_pnl, 4),
                "unrealized_pnl_pct": round(unrealized_pnl_pct, 2),
                "tier_mode": bot.get_tier_name(),
                "max_concurrent_trades": bot.get_max_concurrent_trades(),
                "status_msg": bot.status_msg,
                "active_trade": trades_list[0].to_dict() if trades_list else None,
                "active_trades": [t.to_dict() for t in trades_list],
                "stats": stats,
                "settings": bot.settings,
                "radar_telemetry": telemetry,
                "real_grid": grid_stats,
                "events": events
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

            manage_active_swing_trade(bot)

            # Verificar si hay cupo para abrir trades (según tier de capital y diversificación)
            max_concurrent = bot.get_max_concurrent_trades()
            current_active_count = len(bot.active_trades)

            if current_active_count < max_concurrent:
                with bot.data_lock:
                    telemetry = list(bot.radar_telemetry)

                # Anti-Ametralladora: Si hubo un stop loss en los últimos 300 segundos, exigir score extra
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
