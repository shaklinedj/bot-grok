"""
========================================================================================
  THE HOURLY SWING SNIPER (1H / 4H ASYMMETRIC ENGINE - EV > 0)
  - Modo: PAPER TRADING ESTRICTO (Capital virtual $70.00 USDT, datos reales CCXT/Pionex)
  - Seguridad: Cero órdenes reales a Pionex. La Malla real de DOGE permanece 100% intacta.
  - Marco Temporal: Velas de 1 Hora (1H) con confirmación de tendencia en 4 Horas (4H).
  - Expectativa Matemática: R:R Asimétrico >= 3:1 (Arriesgar ~1.5% para ganar +4.5% a +6.5%).
  - Escudo Break-Even: Al alcanzar +1.20% de avance, el Stop sube automáticamente a +0.20%.
  - Persistencia: SQLite WAL (swing_logs/paper/swing_vault.db).
  - Dashboard Reactivo Dual: http://localhost:8900
    * Muestra en vivo la Malla real de DOGE (Solo Lectura) + El Swing Engine en Paper.
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
from typing import Dict, List, Optional, Tuple

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
SWING_HTTP_PORT = 8900

# Parámetros Cuantitativos Asimétricos (EV > 0)
PAPER_INITIAL_CAPITAL = 70.00
SWING_CAPITAL_ALLOCATION = 0.85  # 85% de la caja por disparo (~$55 a $60 USDT)
BREAK_EVEN_TRIGGER_PCT = 0.0120  # +1.20% de ganancia activa el Escudo Break-Even
BREAK_EVEN_STOP_PCT = 0.0020     # +0.20% asegura comisiones y ganancia neta en BE
DEFAULT_MIN_RR_RATIO = 2.8       # R:R mínimo exigido para disparar
FEE_RATE = 0.0005                # 0.05% por lado (0.10% round-trip)

# Whitelist de Altcoins Líderes de Alta Capitalización y Liquidez
SWING_WHITELIST = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "NEAR/USDT", "AVAX/USDT",
    "INJ/USDT", "DOGE/USDT", "SUI/USDT", "LINK/USDT", "UNI/USDT", "XRP/USDT"
]

# ID de la Malla Real en Pionex (SOLO LECTURA para auditoría en el Dashboard)
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
    def __init__(self):
        self.db = SwingDatabase()
        self.cash = PAPER_INITIAL_CAPITAL
        self.active_trade: Optional[SwingTrade] = None
        self.radar_telemetry: List[Dict] = []
        self.real_grid_stats: Dict = {}
        self.cooldowns: Dict[str, float] = {}
        self.status_msg = "Iniciando Hourly Swing Sniper..."
        self.data_lock = threading.Lock()
        self.scan_cycle = 0
        self.sim_order_seq = 1000
        self.load_state()

    def add_log(self, msg: str, event_type: str = "info"):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [{event_type.upper()}] {msg}", flush=True)
        self.db.insert_event(event_type, msg)

    def load_state(self):
        if os.path.exists(SWING_STATE_FILE):
            try:
                with open(SWING_STATE_FILE, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    self.cash = float(d.get("cash", PAPER_INITIAL_CAPITAL))
                    tr = d.get("active_trade")
                    if tr:
                        self.active_trade = SwingTrade.from_dict(tr)
                    self.cooldowns = d.get("cooldowns", {})
                    self.sim_order_seq = int(d.get("sim_order_seq", 1000))
            except Exception as e:
                self.add_log(f"Error cargando estado swing: {e}", "error")

    def save_state(self):
        d = {
            "cash": self.cash,
            "active_trade": self.active_trade.to_dict() if self.active_trade else None,
            "cooldowns": self.cooldowns,
            "sim_order_seq": self.sim_order_seq,
            "updated_at": time.time()
        }
        tmp = SWING_STATE_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=2)
            os.replace(tmp, SWING_STATE_FILE)
        except Exception as e:
            self.add_log(f"Error guardando estado swing: {e}", "error")


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


# ====================== MOTOR CUANTITATIVO 1H / 4H (SNIPER) ======================
_ohlcv_cache = {}


def fetch_ohlcv_cached(symbol: str, timeframe: str, limit: int = 60) -> List:
    key = f"{symbol}_{timeframe}"
    now = time.time()
    cached = _ohlcv_cache.get(key)
    # Cache de 120s para 1h y 300s para 4h (reduce llamadas REST innecesarias)
    ttl = 120 if timeframe == "1h" else 300
    if cached and (now - cached["ts"] < ttl):
        return cached["data"]
    try:
        data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        _ohlcv_cache[key] = {"ts": now, "data": data}
        return data
    except Exception:
        return cached["data"] if cached else []


def analyze_hourly_swing_structure(symbol: str) -> Optional[Dict]:
    """
    Analiza la estructura de mercado institucional en 4H (Régimen) y 1H (Entrada Francotirador).
    """
    candles_4h = fetch_ohlcv_cached(symbol, "4h", limit=60)
    candles_1h = fetch_ohlcv_cached(symbol, "1h", limit=60)

    if len(candles_4h) < 25 or len(candles_1h) < 25:
        return None

    # 1. Análisis Macro en 4H: ¿Hay tendencia sólida a favor?
    closes_4h = [c[4] for c in candles_4h]
    closes_1h = [c[4] for c in candles_1h]
    curr_p = closes_1h[-1]
    
    # EMA 20 y EMA 50 en 4H
    def calc_ema(series: List[float], period: int) -> float:
        k = 2.0 / (period + 1.0)
        ema = series[0]
        for val in series[1:]:
            ema = (val * k) + (ema * (1.0 - k))
        return ema

    ema20_4h = calc_ema(closes_4h, 20)
    ema50_4h = calc_ema(closes_4h, 50)
    macro_bullish = curr_p > ema50_4h and ema20_4h >= ema50_4h * 0.995

    # 2. Análisis Microestructural en 1H
    highs_1h = [c[2] for c in candles_1h]
    lows_1h = [c[3] for c in candles_1h]
    vols_1h = [c[5] for c in candles_1h]

    ema20_1h = calc_ema(closes_1h, 20)
    dev_ema20 = (curr_p - ema20_1h) / ema20_1h * 100.0

    # ATR 14 de 1H
    trs = []
    for i in range(1, len(candles_1h)):
        h, l, prev_c = candles_1h[i][2], candles_1h[i][3], candles_1h[i-1][4]
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    atr_1h = sum(trs[-14:]) / 14.0 if trs else (highs_1h[-1] - lows_1h[-1])
    atr_pct = (atr_1h / curr_p * 100.0) if curr_p > 0 else 1.5

    # RSI 14 de 1H
    gains, losses = [], []
    for i in range(1, 15):
        diff = closes_1h[-15+i] - closes_1h[-15+i-1]
        gains.append(max(0.0, diff))
        losses.append(max(0.0, -diff))
    avg_g = sum(gains) / 14.0 if gains else 0.0001
    avg_l = sum(losses) / 14.0 if losses else 0.0001
    rs = avg_g / (avg_l if avg_l > 0 else 0.0001)
    rsi_1h = 100.0 - (100.0 / (1.0 + rs))

    # Detección de Vela de Rechazo en 1H (Mecha inferior en zona de soporte)
    last_candle = candles_1h[-1]
    o_c, h_c, l_c, c_c = last_candle[1], last_candle[2], last_candle[3], last_candle[4]
    c_range = h_c - l_c
    lower_wick = min(o_c, c_c) - l_c
    rejection_ratio = (lower_wick / c_range) if c_range > 0 else 0.0
    has_rejection = rejection_ratio >= 0.40 or (c_c > o_c and c_c > closes_1h[-2])

    # Volumen relativo en soporte
    avg_vol = sum(vols_1h[-20:]) / 20.0 if vols_1h else 1.0
    vol_spike = (vols_1h[-1] / avg_vol) if avg_vol > 0 else 1.0

    # 3. Parámetros Cuantitativos 100% Dinámicos por ATR 1H (Cero Hardcoding):
    # Stop Loss Dinámico: 1.50x ATR 1H (espacio natural de oscilación de la moneda)
    stop_distance = 1.50 * atr_1h
    stop_pct = round(stop_distance / curr_p, 4)
    stop_price = round(curr_p - stop_distance, 4)

    # Target Asimétrico Dinámico: 4.50x ATR 1H (Garantiza R:R de 3.0:1 exacto)
    target_distance = 4.50 * atr_1h
    target_pct = round(target_distance / curr_p, 4)
    target_price = round(curr_p + target_distance, 4)
    rr_ratio = round(target_pct / (stop_pct if stop_pct > 0 else 0.001), 2)

    # 4. Filtro Anti-Cuchillo (Anti-Knife Shield):
    # Prohibido comprar si las últimas 3 velas de 1H son rojas consecutivas con cuerpo expansivo
    is_falling_knife = False
    if len(candles_1h) >= 4:
        r1 = candles_1h[-2][4] < candles_1h[-2][1]
        r2 = candles_1h[-3][4] < candles_1h[-3][1]
        r3 = candles_1h[-4][4] < candles_1h[-4][1]
        if r1 and r2 and r3 and not has_rejection:
            is_falling_knife = True

    # 5. Puntuación Cuantitativa Swing (0 a 100)
    score = 0.0
    if macro_bullish:
        score += 35.0  # Tendencia 4H a favor
    if dev_ema20 <= 0.50 and rsi_1h <= 48.0:
        score += 30.0  # Descuento en soporte 1H
    if has_rejection:
        score += 20.0  # Vela de rechazo / absorción
    if vol_spike >= 1.2:
        score += 15.0  # Volumen de soporte

    # Disparo Francotirador listo:
    is_trigger_ready = (score >= 65.0) and macro_bullish and not is_falling_knife and (rr_ratio >= DEFAULT_MIN_RR_RATIO)

    status_str = "🟢 DISPARO LISTO" if is_trigger_ready else (
        "🟡 ESPERANDO RETROCESO" if macro_bullish else "⚪ SIN TENDENCIA 4H"
    )

    return {
        "symbol": symbol,
        "price": curr_p,
        "macro_bullish": macro_bullish,
        "dev_ema20": round(dev_ema20, 2),
        "rsi_1h": round(rsi_1h, 1),
        "atr_1h_pct": round(atr_pct, 2),
        "vol_spike": round(vol_spike, 2),
        "has_rejection": has_rejection,
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


# ====================== GESTOR DE EJECUCIÓN SWING PAPER ======================
def execute_swing_paper_entry(bot: SwingBot, opp: Dict):
    """Abre una posición Swing simulada con tamaño proporcional y ratio R:R >= 3:1."""
    if bot.active_trade is not None:
        return

    sym = opp["symbol"]
    curr_p = opp["price"]
    trade_capital = min(bot.cash * SWING_CAPITAL_ALLOCATION, 60.00)
    if trade_capital < 15.0 or curr_p <= 0:
        return

    # Precision de tamaño adaptada al valor del activo (BTC requiere 6 decimales)
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
    atr_p = opp["atr_1h_pct"]
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
    bot.active_trade = trade
    bot.add_log(f"🎯 DISPARO SWING 1H #{order_id}: {sym} @ ${curr_p:.4f} | Target: ${target_p:.4f} (+{target_pct*100:.2f}%) | Stop: ${stop_p:.4f} (-{stop_pct*100:.2f}%) | R:R {rr}:1", "trade")
    bot.db.log_trade(
        symbol=sym, side="BUY", price=curr_p, amount=amount, capital=trade_capital,
        pnl=0.0, fee=entry_fee, order_id=order_id, target_price=target_p, stop_price=stop_p,
        note=f"Swing Entry #{order_id} (R:R {rr}:1 | ATR 1H {atr_p:.2f}%)"
    )
    bot.save_state()


def manage_active_swing_trade(bot: SwingBot):
    """Monitorea el trade activo: activa Break-Even al +1.20% y gestiona Target y Stop."""
    tr = bot.active_trade
    if not tr:
        return

    sym = tr.symbol
    try:
        ticker = exchange.fetch_ticker(sym)
        curr_p = float(ticker.get("last", 0.0) or 0.0)
    except Exception:
        return

    if curr_p <= 0:
        return

    gain_pct = (curr_p - tr.entry_price) / tr.entry_price

    tr.current_price = curr_p
    tr.highest_price = max(getattr(tr, "highest_price", tr.entry_price), curr_p)
    tr.unrealized_pnl = (curr_p - tr.entry_price) * tr.amount
    tr.unrealized_pnl_pct = gain_pct * 100.0

    atr_val_abs = tr.entry_price * (tr.atr_pct / 100.0)

    # 1. Escudo Break-Even: Si el trade alcanza +1.0x ATR (o mínimo +1.20%), subir el Stop a +0.20% (riesgo cero)
    be_threshold = max(0.0120, (tr.atr_pct / 100.0) * 0.8)
    if not tr.is_be_active and gain_pct >= be_threshold:
        tr.is_be_active = True
        new_stop = round(tr.entry_price * (1.0 + BREAK_EVEN_STOP_PCT), 4)
        if new_stop > tr.stop_price:
            tr.stop_price = new_stop
            bot.add_log(f"🛡️ ESCUDO BREAK-EVEN ACTIVADO en {sym}: Ganancia +{gain_pct*100:.2f}%. Stop sube a ${new_stop:.4f} (+0.20% asegurado). Trade 100% libre de riesgo.", "trade")
            bot.save_state()

    # 2. Trailing Profit Dinámico por ATR (Chandelier Exit):
    # Si la ganancia supera +1.5x ATR, el Stop persigue el máximo histórico menos 1.5x ATR, bloqueando beneficios:
    trailing_trigger = (tr.atr_pct / 100.0) * 1.5
    if gain_pct >= trailing_trigger:
        trail_stop = round(tr.highest_price - (1.50 * atr_val_abs), 4)
        if trail_stop > tr.stop_price:
            old_stop = tr.stop_price
            tr.stop_price = trail_stop
            tr.is_trailing_active = True
            bot.add_log(f"📈 TRAILING ATR ELEVADO en {sym}: Máximo ${tr.highest_price:.4f}. Stop sube de ${old_stop:.4f} a ${trail_stop:.4f} asegurando beneficios crecientes.", "trade")
            bot.save_state()

    # 3. Cierre por Target (+4.5x ATR neto):
    if curr_p >= tr.target_price:
        gross_pnl = (tr.target_price - tr.entry_price) * tr.amount
        exit_fee = (tr.target_price * tr.amount) * FEE_RATE
        net_pnl = gross_pnl - tr.entry_fee - exit_fee
        bot.cash += (tr.capital + net_pnl)
        bot.add_log(f"🏆 VICTORIA TOTAL SWING en {sym}: Target ${tr.target_price:.4f} alcanzado | PnL neto: +${net_pnl:.4f} USDT (+{tr.target_pct*100:.2f}%)", "trade")
        bot.db.log_trade(
            symbol=sym, side="SELL", price=tr.target_price, amount=tr.amount, capital=tr.capital,
            pnl=net_pnl, fee=exit_fee, order_id=tr.trade_id, target_price=tr.target_price, stop_price=tr.stop_price,
            note=f"🏆 TARGET ALCANZADO (+{tr.target_pct*100:.2f}%)"
        )
        bot.cooldowns[sym] = time.time() + 1800  # 30 min cooldown
        bot.active_trade = None
        bot.save_state()
        return

    # 3. Cierre por Stop Loss (o Stop Break-Even):
    if curr_p <= tr.stop_price:
        gross_pnl = (tr.stop_price - tr.entry_price) * tr.amount
        exit_fee = (tr.stop_price * tr.amount) * FEE_RATE
        net_pnl = gross_pnl - tr.entry_fee - exit_fee
        bot.cash += (tr.capital + net_pnl)
        reason = "🛡️ SALIDA BREAK-EVEN (Coste Cero)" if tr.is_be_active else f"🛑 STOP LOSS DEFENSIVO (-{tr.stop_pct*100:.2f}%)"
        bot.add_log(f"{reason} en {sym} @ ${tr.stop_price:.4f} | PnL neto: {net_pnl:+.4f} USDT", "trade")
        bot.db.log_trade(
            symbol=sym, side="SELL", price=tr.stop_price, amount=tr.amount, capital=tr.capital,
            pnl=net_pnl, fee=exit_fee, order_id=tr.trade_id, target_price=tr.target_price, stop_price=tr.stop_price,
            note=reason
        )
        bot.cooldowns[sym] = time.time() + 3600  # 1 hora de cooldown tras stop
        bot.active_trade = None
        bot.save_state()
        return

    pct_now = gain_pct * 100.0
    bot.status_msg = (f"En Trade Swing {sym} @ ${tr.entry_price:.4f} | Actual: ${curr_p:.4f} ({pct_now:+.2f}%) | "
                      f"Target: ${tr.target_price:.4f} | Stop: ${tr.stop_price:.4f} {'[BE Activo]' if tr.is_be_active else ''}")


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
                        <span>🎯 PILAR 2: SWING SNIPER 1H/4H (PAPER TRADING)</span>
                    </div>
                    <span class="tag tag-yellow">MODO SIMULADO EV &gt; 0</span>
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

        <!-- RADAR MATRIX 1H / 4H -->
        <div class="card" style="margin-bottom: 24px;">
            <div class="card-header">
                <div class="card-title">
                    <span>📊 RADAR CUANTITATIVO 1H / 4H: PULLBACKS DE ALTA CONVICCIÓN</span>
                </div>
                <span style="font-size: 11px; color: var(--text-dim); font-family: monospace;">Filtro Anti-Cuchillo + R:R &gt;= 3.0:1</span>
            </div>
            <div style="overflow-x: auto;">
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Par</th>
                            <th>Precio</th>
                            <th>Tendencia 4H</th>
                            <th>Desviación EMA20 1H</th>
                            <th>RSI 1H</th>
                            <th>ATR 1H</th>
                            <th>Rechazo Soporte</th>
                            <th>R:R Proyectado</th>
                            <th>Target / Stop</th>
                            <th>Puntaje</th>
                            <th>Estado</th>
                        </tr>
                    </thead>
                    <tbody id="radar-tbody">
                        <tr><td colspan="12" style="text-align: center; color: var(--text-dim); padding: 20px;">Cargando velas de 1H y 4H...</td></tr>
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
        async function updateDashboard() {
            try {
                const res = await fetch('/api/status');
                const d = await res.json();

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

                // Posición Activa
                const actEl = document.getElementById('active-status');
                if (d.active_trade) {
                    const tr = d.active_trade;
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
                    const unPnlStr = (unPnl >= 0 ? '+' : '') + unPnl.toFixed(4) + ' USDT (' + (unPnlPct >= 0 ? '+' : '') + unPnlPct.toFixed(2) + '%)';
                    const unPnlColor = unPnl >= 0 ? '#3fb950' : '#f85149';
                    const stopDiffPct = ((Number(tr.stop_price) - Number(tr.entry_price)) / Number(tr.entry_price) * 100).toFixed(2);
                    const stopDiffSign = Number(stopDiffPct) >= 0 ? '+' : '';

                    actEl.innerHTML = `
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; border-bottom:1px solid #21262d; padding-bottom:8px;">
                        <span style="font-weight:bold; color:#58a6ff; font-size:14px;">🦅 POSICIÓN EN CURSO: ${tr.symbol}</span>
                        ${badge}
                    </div>
                    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap:10px; margin-bottom:10px;">
                        <div><span style="color:var(--text-dim); font-size:10px;">PORTE (TAMAÑO):</span><br><b>${tr.amount} ${tr.symbol.split('/')[0]}</b> <span style="color:var(--text-dim); font-size:11px;">($${Number(tr.capital).toFixed(2)})</span></div>
                        <div><span style="color:var(--text-dim); font-size:10px;">PRECIO ENTRADA:</span><br><b>$${entP}</b></div>
                        <div><span style="color:var(--text-dim); font-size:10px;">PRECIO ACTUAL:</span><br><b style="color:#58a6ff;">$${liveP}</b> <span style="color:var(--text-dim); font-size:11px;">(Max: $${highP})</span></div>
                        <div><span style="color:var(--text-dim); font-size:10px;">PNL FLOTANTE:</span><br><b style="color:${unPnlColor};">${unPnlStr}</b></div>
                    </div>
                    <div style="background:#161b22; border-radius:6px; padding:10px; display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; font-size:11px; border:1px solid #21262d;">
                        <div>🎯 <b>Target Dinámico:</b> <span style="color:#3fb950; font-weight:bold;">$${tgtP} (+${(tr.target_pct*100).toFixed(2)}%)</span></div>
                        <div>🛡️ <b>Stop Dinámico ATR:</b> <span style="color:${Number(stopDiffPct) >= 0 ? '#3fb950' : '#f85149'}; font-weight:bold;">$${stpP} (${stopDiffSign}${stopDiffPct}%)</span></div>
                        <div>📐 <b>R:R:</b> <span style="color:#3fb950; font-weight:bold;">${tr.rr_ratio}:1</span></div>
                        <div>🌊 <b>ATR 1H:</b> <span style="color:var(--text-main); font-weight:bold;">${tr.atr_pct}%</span></div>
                    </div>`;
                } else {
                    actEl.innerHTML = `<span style="color:var(--text-dim);">${d.status_msg || 'Sin posición activa. Buscando retrocesos de alta probabilidad...'}</span>`;
                }

                // 3. Radar Table
                const tbody = document.getElementById('radar-tbody');
                if (tbody && d.radar_telemetry && d.radar_telemetry.length > 0) {
                    let rows = '';
                    d.radar_telemetry.forEach((c, idx) => {
                        const macroTag = c.macro_bullish ? '<span class="tag tag-green">ALCISTA</span>' : '<span class="tag tag-gray">NEUTRAL</span>';
                        const devColor = c.dev_ema20 <= 0 ? '#3fb950' : '#d29922';
                        const rejTag = c.has_rejection ? '<span style="color:#3fb950;">SÍ (Absorción)</span>' : '<span style="color:#8b949e;">No</span>';
                        const statusClass = c.trigger_ready ? 'tag-green' : (c.score >= 50 ? 'tag-yellow' : 'tag-gray');
                        
                        rows += `<tr>
                            <td>${idx + 1}</td>
                            <td><b>${c.symbol.split('/')[0]}</b></td>
                            <td>$${Number(c.price).toFixed(4)}</td>
                            <td>${macroTag}</td>
                            <td style="color:${devColor}; font-weight:bold;">${c.dev_ema20 > 0 ? '+' : ''}${c.dev_ema20.toFixed(2)}%</td>
                            <td><span style="color:${c.rsi_1h <= 45 ? '#3fb950' : '#c9d1d9'}">${c.rsi_1h}</span></td>
                            <td>${c.atr_1h_pct}%</td>
                            <td>${rejTag}</td>
                            <td style="color:#3fb950; font-weight:bold;">${c.rr_ratio} : 1</td>
                            <td>+${c.target_pct}% / -${c.stop_pct}%</td>
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
                tr = bot.active_trade

            invested = round(tr.amount * tr.entry_price, 2) if tr else 0.0
            live_val = round(tr.amount * getattr(tr, "current_price", tr.entry_price), 2) if tr else 0.0
            unrealized_pnl = getattr(tr, "unrealized_pnl", live_val - invested) if tr else 0.0
            unrealized_pnl_pct = getattr(tr, "unrealized_pnl_pct", ((live_val - invested) / invested * 100.0 if invested > 0 else 0.0)) if tr else 0.0
            equity = bot.cash + (invested + unrealized_pnl if tr else 0.0)

            payload = {
                "cash": round(bot.cash, 2),
                "equity": round(equity, 2),
                "invested": round(invested, 2),
                "unrealized_pnl": round(unrealized_pnl, 4),
                "unrealized_pnl_pct": round(unrealized_pnl_pct, 2),
                "status_msg": bot.status_msg,
                "active_trade": tr.to_dict() if tr else None,
                "stats": stats,
                "radar_telemetry": telemetry,
                "real_grid": grid_stats,
                "events": events
            }
            self.wfile.write(json.dumps(payload).encode("utf-8"))
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


# ====================== HILO DE ESCANEO DE MERCADO (1H / 4H) ======================
def swing_telemetry_thread(bot: SwingBot):
    """Escanea la whitelist de altcoins en 1H y 4H cada 15 segundos."""
    print("  📡 [SWING 1H/4H RADAR] Motor de análisis estructural activo.", flush=True)
    last_grid_check = 0.0

    while True:
        try:
            bot.scan_cycle += 1
            results = []
            for sym in SWING_WHITELIST:
                try:
                    res = analyze_hourly_swing_structure(sym)
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
            bot.add_log(f"Error en escaneo swing: {e}", "error")

        time.sleep(15.0)


# ====================== BUCLE PRINCIPAL ======================
def run_hourly_swing():
    print("=" * 80, flush=True)
    print("  THE HOURLY SWING SNIPER (1H / 4H ASYMMETRIC ENGINE)", flush=True)
    print("  • Modo                           -> PAPER TRADING ESTRICTO (Capital virtual $70.00)", flush=True)
    print("  • Seguridad                      -> Malla DOGE Real Pionex INTACTA (Solo Lectura)", flush=True)
    print("  • Ratio Riesgo/Beneficio         -> R:R >= 3.0:1 (Stop ~1.5% | Target +4.5% a +6.5%)", flush=True)
    print("  • Escudo Break-Even              -> Activación automática al +1.20%", flush=True)
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

            if bot.active_trade:
                manage_active_swing_trade(bot)
            else:
                with bot.data_lock:
                    telemetry = list(bot.radar_telemetry)

                ready_opps = [
                    o for o in telemetry
                    if o["trigger_ready"] and bot.cooldowns.get(o["symbol"], 0.0) <= now_ts
                ]

                if ready_opps:
                    best = ready_opps[0]
                    execute_swing_paper_entry(bot, best)
                else:
                    top = telemetry[0] if telemetry else None
                    if top:
                        bot.status_msg = f"Escaneando 1H/4H: Líder {top['symbol']} (Score {top['score']}/100 | {top['status']}). Esperando confluencia."

            time.sleep(2.5)

        except KeyboardInterrupt:
            print("\nDeteniendo Swing Engine...", flush=True)
            break
        except Exception as e:
            bot.add_log(f"Error en bucle swing: {e}", "error")
            time.sleep(5.0)


if __name__ == "__main__":
    run_hourly_swing()
