"""
========================================================================================
  THE 1-DOLLAR SCALPER (CERO MALLAS, CERO SHORT - ORDER FLOW MOMENTUM ENGINE)
  - Modo: PIONEX CUENTA REAL SPOT (Live Execution via pionex-trade-cli)
  - Persistencia: SQLite WAL (Cero CSV, Ultra-rápido, Cero Bloqueos)
  - Base de Datos: scalper_logs/scalper_vault.db
  - Saldo Inicial Real: ~$70.35 USDT (Liberados tras liquidación de XLM)
  - Objetivo: Cazar micro-impulsos de alta probabilidad (+0.95% neto) y volver 100% a caja líquida.
  - Ejecución: Stoikov LOB Level-1 / Bid-Wall Front-running (Maker Límite con prioridad de cola).
  - Salida Objetivo: +0.95% dinámico (+$0.57 netos descontando comisión Pionex 0.05%).
  - Stop Defensivo: -0.70% estricto (arriesga ~$0.42 para ganar ~$0.57 -> Ratio R:R > 1.35:1).
  - Telemetría en Vivo: 11 pares líderes con radar LOB OBI y almacenamiento SQLite.
  - Dashboard reactivo ultra-visual: http://localhost:8899
========================================================================================
"""

import os
import sys
import time
import json
import math
import shutil
import sqlite3
import contextlib
import http.server
import threading
import subprocess
from collections import deque
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
PIONEX_LIVE_MODE = True  # EJECUCIÓN REAL EN VIVO EN PIONEX
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Paper: l?gica completa contra datos reales de Pionex pero ?rdenes simuladas, con base/estado separados.
PAPER_MODE = ("--paper" in sys.argv) or os.environ.get("SCALPER_PAPER") == "1"
PAPER_START_USDT = 70.0
PORTFOLIO_DIR = os.environ.get("SCALPER_DATA_DIR") or (
    os.path.join(BASE_DIR, "scalper_logs", "paper") if PAPER_MODE else os.path.join(BASE_DIR, "scalper_logs"))
SCALPER_DB_FILE = os.path.join(PORTFOLIO_DIR, "scalper_vault.db")
SCALPER_STATE_FILE = os.path.join(PORTFOLIO_DIR, "scalper_live_state.json")
SCALPER_STANDALONE_HTML = os.path.join(PORTFOLIO_DIR, "dashboard.html")
SCALPER_HTTP_PORT = 8899

PIONEX_FEE_RATE = 0.0005    # 0.05% Pionex Spot Maker/Taker estándar
TARGET_PROFIT_PCT = 0.0095  # +0.95% bruto -> +0.85% neto (~+$0.55 a $0.60 USDT por ciclo ágil)
STOP_LOSS_PCT = 0.0070      # -0.70% bruto -> -0.80% neto (-$0.45 USDT) | R:R > 1.35:1
ORDER_EXPIRY_SECS = 360     # 6 minutos de persistencia en cola Maker LOB
MAX_HOLD_TIME_SECS = 1800   # 30 minutos máximo por trade (salida si se estanca)
MIN_RANGE15_PCT = 0.40      # Rango medio 15m mínimo (%) para que +0.95% sea alcanzable en la ventana
STOP_COOLDOWN_SECS = 1800   # No reentrar en un par que acaba de cortar stop
CLI_TIMEOUT_SECS = 25
DASHBOARD_ONLY = ("--dashboard-only" in sys.argv) or os.environ.get("SCALPER_DASHBOARD_ONLY") == "1"

# Perfil RÁPIDO (por defecto): opera en cualquier régimen (alcista/bajista/lateral) buscando rebotes cortos,
# compra cruzando el ask (fill inmediato), objetivo pequeño y salida por tiempo corta. SCALPER_FAST=0 -> perfil clásico.
FAST_MODE = os.environ.get("SCALPER_FAST", "1") != "0"
if FAST_MODE:
    TARGET_PROFIT_PCT = 0.0050     # Base fallback dinámico (~0.70x ATR)
    STOP_LOSS_PCT = 0.0180         # Piso de seguridad catastrófico (~2.2x ATR, nunca cazado por ruido)
    ORDER_EXPIRY_SECS = 90
    MAX_HOLD_TIME_SECS = 900       # 15 minutos de ventana de impulso
    MIN_RANGE15_PCT = 0.30
    STOP_COOLDOWN_SECS = 300
    FAST_MAX_SPREAD_PCT = 0.08
    FAST_MIN_PROFIT_EXIT = 0.0020  # salida si supera +0.20% (ganancia neta tras 0.10% fees)
    FAST_FORCE_EXIT_SECS = 1500    # 25 min máximo absoluto
    FAST_TRIGGERS_REQUIRED = 1
else:
    FAST_MAX_SPREAD_PCT = 0.08
    FAST_MIN_PROFIT_EXIT = 0.002
    FAST_FORCE_EXIT_SECS = 10 ** 9
    FAST_TRIGGERS_REQUIRED = 2

# Whitelist de Altcoins Ágiles de Alta Beta (excluye BTC y ETH por baja velocidad de oscilación)
INSTITUTIONAL_SCALP_WHITELIST = [
    "SOL/USDT", "SUI/USDT", "NEAR/USDT", "INJ/USDT", "AVAX/USDT",
    "LINK/USDT", "UNI/USDT", "DOGE/USDT", "ADA/USDT", "DOT/USDT", "XRP/USDT"
]

os.makedirs(PORTFOLIO_DIR, exist_ok=True)
exchange = ccxt.binance({"enableRateLimit": True, "timeout": 8000})


# ====================== BASE DE DATOS SQLITE (ALTA VELOCIDAD) ======================
class ScalperDatabase:
    """Gestor de persistencia transaccional SQLite de alto rendimiento con WAL."""

    def __init__(self, db_path: str = SCALPER_DB_FILE):
        self.db_path = db_path
        self._init_db()

    @contextlib.contextmanager
    def _get_connection(self):
        # sqlite3 como context manager solo hace commit: hay que cerrar explícitamente para no filtrar conexiones.
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

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
                    pnl REAL NOT NULL,
                    fee REAL NOT NULL,
                    order_id TEXT,
                    target_order_id TEXT,
                    note TEXT,
                    mode TEXT DEFAULT 'LIVE_SPOT'
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(timestamp);")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp);")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS equity_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    cash REAL NOT NULL,
                    equity REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    win_rate REAL,
                    total_trades INTEGER
                );
            """)
            conn.commit()

    def insert_trade(self, symbol: str, side: str, price: float, amount: float, capital: float,
                     pnl: float, fee: float, note: str, order_id: str = "", target_order_id: str = "", mode: str = "LIVE_SPOT"):
        ts = datetime.now().isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO trades (timestamp, symbol, side, price, amount, capital, pnl, fee, order_id, target_order_id, note, mode)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (ts, symbol, side, price, amount, capital, pnl, fee, order_id, target_order_id, note, mode))
            conn.commit()

    def insert_event(self, event_type: str, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO events (timestamp, event_type, message)
                VALUES (?, ?, ?)
            """, (ts, event_type, message))
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
        """Fuente de verdad de contadores: se derivan de las ventas registradas."""
        with self._get_connection() as conn:
            row = conn.execute("""
                SELECT COUNT(*) AS n,
                       COALESCE(SUM(pnl), 0) AS pnl,
                       COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) AS wins,
                       COALESCE(SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END), 0) AS losses
                FROM trades WHERE side = 'SELL'
            """).fetchone()
            return {"total": int(row["n"]), "pnl": float(row["pnl"]), "wins": int(row["wins"]), "losses": int(row["losses"])}

    def get_last_buy(self, symbol: str) -> Optional[Dict]:
        norm = symbol.replace("/", "_")
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM trades WHERE side='BUY' AND REPLACE(symbol,'/','_')=? ORDER BY id DESC LIMIT 1", (norm,)
            ).fetchone()
            return dict(row) if row else None

    def get_equity_curve(self, limit: int = 300) -> List[Dict]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT timestamp, equity FROM equity_history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            res = [dict(r) for r in rows]
            res.reverse()
            return res

    def prune(self):
        """Evita crecimiento sin límite de eventos y equity."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM events WHERE event_type = 'radar'")
            conn.execute("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 3000)")
            conn.execute("DELETE FROM equity_history WHERE id NOT IN (SELECT id FROM equity_history ORDER BY id DESC LIMIT 20000)")

    def get_recent_trades(self, limit: int = 50) -> List[Dict]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_recent_events(self, limit: int = 40) -> List[Dict]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT timestamp as time, event_type as type, message as text FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            res = [dict(r) for r in rows]
            res.reverse()
            return res


# ====================== EJECUTOR REAL PIONEX (CLI) ======================
class PionexLiveExecutor:
    """Ejecutor de órdenes spot en vivo para Pionex usando pionex-trade-cli."""

    _symbol_rules_cache = {}
    _last_rules_update = 0

    @staticmethod
    def run_cmd(args: List[str]) -> Dict:
        exe = shutil.which("pionex-trade-cli.cmd") or shutil.which("pionex-trade-cli")
        use_shell = exe is None
        cmd = [exe or "pionex-trade-cli"] + args
        try:
            res = subprocess.run(
                cmd,
                shell=use_shell,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=CLI_TIMEOUT_SECS
            )
            if res.returncode != 0:
                return {"result": False, "error": res.stderr.strip() or res.stdout.strip()}
            return json.loads(res.stdout)
        except subprocess.TimeoutExpired:
            return {"result": False, "error": f"timeout {CLI_TIMEOUT_SECS}s: {' '.join(args[:3])}"}
        except Exception as e:
            return {"result": False, "error": str(e)}

    @classmethod
    def get_usdt_balance(cls) -> Tuple[float, float]:
        """Obtiene el saldo libre y congelado en USDT de Pionex."""
        res = cls.run_cmd(["account", "balance"])
        if not res.get("result"):
            return 0.0, 0.0
        free_usdt = 0.0
        frozen_usdt = 0.0
        for b in res.get("data", {}).get("balances", []):
            if b.get("coin") == "USDT":
                try:
                    free_usdt = float(b.get("free", 0.0))
                    frozen_usdt = float(b.get("frozen", 0.0))
                except Exception:
                    pass
        return free_usdt, frozen_usdt

    @classmethod
    def get_coin_balance(cls, coin: str) -> float:
        """Obtiene el saldo libre real de cualquier criptomoneda en Pionex."""
        res = cls.run_cmd(["account", "balance"])
        if not res.get("result"):
            return 0.0
        for b in res.get("data", {}).get("balances", []):
            if b.get("coin") == coin:
                try:
                    return float(b.get("free", 0.0))
                except Exception:
                    return 0.0
        return 0.0

    @classmethod
    def get_symbol_rules(cls) -> Dict:
        """Cachea y retorna reglas de precisión de Pionex."""
        now = time.time()
        if cls._symbol_rules_cache and (now - cls._last_rules_update < 1800):
            return cls._symbol_rules_cache

        res = cls.run_cmd(["market", "symbols"])
        if res.get("result"):
            rules = {}
            for s in res.get("data", {}).get("symbols", []):
                sym = s.get("symbol")
                rules[sym] = {
                    "basePrecision": int(s.get("basePrecision", 2)),
                    "quotePrecision": int(s.get("quotePrecision", 4)),
                    "minAmount": float(s.get("minAmount", 10.0)),
                    "minTradeSize": float(s.get("minTradeSize", 0.01))
                }
            cls._symbol_rules_cache = rules
            cls._last_rules_update = now
        return cls._symbol_rules_cache

    @classmethod
    def get_open_orders(cls, pio_symbol: str) -> Optional[List[Dict]]:
        """Órdenes abiertas del par. Devuelve None si la consulta falla (no confundir con 'sin órdenes')."""
        res = cls.run_cmd(["orders", "open", "--symbol", pio_symbol])
        if res.get("result"):
            return res.get("data", {}).get("orders", [])
        return None

    @classmethod
    def get_order(cls, pio_symbol: str, order_id: str) -> Optional[Dict]:
        res = cls.run_cmd(["orders", "get", "--symbol", pio_symbol, "--order-id", str(order_id)])
        if res.get("result"):
            data = res.get("data", {})
            return data.get("order") if isinstance(data.get("order"), dict) else (data if data.get("orderId") else None)
        return None

    @staticmethod
    def summarize_fill(order: Optional[Dict]) -> Optional[Dict]:
        """Precio medio, tamaño, importe y comisión (en USDT) reales de una orden."""
        if not order:
            return None
        try:
            size = float(order.get("filledSize", 0) or 0)
            amount = float(order.get("filledAmount", 0) or 0)
            fee = float(order.get("fee", 0) or 0)
        except (TypeError, ValueError):
            return None
        if size <= 0 or amount <= 0:
            return None
        avg = amount / size
        fee_coin = order.get("feeCoin")
        fee_usdt = fee if fee_coin in (None, "", "USDT") else fee * avg
        base_fee = fee if fee_coin not in (None, "", "USDT") else 0.0
        return {"price": avg, "size": size, "amount": amount, "fee_usdt": fee_usdt, "base_fee": base_fee,
                "status": order.get("status", "")}

    @classmethod
    def get_market_depth(cls, pio_symbol: str, limit: int = 5) -> Dict:
        """Obtiene la profundidad nativa del libro de órdenes directamente de Pionex."""
        res = cls.run_cmd(["market", "depth", pio_symbol, "--limit", str(limit)])
        if res.get("result"):
            return res.get("data", {})
        return {}

    @classmethod
    def place_limit_buy(cls, pio_symbol: str, price: float, size: float) -> Optional[str]:
        """Coloca una orden Maker Límite de compra en Pionex."""
        rules = cls.get_symbol_rules().get(pio_symbol, {"basePrecision": 2, "quotePrecision": 4})
        b_prec = rules["basePrecision"]
        q_prec = rules["quotePrecision"]

        price_str = f"{price:.{q_prec}f}"
        size_str = f"{size:.{b_prec}f}"

        res = cls.run_cmd([
            "orders", "new",
            "--symbol", pio_symbol,
            "--side", "BUY",
            "--type", "LIMIT",
            "--price", price_str,
            "--size", size_str
        ])
        if res.get("result") and res.get("data", {}).get("orderId"):
            return str(res["data"]["orderId"])
        print(f"  [Pionex Buy Error] {res}", flush=True)
        return None

    @classmethod
    def place_limit_sell(cls, pio_symbol: str, price: float, size: float) -> Optional[str]:
        """Coloca orden Límite de venta en Target (+0.95%) ajustada al saldo libre real."""
        rules = cls.get_symbol_rules().get(pio_symbol, {"basePrecision": 2, "quotePrecision": 4})
        b_prec = rules["basePrecision"]
        q_prec = rules["quotePrecision"]

        base_coin = pio_symbol.split("_")[0]
        actual_free = cls.get_coin_balance(base_coin)
        target_size = min(size, actual_free) if actual_free > 0 else size
        factor = 10 ** b_prec
        floored_size = math.floor(target_size * factor) / factor

        price_str = f"{price:.{q_prec}f}"
        size_str = f"{floored_size:.{b_prec}f}"

        res = cls.run_cmd([
            "orders", "new",
            "--symbol", pio_symbol,
            "--side", "SELL",
            "--type", "LIMIT",
            "--price", price_str,
            "--size", size_str
        ])
        if res.get("result") and res.get("data", {}).get("orderId"):
            return str(res["data"]["orderId"])
        print(f"  [Pionex Sell Target Error] {res}", flush=True)
        return None

    @classmethod
    def place_market_sell(cls, pio_symbol: str, size: float) -> Optional[Dict]:
        """Ejecuta una venta a mercado inmediata (Stop Loss Defensivo) ajustada al saldo libre real."""
        rules = cls.get_symbol_rules().get(pio_symbol, {"basePrecision": 2, "quotePrecision": 4})
        b_prec = rules["basePrecision"]

        base_coin = pio_symbol.split("_")[0]
        actual_free = cls.get_coin_balance(base_coin)
        target_size = min(size, actual_free) if actual_free > 0 else size
        factor = 10 ** b_prec
        floored_size = math.floor(target_size * factor) / factor

        size_str = f"{floored_size:.{b_prec}f}"

        res = cls.run_cmd([
            "orders", "new",
            "--symbol", pio_symbol,
            "--side", "SELL",
            "--type", "MARKET",
            "--size", size_str
        ])
        if res.get("result"):
            return res.get("data", {})
        print(f"  [Pionex Stop Market Sell Error] {res}", flush=True)
        return None

    @classmethod
    def cancel_all_orders(cls, pio_symbol: str) -> bool:
        """Cancela todas las órdenes abiertas de un par en Pionex."""
        res = cls.run_cmd(["orders", "cancel_all", "--symbol", pio_symbol])
        return bool(res.get("result"))

    @classmethod
    def get_latest_order(cls, pio_symbol: str) -> Optional[Dict]:
        """Obtiene la última orden ejecutada o cerrada del par."""
        res = cls.run_cmd(["orders", "all", "--symbol", pio_symbol, "--limit", "1"])
        if res.get("result"):
            orders = res.get("data", {}).get("orders", [])
            if orders:
                return orders[0]
        return None


# ====================== EJECUTOR PAPER (?rdenes simuladas, mercado real de Pionex) ======================
class PaperExecutor(PionexLiveExecutor):
    """Simula cuenta/?rdenes con el libro REAL de Pionex. Maker compra llena si ask<=l?mite; venta l?mite si bid>=l?mite;
    mercado cruza el libro. Comisi?n 0.05% (compra en base coin, venta en USDT), igual que Pionex."""

    _file = os.path.join(PORTFOLIO_DIR, "paper_wallet.json")
    _lock = threading.RLock()
    _w: Dict = {}

    @classmethod
    def _load(cls):
        if cls._w:
            return
        try:
            with open(cls._file, "r", encoding="utf-8") as f:
                cls._w = json.load(f)
        except Exception:
            cls._w = {"usdt": PAPER_START_USDT, "frozen": 0.0, "coins": {}, "orders": {}, "seq": 9000000000}
            cls._save()

    @classmethod
    def _save(cls):
        tmp = cls._file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cls._w, f, indent=1)
        os.replace(tmp, cls._file)

    @classmethod
    def reset(cls, usdt: float = PAPER_START_USDT):
        with cls._lock:
            cls._w = {"usdt": usdt, "frozen": 0.0, "coins": {}, "orders": {}, "seq": 9000000000}
            cls._save()

    @classmethod
    def _best(cls, sym: str):
        d = cls.get_market_depth(sym, limit=5)
        try:
            bids = [(float(p), float(q)) for p, q in d["bids"]]
            asks = [(float(p), float(q)) for p, q in d["asks"]]
            return bids, asks
        except Exception:
            return None, None

    @classmethod
    def _tick(cls, sym: str):
        """Eval?a fills de las ?rdenes l?mite abiertas del par contra el libro real."""
        with cls._lock:
            cls._load()
            open_ids = [i for i, o in cls._w["orders"].items() if o["symbol"] == sym and o["status"] == "OPEN"]
            if not open_ids:
                return
            bids, asks = cls._best(sym)
            if not bids or not asks:
                return
            base = sym.split("_")[0]
            for i in open_ids:
                o = cls._w["orders"][i]
                px, sz = float(o["price"]), float(o["size"])
                if o["side"] == "BUY" and asks[0][0] <= px:
                    fee = sz * PIONEX_FEE_RATE
                    cls._w["frozen"] -= px * sz
                    cls._w["coins"][base] = cls._w["coins"].get(base, 0.0) + sz - fee
                    o.update(status="CLOSED", filledSize=str(sz), filledAmount=str(px * sz), fee=str(fee), feeCoin=base)
                elif o["side"] == "SELL" and bids[0][0] >= px:
                    amt = px * sz
                    fee = amt * PIONEX_FEE_RATE
                    cls._w["usdt"] += amt - fee
                    o.update(status="CLOSED", filledSize=str(sz), filledAmount=str(amt), fee=str(fee), feeCoin="USDT")
            cls._save()

    @classmethod
    def get_usdt_balance(cls) -> Tuple[float, float]:
        with cls._lock:
            cls._load()
            return cls._w["usdt"], max(0.0, cls._w["frozen"])

    @classmethod
    def get_coin_balance(cls, coin: str) -> float:
        with cls._lock:
            cls._load()
            return cls._w["coins"].get(coin, 0.0)

    @classmethod
    def get_open_orders(cls, pio_symbol: str):
        cls._tick(pio_symbol)
        with cls._lock:
            return [dict(o) for o in cls._w["orders"].values() if o["symbol"] == pio_symbol and o["status"] == "OPEN"]

    @classmethod
    def get_order(cls, pio_symbol: str, order_id: str):
        cls._tick(pio_symbol)
        with cls._lock:
            o = cls._w["orders"].get(str(order_id))
            return dict(o) if o else None

    @classmethod
    def _new(cls, sym, side, otype, price, size):
        cls._w["seq"] += 1
        oid = str(cls._w["seq"])
        cls._w["orders"][oid] = {"orderId": oid, "symbol": sym, "side": side, "type": otype, "price": str(price),
                                 "size": str(size), "filledSize": "0", "filledAmount": "0", "fee": "0",
                                 "feeCoin": "", "status": "OPEN", "createTime": int(time.time() * 1000)}
        return oid

    @classmethod
    def _fmt(cls, sym, price, size):
        r = cls.get_symbol_rules().get(sym, {"basePrecision": 2, "quotePrecision": 4})
        f = 10 ** r["basePrecision"]
        return round(price, r["quotePrecision"]), math.floor(size * f) / f, r

    @classmethod
    def place_limit_buy(cls, pio_symbol, price, size):
        with cls._lock:
            cls._load()
            price, size, r = cls._fmt(pio_symbol, price, size)
            cost = price * size
            if size <= 0 or cost < r.get("minAmount", 10.0) or cost > cls._w["usdt"]:
                print(f"  [Paper Buy Rechazada] costo {cost:.2f} libre {cls._w['usdt']:.2f}", flush=True)
                return None
            cls._w["usdt"] -= cost
            cls._w["frozen"] += cost
            oid = cls._new(pio_symbol, "BUY", "LIMIT", price, size)
            cls._save()
            return oid

    @classmethod
    def place_limit_sell(cls, pio_symbol, price, size):
        with cls._lock:
            cls._load()
            base = pio_symbol.split("_")[0]
            price, size, r = cls._fmt(pio_symbol, price, min(size, cls._w["coins"].get(base, 0.0)))
            if size <= 0 or price * size < r.get("minAmount", 10.0):
                print(f"  [Paper Sell Rechazada] {size} @ {price}", flush=True)
                return None
            cls._w["coins"][base] -= size
            oid = cls._new(pio_symbol, "SELL", "LIMIT", price, size)
            cls._save()
            return oid

    @classmethod
    def place_market_sell(cls, pio_symbol, size):
        with cls._lock:
            cls._load()
            bids, _ = cls._best(pio_symbol)
            base = pio_symbol.split("_")[0]
            price, size, _r = cls._fmt(pio_symbol, 0, min(size, cls._w["coins"].get(base, 0.0)))
            if not bids or size <= 0:
                return None
            left, amt = size, 0.0
            for p, q in bids:
                take = min(left, q)
                amt += take * p
                left -= take
                if left <= 1e-12:
                    break
            if left > 1e-12:
                amt += left * bids[-1][0]  # libro de 5 niveles agotado: peor precio visible
            fee = amt * PIONEX_FEE_RATE
            cls._w["coins"][base] -= size
            cls._w["usdt"] += amt - fee
            oid = cls._new(pio_symbol, "SELL", "MARKET", 0, size)
            cls._w["orders"][oid].update(status="CLOSED", filledSize=str(size), filledAmount=str(amt), fee=str(fee), feeCoin="USDT")
            cls._save()
            return {"orderId": oid}

    @classmethod
    def cancel_all_orders(cls, pio_symbol):
        cls._tick(pio_symbol)  # un fill pendiente gana a la cancelaci?n
        with cls._lock:
            base = pio_symbol.split("_")[0]
            for o in cls._w["orders"].values():
                if o["symbol"] == pio_symbol and o["status"] == "OPEN":
                    if o["side"] == "BUY":
                        c = float(o["price"]) * float(o["size"])
                        cls._w["frozen"] -= c
                        cls._w["usdt"] += c
                    else:
                        cls._w["coins"][base] = cls._w["coins"].get(base, 0.0) + float(o["size"])
                    o["status"] = "CANCELED"
            cls._save()
        return True


if PAPER_MODE:
    PionexLiveExecutor = PaperExecutor  # type: ignore[misc]  # el resto del c?digo resuelve el ejecutor por nombre global


# ====================== MODELO DE DATOS ======================
class ScalperTrade:
    def __init__(self, trade_id: str, symbol: str, entry_price: float, amount: float, capital: float,
                 target_order_id: str = "", entry_fee_usdt: float = 0.0,
                 target_pct: float = None, stop_pct: float = None, atr_val: float = None):
        self.trade_id = trade_id
        self.symbol = symbol
        self.entry_price = entry_price
        self.amount = amount
        self.capital = capital
        self.target_order_id = target_order_id
        self.entry_fee_usdt = entry_fee_usdt
        self.entry_time = time.time()
        self.target_pct = target_pct if target_pct is not None else TARGET_PROFIT_PCT
        self.stop_pct = stop_pct if stop_pct is not None else STOP_LOSS_PCT
        self.atr_val = atr_val or 0.0
        self.target_price = round(entry_price * (1.0 + self.target_pct), 6)
        self.stop_price = round(entry_price * (1.0 - self.stop_pct), 6)
        self.status = "OPEN"

    def to_dict(self):
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "entry_price": self.entry_price,
            "amount": self.amount,
            "capital": self.capital,
            "target_order_id": self.target_order_id,
            "entry_fee_usdt": self.entry_fee_usdt,
            "entry_time": self.entry_time,
            "target_pct": self.target_pct,
            "stop_pct": self.stop_pct,
            "atr_val": self.atr_val,
            "target_price": self.target_price,
            "stop_price": self.stop_price,
            "status": self.status
        }


class ScalperPendingOrder:
    def __init__(self, order_id: str, symbol: str, limit_price: float, size: float, capital: float, reason: str,
                 target_pct: float = None, stop_pct: float = None, atr_pct: float = None):
        self.order_id = order_id
        self.symbol = symbol
        self.limit_price = limit_price
        self.size = size
        self.capital = capital
        self.reason = reason
        self.target_pct = target_pct if target_pct is not None else TARGET_PROFIT_PCT
        self.stop_pct = stop_pct if stop_pct is not None else STOP_LOSS_PCT
        self.atr_pct = atr_pct or 0.0
        self.created_at = time.time()
        self.expires_at = self.created_at + ORDER_EXPIRY_SECS

    def to_dict(self):
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "limit_price": self.limit_price,
            "size": self.size,
            "capital": self.capital,
            "reason": self.reason,
            "target_pct": self.target_pct,
            "stop_pct": self.stop_pct,
            "atr_pct": self.atr_pct,
            "created_at": self.created_at,
            "expires_at": self.expires_at
        }


class ScalperBot:
    def __init__(self):
        self.db = ScalperDatabase(SCALPER_DB_FILE)
        self.cash = 0.0
        self.frozen = 0.0
        self.active_trade: Optional[ScalperTrade] = None
        self.pending_order: Optional[ScalperPendingOrder] = None
        self.realized_pnl = 0.0
        self.wins = 0
        self.losses = 0
        self.total_trades = 0
        self.status_msg = "Sincronizando con Pionex Real..."
        self.scan_cycle = 0
        self.radar_telemetry: List[Dict] = []
        self.event_log = deque(maxlen=40)
        self.consecutive_triggers: Dict[str, int] = {}
        self.last_counted_cycle = -1
        self.cooldowns: Dict[str, float] = {}
        self.last_equity_ts = 0.0
        self.data_lock = threading.Lock()
        try:
            self.db.prune()
        except Exception as e:
            print(f"  [Aviso DB] No se pudo depurar la base: {e}", flush=True)
        for ev in self.db.get_recent_events(40):
            self.event_log.append(ev)
        self.sync_balance()
        self.load_state()
        self.refresh_stats()
        self.reconcile_with_exchange()
        self.add_log("🚀 Motor The 1-Dollar Scalper iniciado. Base de datos SQLite activa (WAL mode).", "info")

    def add_log(self, text: str, log_type: str = "info"):
        now_str = datetime.now().strftime("%H:%M:%S")
        self.event_log.append({"time": now_str, "type": log_type, "text": text})
        if log_type == "radar":
            return
        try:
            self.db.insert_event(log_type, text)
        except Exception as e:
            print(f"  [Aviso DB] insert_event falló: {e}", flush=True)

    def sync_balance(self):
        """Sincroniza el saldo real con Pionex."""
        free, frozen = PionexLiveExecutor.get_usdt_balance()
        if (free + frozen) > 0:
            self.cash = free
            self.frozen = frozen

    def refresh_stats(self):
        """Contadores y PnL se derivan siempre de la base (no del JSON, que puede corromperse)."""
        try:
            s = self.db.get_stats()
            self.realized_pnl = s["pnl"]
            self.wins = s["wins"]
            self.losses = s["losses"]
            self.total_trades = s["total"]
        except Exception as e:
            print(f"  [Aviso DB] No se pudieron leer estadísticas: {e}", flush=True)

    def equity(self) -> float:
        return self.cash + self.frozen + (self.active_trade.capital if self.active_trade else 0.0)

    def maybe_log_equity(self, every_secs: float = 60.0):
        now = time.time()
        if now - self.last_equity_ts < every_secs or self.equity() <= 0:
            return
        self.last_equity_ts = now
        wr = (self.wins / self.total_trades * 100.0) if self.total_trades else 0.0
        try:
            self.db.insert_equity(self.cash, self.equity(), self.realized_pnl, wr, self.total_trades)
        except Exception as e:
            print(f"  [Aviso DB] insert_equity falló: {e}", flush=True)

    def load_state(self):
        """Restaura solo la posición/orden en vuelo desde el JSON; si está corrupto se respalda y se reconcilia con Pionex."""
        if not os.path.exists(SCALPER_STATE_FILE):
            return
        try:
            with open(SCALPER_STATE_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            backup = f"{SCALPER_STATE_FILE}.corrupt.{int(time.time())}.bak"
            try:
                shutil.copy2(SCALPER_STATE_FILE, backup)
            except Exception:
                backup = "(sin respaldo)"
            print(f"  ⚠️ [Estado corrupto] {e}. Respaldo: {backup}. Se reconcilia con Pionex.", flush=True)
            return
        try:
            if d.get("active_trade"):
                at = d["active_trade"]
                self.active_trade = ScalperTrade(
                    at["trade_id"], at["symbol"], at["entry_price"], at["amount"], at["capital"],
                    at.get("target_order_id", ""), at.get("entry_fee_usdt", 0.0),
                    target_pct=at.get("target_pct"), stop_pct=at.get("stop_pct"), atr_val=at.get("atr_val")
                )
                self.active_trade.entry_time = at.get("entry_time", time.time())
                self.active_trade.target_price = at.get("target_price", self.active_trade.target_price)
                self.active_trade.stop_price = at.get("stop_price", self.active_trade.stop_price)
            if d.get("pending_order"):
                po = d["pending_order"]
                self.pending_order = ScalperPendingOrder(
                    po["order_id"], po["symbol"], po["limit_price"], po.get("size", 0.0), po["capital"], po.get("reason", ""),
                    target_pct=po.get("target_pct"), stop_pct=po.get("stop_pct"), atr_pct=po.get("atr_pct")
                )
                self.pending_order.created_at = po.get("created_at", time.time())
                self.pending_order.expires_at = po.get("expires_at", time.time() + ORDER_EXPIRY_SECS)
        except Exception as e:
            print(f"  [Aviso Estado] No se pudo restaurar posición previa: {e}", flush=True)

    def reconcile_with_exchange(self):
        """Si no hay posición en memoria pero Pionex tiene órdenes vivas del scalper, las adopta para no dejarlas huérfanas."""
        if self.active_trade or self.pending_order:
            return
        for ccxt_sym in INSTITUTIONAL_SCALP_WHITELIST:
            pio_sym = ccxt_sym.replace("/", "_")
            orders = PionexLiveExecutor.get_open_orders(pio_sym)
            if not orders:
                continue
            for o in orders:
                side = str(o.get("side", "")).upper()
                try:
                    price = float(o.get("price", 0) or 0)
                    size = float(o.get("size", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if side == "SELL" and price > 0 and size > 0:
                    last_buy = self.db.get_last_buy(pio_sym)
                    entry = float(last_buy["price"]) if last_buy else price / (1.0 + TARGET_PROFIT_PCT)
                    tr = ScalperTrade(f"pio_adopt_{o.get('orderId')}", pio_sym, entry, size, entry * size, str(o.get("orderId")),
                                      float(last_buy["fee"]) if last_buy else 0.0)
                    tr.target_price = price
                    if last_buy:
                        try:
                            tr.entry_time = datetime.fromisoformat(last_buy["timestamp"]).timestamp()
                        except ValueError:
                            pass
                    self.active_trade = tr
                    print(f"  🔄 [RECONCILIADO] Venta viva adoptada: {pio_sym} {size} @ {price}", flush=True)
                    return
                if side == "BUY" and price > 0 and size > 0:
                    self.pending_order = ScalperPendingOrder(str(o.get("orderId")), pio_sym, price, size, price * size, "adoptada")
                    print(f"  🔄 [RECONCILIADO] Compra viva adoptada: {pio_sym} {size} @ {price}", flush=True)
                    return

    def save_state(self):
        d = {
            "cash": round(self.cash, 4),
            "frozen": round(self.frozen, 4),
            "equity": round(self.equity(), 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "wins": self.wins,
            "losses": self.losses,
            "total_trades": self.total_trades,
            "status_msg": self.status_msg,
            "active_trade": self.active_trade.to_dict() if self.active_trade else None,
            "pending_order": self.pending_order.to_dict() if self.pending_order else None,
            "updated_at": datetime.now().isoformat(),
            "mode": "PAPER" if PAPER_MODE else "PIONEX_LIVE_SPOT",
            "db": "SQLite WAL"
        }
        tmp = f"{SCALPER_STATE_FILE}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, SCALPER_STATE_FILE)
        except Exception as e:
            print(f"  [Aviso Estado] save_state falló: {e}", flush=True)

    def log_trade(self, symbol: str, side: str, price: float, amount: float, pnl: float, fee: float, note: str, order_id: str = "", target_order_id: str = ""):
        capital = price * amount
        self.db.insert_trade(
            symbol=symbol,
            side=side,
            price=price,
            amount=amount,
            capital=capital,
            pnl=pnl,
            fee=fee,
            note=note,
            order_id=order_id,
            target_order_id=target_order_id,
            mode="PAPER" if PAPER_MODE else "LIVE_SPOT"
        )
        self.refresh_stats()


# ====================== SCANNER DE ORDER FLOW & TELEMETRÍA ======================
_OHLCV_CACHE: Dict[str, Tuple[float, list]] = {}


def _cached_ohlcv(ccxt_sym: str, ttl: float = 45.0) -> list:
    """Velas 15m con caché corta: la señal no cambia cada 4s y así se reduce la carga REST."""
    now = time.time()
    hit = _OHLCV_CACHE.get(ccxt_sym)
    if hit and now - hit[0] < ttl:
        return hit[1]
    data = exchange.fetch_ohlcv(ccxt_sym, "15m", limit=20)
    _OHLCV_CACHE[ccxt_sym] = (now, data)
    return data


def fetch_full_radar_telemetry(bot: ScalperBot) -> List[Dict]:
    """
    Escanea los 13 pares líderes y genera telemetría de alta resolución.
    Calcula en tiempo real OBI (-1.0 a +1.0), RSI, EMA20 y Conviction Score.
    """
    rules = PionexLiveExecutor.get_symbol_rules()
    telemetry_list = []

    try:
        tickers = exchange.fetch_tickers(INSTITUTIONAL_SCALP_WHITELIST)
    except Exception:
        return bot.radar_telemetry

    for ccxt_sym in INSTITUTIONAL_SCALP_WHITELIST:
        pio_sym = ccxt_sym.replace("/", "_")
        sym_rule = rules.get(pio_sym, {"basePrecision": 2, "quotePrecision": 4, "minAmount": 10.0})
        t = tickers.get(ccxt_sym, {})
        curr_p = float(t.get("last", 0.0) or 0.0)
        chg_24h = float(t.get("percentage", 0.0) or 0.0)
        high_24h = float(t.get("high", curr_p) or curr_p)
        low_24h = float(t.get("low", curr_p) or curr_p)

        if curr_p <= 0:
            continue

        obi = 0.0
        spread_pct = 99.0
        best_ask = 0.0
        bid_pct = 50.0
        ask_pct = 50.0
        rsi = 50.0
        vol_spike = 1.0
        sma20 = curr_p
        range_pct = 0.0

        try:
            ob = exchange.fetch_order_book(ccxt_sym, limit=15)
            raw_bids = ob.get("bids", [])
            raw_asks = ob.get("asks", [])
            bids_vol = sum(b[1] for b in raw_bids)
            asks_vol = sum(a[1] for a in raw_asks)
            tot_depth = bids_vol + asks_vol
            if tot_depth > 0:
                obi = (bids_vol - asks_vol) / tot_depth
                bid_pct = (bids_vol / tot_depth) * 100.0
                ask_pct = (asks_vol / tot_depth) * 100.0

            # Stoikov Micro-price & Bid Wall Front-Running
            best_bid = float(raw_bids[0][0]) if raw_bids else curr_p * 0.999
            best_ask = float(raw_asks[0][0]) if raw_asks else curr_p * 1.001
            spread = max(0.0, best_ask - best_bid)
            spread_pct = (spread / curr_p) * 100.0 if curr_p > 0 else 0.0

            # Encontrar el Bid Wall dominante (mayor volumen en los primeros 5 niveles)
            bid_wall_price = best_bid
            max_bid_vol = 0.0
            for b in raw_bids[:5]:
                if b[1] > max_bid_vol:
                    max_bid_vol = b[1]
                    bid_wall_price = float(b[0])

            q_prec = sym_rule.get("quotePrecision", 4)
            tick_size = 10 ** (-q_prec)

            # Colocación cuantitativa en el libro (Stoikov 2018):
            # Prioridad de cola en Best Bid si el spread es estrecho (<= 0.08%).
            # O front-running 1 tick por encima del muro de compradores institucional si está cerca.
            if spread_pct <= 0.08:
                entry_limit = round(best_bid, q_prec)
            elif bid_wall_price >= curr_p * 0.9985:
                entry_limit = round(min(best_bid, bid_wall_price + tick_size), q_prec)
            else:
                entry_limit = round(best_bid, q_prec)

            ohlcv = _cached_ohlcv(ccxt_sym)
            atr_pct = 0.60
            dyn_target_pct = 0.0050
            dyn_stop_pct = 0.0180
            if len(ohlcv) >= 15:
                closes = [c[4] for c in ohlcv]
                volumes = [c[5] for c in ohlcv]
                sma20 = sum(closes[-15:]) / 15.0

                trs = []
                for k in range(1, len(ohlcv)):
                    hi_k, lo_k, cl_prev = ohlcv[k][2], ohlcv[k][3], ohlcv[k-1][4]
                    tr = max(hi_k - lo_k, abs(hi_k - cl_prev), abs(lo_k - cl_prev))
                    trs.append(tr)
                atr_abs = sum(trs[-14:]) / 14.0 if trs else (ohlcv[-1][2] - ohlcv[-1][3])
                atr_pct = (atr_abs / curr_p * 100.0) if curr_p > 0 else 0.60
                range_pct = atr_pct

                # Cálculo 100% dinámico por ATR (Cero números fijos / hardcodeados):
                # Target: 0.70x ATR (mínimo 0.35% para cubrir fees con ganancia limpia, máximo 1.20%)
                dyn_target_pct = max(0.0035, min(0.0120, round(0.70 * (atr_pct / 100.0), 4)))
                # Stop Catastrófico: 2.20x ATR (mínimo 1.50% para proteger del ruido, máximo 3.00%)
                dyn_stop_pct = max(0.0150, min(0.0300, round(2.20 * (atr_pct / 100.0), 4)))

                gains, losses = [], []
                for i in range(1, 15):
                    diff = closes[-15+i] - closes[-15+i-1]
                    gains.append(max(0.0, diff))
                    losses.append(max(0.0, -diff))
                avg_g = sum(gains) / 14.0 if gains else 0.0001
                avg_l = sum(losses) / 14.0 if losses else 0.0001
                rs = avg_g / (avg_l if avg_l > 0 else 0.0001)
                rsi = 100.0 - (100.0 / (1.0 + rs))

                avg_vol = sum(volumes[-15:]) / 15.0 if volumes else 1.0
                vol_spike = (volumes[-1] / avg_vol) if avg_vol > 0 else 1.0
        except Exception:
            q_prec = sym_rule.get("quotePrecision", 4)
            entry_limit = round(curr_p * 0.999, q_prec)

        # Filtro de Régimen Macro y Microestructura Estricta (Pro-Tendencia, Cero Cuchillos Cayendo):
        # 1. 24h Change: Estrictamente positivo o neutral (>= -0.20%). Prohibido comprar monedas en markdown.
        # 2. SMA20 (15m): Precio cotizando por encima de la media móvil promediada (curr_p >= sma20).
        # 3. OBI Institucional: Desbalance comprador robusto (obi >= 0.18 y bid_pct >= 58.0%).
        # 4. Momentum RSI Saludable: 49.0 <= rsi <= 68.0 (evita activos en colapso o sobrecomprados al límite).
        if FAST_MODE:
            # Sin sesgo de régimen: basta presión compradora inmediata, spread barato y volatilidad suficiente.
            # RSI < 80 evita comprar techos; en caída se compran rebotes (RSI bajo permitido).
            is_macro_aligned = True
            is_valid_flow = (obi >= 0.08) and (bid_pct >= 53.0) and (spread_pct <= FAST_MAX_SPREAD_PCT) \
                and (rsi <= 80.0) and (range_pct >= MIN_RANGE15_PCT)
            entry_limit = round(best_ask, q_prec)  # cruza el ask: fill inmediato (comisión maker = taker en Pionex)
        else:
            is_macro_aligned = (chg_24h >= -0.20) and (curr_p >= sma20)
            is_valid_flow = (obi >= 0.18) and (bid_pct >= 58.0) and is_macro_aligned and (49.0 <= rsi <= 68.0) and (range_pct >= MIN_RANGE15_PCT)

        score = (obi * 35.0) + (min(2.0, vol_spike) * 20.0) + (25.0 if curr_p > sma20 else 0.0) + (15.0 if chg_24h > 0 else 0.0) + ((rsi - 45.0) * 0.5)
        score = max(0.0, min(100.0, score))

        trigger_ready = is_valid_flow and (score >= 48.0)
        gap_to_trigger = max(0.0, round(48.0 - score, 1))

        if trigger_ready:
            flow_status = "🟢 DISPARO LISTO"
        elif score >= 30.0:
            flow_status = "🟡 ACUMULANDO"
        else:
            flow_status = "⚪ NEUTRAL"

        telemetry_list.append({
            "ccxt_symbol": ccxt_sym,
            "pio_symbol": pio_sym,
            "name": ccxt_sym.split("/")[0],
            "price": curr_p,
            "change_24h": round(chg_24h, 2),
            "high_24h": high_24h,
            "low_24h": low_24h,
            "obi": round(obi, 3),
            "bid_pct": round(bid_pct, 1),
            "ask_pct": round(ask_pct, 1),
            "rsi": round(rsi, 1),
            "vol_spike": round(vol_spike, 2),
            "range_pct": round(range_pct, 2),
            "atr_pct": round(atr_pct, 2),
            "dyn_target_pct": dyn_target_pct,
            "dyn_stop_pct": dyn_stop_pct,
            "score": round(score, 1),
            "entry_limit": entry_limit,
            "is_valid_flow": is_valid_flow,
            "trigger_ready": trigger_ready,
            "gap_to_trigger": gap_to_trigger,
            "status": flow_status
        })

    telemetry_list.sort(key=lambda x: x["score"], reverse=True)
    return telemetry_list


def telemetry_background_thread(bot: ScalperBot):
    """Hilo dedicado de escaneo continuo de alta frecuencia cada 2.5s."""
    print("  📡 [RADAR TELEMETRY ENGINE] Hilo de escaneo activo en segundo plano.", flush=True)
    last_err = ""
    while True:
        try:
            data = fetch_full_radar_telemetry(bot)
            with bot.data_lock:
                bot.radar_telemetry = data
            bot.scan_cycle += 1

            if data:
                top = data[0]
                if bot.scan_cycle % 3 == 0:
                    bot.add_log(
                        f"📡 Radar sweep #{bot.scan_cycle}: Top {top['name']} (Score {top['score']:.1f} | OBI {top['obi']:+.2f} | RSI {top['rsi']:.1f})",
                        "radar"
                    )
            time.sleep(4.0)
        except Exception as e:
            if str(e) != last_err:
                last_err = str(e)
                print(f"  [Radar Error] {e}", flush=True)
            time.sleep(6.0)


# ====================== DASHBOARD HTTP LOCAL ULTRA-VISUAL ======================
class ScalperDashboardHandler(http.server.BaseHTTPRequestHandler):
    bot_ref: Optional[ScalperBot] = None

    def do_GET(self):
        if self.path.startswith("/api/status"):
            b = self.bot_ref
            if not b:
                self.send_response(500)
                self.end_headers()
                return

            with b.data_lock:
                telemetry = list(b.radar_telemetry)

            # Saldo y Equity Total Vivo
            free_cash = b.cash
            frozen_cash = b.frozen
            equity = b.equity()

            win_rate = (b.wins / b.total_trades * 100.0) if b.total_trades > 0 else 0.0

            trades_list = b.db.get_recent_trades(50)
            events_list = list(b.event_log)

            data = {
                "mode": "SOLO LECTURA (radar)" if DASHBOARD_ONLY else ("PAPER (?rdenes simuladas, datos Pionex)" if PAPER_MODE else "PIONEX LIVE SPOT"),
                "storage": "SQLite WAL",
                "cash": round(free_cash, 2),
                "frozen": round(frozen_cash, 2),
                "equity": round(equity, 2),
                "equity_curve": b.db.get_equity_curve(300),
                "realized_pnl": round(b.realized_pnl, 4),
                "wins": b.wins,
                "losses": b.losses,
                "total_trades": b.total_trades,
                "win_rate": round(win_rate, 1),
                "status_msg": b.status_msg,
                "scan_cycle": b.scan_cycle,
                "active_trade": b.active_trade.to_dict() if b.active_trade else None,
                "pending_order": b.pending_order.to_dict() if b.pending_order else None,
                "top_candidate": telemetry[0] if telemetry else None,
                "radar_telemetry": telemetry,
                "event_log": events_list,
                "trades": trades_list
            }

            encoded = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(encoded)
            return

        if self.path.split("?")[0] not in ("/", "/index.html"):
            self.send_response(404)
            self.end_headers()
            return

        # HTML Dashboard en vivo
        html = get_scalper_dashboard_html()
        encoded_html = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded_html)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(encoded_html)

    def log_message(self, format, *args):
        pass


def _dashboard_html_raw() -> str:
    return """<!DOCTYPE html>
<html lang="es">
<head>
    <title>THE 1-DOLLAR SCALPER | Pionex Live Spot Telemetry Engine</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        :root {
            --bg-dark: #080b11;
            --card-bg: #111622;
            --border: #1f2738;
            --blue: #388bfd;
            --green: #238636;
            --neon-green: #3fb950;
            --red: #f85149;
            --gold: #d29922;
            --text-main: #f0f6fc;
            --text-dim: #8b949e;
        }
        body {
            background: var(--bg-dark);
            color: var(--text-main);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            padding: 20px;
            margin: 0;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 16px;
            margin-bottom: 20px;
            flex-wrap: wrap;
            gap: 12px;
        }
        .title-area {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .title {
            font-size: 22px;
            font-weight: 900;
            color: #58a6ff;
            letter-spacing: -0.5px;
        }
        .radar-spinner {
            width: 24px;
            height: 24px;
            border: 3px solid rgba(56, 139, 253, 0.2);
            border-top: 3px solid #58a6ff;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        
        .badge-live {
            background: rgba(46, 160, 67, 0.15);
            color: #3fb950;
            border: 1px solid rgba(46, 160, 67, 0.4);
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .pulse-dot {
            width: 8px;
            height: 8px;
            background: #3fb950;
            border-radius: 50%;
            animation: pulse-ring 1.5s cubic-bezier(0.215, 0.61, 0.355, 1) infinite;
        }
        @keyframes pulse-ring {
            0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(63, 185, 80, 0.7); }
            70% { transform: scale(1.1); box-shadow: 0 0 0 8px rgba(63, 185, 80, 0); }
            100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(63, 185, 80, 0); }
        }

        .banner {
            background: linear-gradient(90deg, rgba(56, 139, 253, 0.08) 0%, rgba(35, 134, 54, 0.08) 100%);
            border: 1px solid #23344d;
            border-left: 4px solid #388bfd;
            padding: 12px 18px;
            border-radius: 8px;
            font-size: 13px;
            margin-bottom: 20px;
            color: #9ac2f7;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
        }

        .grid-kpis {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
            margin-bottom: 20px;
        }
        .card-kpi {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 15px;
            transition: all 0.2s ease;
        }
        .card-kpi:hover {
            border-color: #388bfd;
            transform: translateY(-2px);
        }
        .kpi-label {
            font-size: 11px;
            color: var(--text-dim);
            text-transform: uppercase;
            font-weight: 700;
            letter-spacing: 0.5px;
            margin-bottom: 6px;
        }
        .kpi-val {
            font-size: 24px;
            font-weight: 800;
            font-family: monospace;
            color: #ffffff;
        }
        .val-green { color: var(--neon-green); }
        .val-gold { color: var(--gold); }

        /* SPOTLIGHT HERO CARD */
        .spotlight-card {
            background: linear-gradient(135deg, #121929 0%, #0d121c 100%);
            border: 2px solid #388bfd;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
            position: relative;
            overflow: hidden;
        }
        .spotlight-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            flex-wrap: wrap;
            gap: 10px;
        }
        .spotlight-title {
            font-size: 18px;
            font-weight: 800;
            color: #58a6ff;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .duel-bar-wrapper {
            margin: 12px 0;
        }
        .duel-bar-labels {
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            font-family: monospace;
            font-weight: 700;
            margin-bottom: 4px;
        }
        .duel-bar {
            height: 12px;
            border-radius: 6px;
            overflow: hidden;
            display: flex;
            background: #21262d;
            border: 1px solid #30363d;
        }
        .bar-bids {
            background: linear-gradient(90deg, #238636, #3fb950);
            height: 100%;
            transition: width 0.4s ease;
        }
        .bar-asks {
            background: linear-gradient(90deg, #f85149, #da3633);
            height: 100%;
            transition: width 0.4s ease;
        }

        /* RADAR MATRIX TABLE */
        .radar-card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            flex-wrap: wrap;
            gap: 10px;
        }
        .section-title {
            font-size: 16px;
            font-weight: 800;
            color: #58a6ff;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            font-family: monospace;
        }
        th {
            text-align: left;
            padding: 10px;
            border-bottom: 2px solid var(--border);
            color: var(--text-dim);
            font-size: 11px;
            text-transform: uppercase;
            font-weight: 700;
        }
        td {
            padding: 10px;
            border-bottom: 1px solid #161c28;
            vertical-align: middle;
        }
        tr:hover {
            background: rgba(56, 139, 253, 0.04);
        }
        .coin-cell {
            display: flex;
            align-items: center;
            gap: 8px;
            font-weight: 800;
            color: #ffffff;
            font-size: 14px;
        }
        .coin-rank {
            background: #1f2738;
            color: #8b949e;
            width: 20px;
            height: 20px;
            border-radius: 4px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: bold;
        }
        .rank-top {
            background: rgba(56, 139, 253, 0.25);
            color: #58a6ff;
            border: 1px solid rgba(56, 139, 253, 0.5);
        }

        .score-bar-bg {
            width: 110px;
            height: 8px;
            background: #1f2738;
            border-radius: 4px;
            overflow: hidden;
            position: relative;
            display: inline-block;
            vertical-align: middle;
            margin-right: 6px;
        }
        .score-bar-fill {
            height: 100%;
            border-radius: 4px;
            background: linear-gradient(90deg, #388bfd, #3fb950);
            transition: width 0.3s ease;
        }
        .score-target-mark {
            position: absolute;
            left: 45%;
            top: 0;
            bottom: 0;
            width: 2px;
            background: #ffffff;
            opacity: 0.7;
        }

        .tag-ready {
            background: rgba(46, 160, 67, 0.2);
            color: #3fb950;
            border: 1px solid rgba(46, 160, 67, 0.4);
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: bold;
            display: inline-block;
        }
        .tag-warm {
            background: rgba(210, 153, 34, 0.2);
            color: #d29922;
            border: 1px solid rgba(210, 153, 34, 0.4);
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: bold;
            display: inline-block;
        }
        .tag-neutral {
            background: rgba(139, 148, 158, 0.15);
            color: #8b949e;
            border: 1px solid rgba(139, 148, 158, 0.3);
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            display: inline-block;
        }

        /* CYBER TERMINAL EVENT STREAM */
        .terminal-box {
            background: #05080e;
            border: 1px solid #1c2333;
            border-radius: 10px;
            padding: 15px;
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 12px;
            max-height: 160px;
            overflow-y: auto;
            margin-bottom: 20px;
            box-shadow: inset 0 2px 8px rgba(0,0,0,0.6);
        }
        .log-row {
            padding: 3px 0;
            line-height: 1.4;
            display: flex;
            gap: 8px;
        }
        .log-time { color: #58a6ff; }
        .log-text-radar { color: #7ee787; }
        .log-text-trade { color: #ffa657; font-weight: bold; }
        .log-text-info { color: #c9d1d9; }

        .flash-green { animation: flash-g 0.8s ease; }
        @keyframes flash-g {
            0% { background-color: rgba(63, 185, 80, 0.4); color: #ffffff; }
            100% { background-color: transparent; }
        }
        .flash-red { animation: flash-r 0.8s ease; }
        @keyframes flash-r {
            0% { background-color: rgba(248, 81, 73, 0.4); color: #ffffff; }
            100% { background-color: transparent; }
        }
    </style>
</head>
<body>
    <!-- Top Header -->
    <div class="header">
        <div class="title-area">
            <div class="radar-spinner"></div>
            <div>
                <div class="title">THE 1-DOLLAR SCALPER <span style="font-size: 13px; color: var(--text-dim); font-weight: normal;">| Pionex Spot Live Engine</span></div>
                <div style="font-size: 11px; color: var(--text-dim); margin-top: 2px;">Vigilancia LOB en Alta Frecuencia • Persistencia SQLite WAL • Maker Límite Stoikov • Salida +0.95% (~+$0.57 USD) • Stop -0.70%</div>
            </div>
        </div>
        <div class="badge-live">
            <div class="pulse-dot"></div>
            <span id="conn-badge">PIONEX CUENTA REAL VIVA (SQLite)</span>
        </div>
    </div>

    <!-- Banner Info -->
    <div class="banner">
        <div>
            🛡️ <b>MOMENTUM SNIPER SPOT:</b> Radar analizando libros de órdenes (LOB Imbalance) de Altcoins Ágiles de Alta Beta en tiempo real (excluye BTC/ETH). Cero mallas atrapadas. El capital entra en soporte Stoikov, cobra el impulso (+0.95%) y vuelve 100% a caja líquida.
        </div>
        <div style="font-family: monospace; font-size: 12px; color: #58a6ff;">
            Barrido #<span id="cycle-count">0</span> • Base de Datos: <span style="color:#3fb950; font-weight:bold;">SQLite WAL (scalper_vault.db)</span>
        </div>
    </div>

    <!-- KPIs Bar -->
    <div class="grid-kpis">
        <div class="card-kpi" id="card-cash" style="border-top: 3px solid #388bfd;">
            <div class="kpi-label">Saldo Pionex USDT (Libre)</div>
            <div class="kpi-val" id="cash">$0.00</div>
        </div>
        <div class="card-kpi" id="card-frozen" style="border-top: 3px solid #d29922;">
            <div class="kpi-label">En Orden Maker (Frozen)</div>
            <div class="kpi-val val-gold" id="frozen">$0.00</div>
        </div>
        <div class="card-kpi" id="card-equity" style="border-top: 3px solid #8b949e;">
            <div class="kpi-label">Equity Total Vivo</div>
            <div class="kpi-val" id="equity">$0.00</div>
        </div>
        <div class="card-kpi" id="card-pnl" style="border-top: 3px solid #8b949e;">
            <div class="kpi-label">Ganancia Neta (Live)</div>
            <div class="kpi-val" id="pnl">$0.00</div>
        </div>
        <div class="card-kpi" id="card-winrate" style="border-top: 3px solid #8b949e;">
            <div class="kpi-label">Win Rate Real</div>
            <div class="kpi-val" id="winrate">0.0%</div>
        </div>
        <div class="card-kpi" id="card-trades" style="border-top: 3px solid #a371f7;">
            <div class="kpi-label">Disparos Cerrados</div>
            <div class="kpi-val" id="trades">0</div>
        </div>
    </div>

    <!-- SPOTLIGHT HERO CARD -->
    <div class="spotlight-card" id="spotlight-box">
        <div class="spotlight-header">
            <div class="spotlight-title" id="spotlight-title">
                <span>🎯 CANDIDATO LÍDER EN EL RADAR:</span>
                <span id="spotlight-sym" style="color: #ffffff; background: #1f2738; padding: 2px 10px; border-radius: 6px;">SUI/USDT</span>
            </div>
            <div id="spotlight-badge" class="tag-warm">PUNTAJE ELEVADO</div>
        </div>

        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; font-family: monospace; font-size: 13px;">
            <div>
                <span style="color: var(--text-dim); font-size: 11px; display: block;">PRECIO EN VIVO</span>
                <span id="spotlight-price" style="font-size: 22px; font-weight: 800; color: #ffffff;">$0.0000</span>
                <span id="spotlight-chg" style="margin-left: 6px; font-weight: bold;">(+0.00%)</span>
            </div>
            <div>
                <span style="color: var(--text-dim); font-size: 11px; display: block;">ORDEN MAKER LÍMITE (STOIKOV LOB)</span>
                <span id="spotlight-entry" style="font-size: 18px; font-weight: 700; color: #58a6ff;">$0.0000</span>
                <span style="color: var(--text-dim); font-size: 11px;">(Best Bid / Soporte Muro)</span>
            </div>
            <div>
                <span id="label-target" style="color: var(--text-dim); font-size: 11px; display: block;">TARGET DINÁMICO ATR (+0.70x ATR)</span>
                <span id="spotlight-target" style="font-size: 18px; font-weight: 700; color: #3fb950;">$0.0000</span>
                <span id="spotlight-target-sub" style="color: #3fb950; font-size: 11px;">(Take Profit Dinámico)</span>
            </div>
            <div>
                <span id="label-stop" style="color: var(--text-dim); font-size: 11px; display: block;">STOP LOSS DEFENSIVO ATR (-2.20x ATR)</span>
                <span id="spotlight-stop" style="font-size: 18px; font-weight: 700; color: #f85149;">$0.0000</span>
                <span id="spotlight-stop-sub" style="color: #f85149; font-size: 11px;">(Inmunidad a Ruido 1m)</span>
            </div>
        </div>

        <!-- DUEL BAR LOB -->
        <div class="duel-bar-wrapper">
            <div class="duel-bar-labels">
                <span style="color: #3fb950;">🟢 COMPRADORES (BIDS): <b id="duel-bids-pct">50.0%</b></span>
                <span style="color: var(--text-dim);">DESEQUILIBRIO DE LIBRO (OBI): <b id="duel-obi">+0.00</b></span>
                <span style="color: #f85149;">🔴 VENDEDORES (ASKS): <b id="duel-asks-pct">50.0%</b></span>
            </div>
            <div class="duel-bar">
                <div id="bar-bids" class="bar-bids" style="width: 50%;"></div>
                <div id="bar-asks" class="bar-asks" style="width: 50%;"></div>
            </div>
        </div>
    </div>

    <!-- CYBER TERMINAL EVENT STREAM -->
    <div style="margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 13px; font-weight: 700; color: #58a6ff;">⚡ REGISTRO DE PENSAMIENTO & TELEMETRÍA EN VIVO (EVENT STREAM)</span>
        <span style="font-size: 11px; color: var(--text-dim); font-family: monospace;">Streaming SQLite WAL cada 1.5s</span>
    </div>
    <div class="terminal-box" id="terminal-feed">
        <div class="log-row"><span class="log-time">[--:--:--]</span> <span class="log-text-info">Iniciando consola de telemetría en vivo...</span></div>
    </div>

    <!-- RADAR MATRIX TABLE (13 MONEDAS EN VIVO) -->
    <div class="radar-card">
        <div class="section-header">
            <div class="section-title">
                <span>📊 RADAR DE ORDER FLOW: ALTCOINS ÁGILES EN PIONEX SPOT</span>
            </div>
            <span style="font-size: 12px; color: var(--text-dim);">Ordenado en vivo por Puntaje de Convicción Cuantitativa</span>
        </div>
        <div style="overflow-x: auto;">
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Par</th>
                        <th>Precio Vivo</th>
                        <th>24h %</th>
                        <th>LOB Desequilibrio (Bids vs Asks)</th>
                        <th>RSI 15m</th>
                        <th>ATR 15m</th>
                        <th>Volumen Spike</th>
                        <th>Puntaje de Convicción</th>
                        <th>Entrada Maker Proyectada</th>
                        <th>Estado Radar</th>
                    </tr>
                </thead>
                <tbody id="radar-tbody">
                    <tr><td colspan="11" style="text-align: center; color: var(--text-dim); padding: 25px;">Cargando telemetría de alta frecuencia...</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <!-- AUDITORÍA DE ÓRDENES EN PIONEX (SQLITE) -->
    <div class="radar-card">
        <div class="section-header">
            <div class="section-title">
                <span>📋 AUDITORÍA DE ÓRDENES REALES EN PIONEX SPOT (SQLITE WAL)</span>
            </div>
            <span style="font-size: 12px; color: var(--text-dim);">Historial persistente en scalper_vault.db</span>
        </div>
        <div style="overflow-x: auto;">
            <table>
                <thead>
                    <tr>
                        <th>Hora</th>
                        <th>Par</th>
                        <th>Acción</th>
                        <th>Precio</th>
                        <th>Cantidad</th>
                        <th>PnL Neto</th>
                        <th>Fee Pionex</th>
                        <th>Modo / Ticket</th>
                    </tr>
                </thead>
                <tbody id="trades-tbody">
                    <tr><td colspan="8" style="text-align: center; color: var(--text-dim); padding: 20px;">Cargando órdenes desde SQLite...</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <script>
        let prevPrices = {};

        async function updateDashboard() {
            const endpoints = [
                '/api/status',
                'http://localhost:8899/api/status',
                'http://127.0.0.1:8899/api/status'
            ];

            let res = null;
            for (const ep of endpoints) {
                try {
                    res = await fetch(ep, { cache: 'no-store' });
                    if (res && res.ok) break;
                } catch(e) {}
            }

            const setTxt = (id, val) => { const el = document.getElementById(id); if (el) el.innerText = val; };
            const setHtml = (id, val) => { const el = document.getElementById(id); if (el) el.innerHTML = val; };

            try {
                if (!res || !res.ok) {
                    setTxt('conn-badge', 'CONECTANDO A :8899...');
                    return;
                }
                const d = await res.json();
                setTxt('conn-badge', 'PIONEX CUENTA REAL VIVA (SQLite)');

                // 1. KPIs Dinámicos con Colores Reales (Verde solo si hay ganancia)
                setTxt('cash', '$' + Number(d.cash || 0).toFixed(2));
                setTxt('frozen', '$' + Number(d.frozen || 0).toFixed(2));

                // Equity Dinámico
                const eqVal = Number(d.equity || 0);
                const initCap = 70.35;
                const eqDiff = eqVal - initCap;
                const eqEl = document.getElementById('equity');
                const eqCard = document.getElementById('card-equity');
                if (eqEl) {
                    eqEl.innerText = '$' + eqVal.toFixed(2);
                    eqEl.style.color = eqDiff >= 0.05 ? '#3fb950' : (eqDiff <= -0.20 ? '#f85149' : '#d29922');
                }
                if (eqCard) {
                    eqCard.style.borderTopColor = eqDiff >= 0.05 ? '#3fb950' : (eqDiff <= -0.20 ? '#f85149' : '#d29922');
                }

                // Ganancia Neta (PnL) Dinámica
                const pnlVal = Number(d.realized_pnl || 0);
                const pnlEl = document.getElementById('pnl');
                const pnlCard = document.getElementById('card-pnl');
                if (pnlEl) {
                    pnlEl.innerText = (pnlVal > 0 ? '+$' : (pnlVal < 0 ? '-$' : '$')) + Math.abs(pnlVal).toFixed(4);
                    pnlEl.style.color = pnlVal > 0.0001 ? '#3fb950' : (pnlVal < -0.0001 ? '#f85149' : '#8b949e');
                }
                if (pnlCard) {
                    pnlCard.style.borderTopColor = pnlVal > 0.0001 ? '#3fb950' : (pnlVal < -0.0001 ? '#f85149' : '#8b949e');
                }

                // Win Rate Dinámico (Matemático Real)
                const totTrades = Number(d.total_trades || 0);
                const wins = Number(d.wins || 0);
                const wrVal = totTrades > 0 ? (wins / totTrades * 100.0) : 0.0;
                const wrEl = document.getElementById('winrate');
                const wrCard = document.getElementById('card-winrate');
                if (wrEl) {
                    wrEl.innerText = totTrades > 0 ? wrVal.toFixed(1) + '%' : '0.0%';
                    wrEl.style.color = totTrades === 0 ? '#8b949e' : (wrVal >= 50.0 ? '#3fb950' : '#f85149');
                }
                if (wrCard) {
                    wrCard.style.borderTopColor = totTrades === 0 ? '#8b949e' : (wrVal >= 50.0 ? '#3fb950' : '#f85149');
                }

                setTxt('trades', totTrades + ' (' + wins + 'W / ' + Number(d.losses || 0) + 'L)');
                setTxt('cycle-count', d.scan_cycle || 0);

                // 2. Spotlight Hero Card
                const top = d.top_candidate;
                const act = d.active_trade;
                const pend = d.pending_order;

                const box = document.getElementById('spotlight-box');
                const badge = document.getElementById('spotlight-badge');
                const sym = document.getElementById('spotlight-sym');

                if (act) {
                    if (box) box.style.borderColor = '#3fb950';
                    setHtml('spotlight-title', '<span style="color:#3fb950;">🎯 EN POSICIÓN REAL EN PIONEX:</span>');
                    setTxt('spotlight-sym', act.symbol);
                    if (sym) sym.style.background = '#238636';
                    if (badge) { badge.className = 'tag-ready'; badge.innerText = 'ORDEN VENTA PIONEX #' + (act.target_order_id || 'ACTIVA'); }
                    setTxt('spotlight-price', '$' + Number(act.entry_price).toFixed(4));
                    setTxt('spotlight-entry', '$' + Number(act.entry_price).toFixed(4));
                    const actTgtPct = (act.target_pct || 0.0075) * 100;
                    const actStpPct = (act.stop_pct || 0.0220) * 100;
                    setHtml('label-target', `TARGET DINÁMICO ATR (+${actTgtPct.toFixed(2)}%)`);
                    setHtml('label-stop', `STOP DEFENSIVO ATR (-${actStpPct.toFixed(2)}%)`);
                    setTxt('spotlight-target', '$' + Number(act.target_price).toFixed(4));
                    setTxt('spotlight-stop', '$' + Number(act.stop_price).toFixed(4));
                } else if (pend) {
                    if (box) box.style.borderColor = '#d29922';
                    setHtml('spotlight-title', '<span style="color:#d29922;">⏳ ORDEN MAKER LÍMITE EN PIONEX:</span>');
                    setTxt('spotlight-sym', pend.symbol);
                    if (sym) sym.style.background = '#d29922';
                    if (badge) { badge.className = 'tag-warm'; badge.innerText = 'ESPERANDO RETROCESO (#' + pend.order_id + ')'; }
                    setTxt('spotlight-price', '$' + Number(pend.limit_price).toFixed(4));
                    setTxt('spotlight-entry', '$' + Number(pend.limit_price).toFixed(4));
                    const pTgtPct = (pend.target_pct || (top ? top.dyn_target_pct : 0.0075)) * 100;
                    const pStpPct = (pend.stop_pct || (top ? top.dyn_stop_pct : 0.0220)) * 100;
                    setHtml('label-target', `TARGET DINÁMICO ATR (+${pTgtPct.toFixed(2)}%)`);
                    setHtml('label-stop', `STOP DEFENSIVO ATR (-${pStpPct.toFixed(2)}%)`);
                    setTxt('spotlight-target', '$' + (Number(pend.limit_price) * (1 + pTgtPct / 100)).toFixed(4));
                    setTxt('spotlight-stop', '$' + (Number(pend.limit_price) * (1 - pStpPct / 100)).toFixed(4));
                    if (top) {
                        setTxt('duel-bids-pct', Number(top.bid_pct || 50).toFixed(1) + '%');
                        setTxt('duel-asks-pct', Number(top.ask_pct || 50).toFixed(1) + '%');
                        const obi = Number(top.obi || 0);
                        setTxt('duel-obi', (obi >= 0 ? '+' : '') + obi.toFixed(3));
                        const bBids = document.getElementById('bar-bids');
                        const bAsks = document.getElementById('bar-asks');
                        if (bBids) bBids.style.width = (top.bid_pct || 50) + '%';
                        if (bAsks) bAsks.style.width = (top.ask_pct || 50) + '%';
                    }
                } else if (top) {
                    if (box) box.style.borderColor = '#388bfd';
                    setHtml('spotlight-title', '<span>🎯 CANDIDATO LÍDER EN EL RADAR:</span>');
                    setTxt('spotlight-sym', top.ccxt_symbol);
                    if (sym) sym.style.background = '#1f2738';
                    if (badge) {
                        badge.className = top.trigger_ready ? 'tag-ready' : (top.score >= 30 ? 'tag-warm' : 'tag-neutral');
                        badge.innerText = top.status;
                    }
                    setTxt('spotlight-price', '$' + Number(top.price).toFixed(4));
                    const chg = Number(top.change_24h || 0);
                    const chgColor = chg >= 0 ? '#3fb950' : '#f85149';
                    setHtml('spotlight-chg', '<span style="color:' + chgColor + '">' + (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%</span>');
                    setTxt('spotlight-entry', '$' + Number(top.entry_limit).toFixed(4));
                    const tTgtPct = (top.dyn_target_pct || 0.0075) * 100;
                    const tStpPct = (top.dyn_stop_pct || 0.0220) * 100;
                    setHtml('label-target', `TARGET DINÁMICO ATR (+${tTgtPct.toFixed(2)}%)`);
                    setHtml('label-stop', `STOP DEFENSIVO ATR (-${tStpPct.toFixed(2)}%)`);
                    setTxt('spotlight-target', '$' + (Number(top.entry_limit) * (1 + tTgtPct / 100)).toFixed(4));
                    setTxt('spotlight-stop', '$' + (Number(top.entry_limit) * (1 - tStpPct / 100)).toFixed(4));

                    // Duel Bar
                    setTxt('duel-bids-pct', Number(top.bid_pct).toFixed(1) + '%');
                    setTxt('duel-asks-pct', Number(top.ask_pct).toFixed(1) + '%');
                    const obi = Number(top.obi || 0);
                    setTxt('duel-obi', (obi >= 0 ? '+' : '') + obi.toFixed(3));
                    const bBids = document.getElementById('bar-bids');
                    const bAsks = document.getElementById('bar-asks');
                    if (bBids) bBids.style.width = top.bid_pct + '%';
                    if (bAsks) bAsks.style.width = top.ask_pct + '%';
                }

                // 3. Radar Matrix Table (13 Coins)
                const tbody = document.getElementById('radar-tbody');
                if (tbody && d.radar_telemetry && d.radar_telemetry.length > 0) {
                    let rows = '';
                    d.radar_telemetry.forEach((c, idx) => {
                        const rankClass = idx === 0 ? 'coin-rank rank-top' : 'coin-rank';
                        const chg = Number(c.change_24h || 0);
                        const chgSign = chg >= 0 ? '+' : '';
                        const chgColor = chg >= 0 ? '#3fb950' : '#f85149';
                        
                        const p = Number(c.price || 0);
                        const prev = prevPrices[c.ccxt_symbol];
                        let flashClass = '';
                        if (prev !== undefined) {
                            if (p > prev) flashClass = 'flash-green';
                            else if (p < prev) flashClass = 'flash-red';
                        }
                        prevPrices[c.ccxt_symbol] = p;

                        const tagClass = c.trigger_ready ? 'tag-ready' : (c.score >= 30 ? 'tag-warm' : 'tag-neutral');
                        const obi = Number(c.obi || 0);
                        const obiColor = obi >= 0.18 ? '#3fb950' : (obi >= 0 ? '#58a6ff' : '#f85149');

                        rows += `<tr>
                            <td><span class="${rankClass}">${idx + 1}</span></td>
                            <td><div class="coin-cell"><span>${c.name}</span><span style="font-size:10px; color:#8b949e; font-weight:normal;">/USDT</span></div></td>
                            <td class="${flashClass}" style="font-weight: bold; color: #ffffff;">$${p.toFixed(4)}</td>
                            <td style="color: ${chgColor}; font-weight: bold;">${chgSign}${chg.toFixed(2)}%</td>
                            <td>
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <span style="color: ${obiColor}; font-weight: bold; width: 55px;">${obi >= 0 ? '+' : ''}${obi.toFixed(3)}</span>
                                    <div style="width: 70px; height: 6px; background: #21262d; border-radius: 3px; display: flex; overflow: hidden;">
                                        <div style="width: ${c.bid_pct}%; background: #3fb950;"></div>
                                        <div style="width: ${c.ask_pct}%; background: #f85149;"></div>
                                    </div>
                                    <span style="font-size: 11px; color: #8b949e;">${Number(c.bid_pct).toFixed(0)}% Bids</span>
                                </div>
                            </td>
                            <td><span style="color: ${c.rsi >= 47 && c.rsi <= 65 ? '#3fb950' : '#d29922'}; font-weight: bold;">${Number(c.rsi).toFixed(1)}</span></td>
                            <td><span style="color: #58a6ff; font-weight: bold;">${Number(c.atr_pct || 0).toFixed(2)}%</span></td>
                            <td><span style="color: #c9d1d9;">${Number(c.vol_spike).toFixed(2)}x</span></td>
                            <td>
                                <div class="score-bar-bg">
                                    <div class="score-bar-fill" style="width: ${Math.min(100, c.score)}%;"></div>
                                    <div class="score-target-mark" title="Objetivo Disparo: 45.0"></div>
                                </div>
                                <span style="font-weight: bold; color: ${c.score >= 45 ? '#3fb950' : '#ffffff'};">${Number(c.score).toFixed(1)}</span>
                            </td>
                            <td style="color: #58a6ff; font-weight: bold;">$${Number(c.entry_limit).toFixed(4)}</td>
                            <td><span class="${tagClass}">${c.status}</span></td>
                        </tr>`;
                    });
                    tbody.innerHTML = rows;
                }

                // 4. Cyber Terminal Event Stream
                const term = document.getElementById('terminal-feed');
                if (term && d.event_log && d.event_log.length > 0) {
                    let logHtml = '';
                    d.event_log.forEach(l => {
                        const typeClass = l.type === 'radar' ? 'log-text-radar' : (l.type === 'trade' ? 'log-text-trade' : 'log-text-info');
                        logHtml += `<div class="log-row"><span class="log-time">[${l.time}]</span> <span class="${typeClass}">${l.text}</span></div>`;
                    });
                    term.innerHTML = logHtml;
                    term.scrollTop = term.scrollHeight;
                }

                // 5. Trades Table (SQLite)
                const tradesBody = document.getElementById('trades-tbody');
                if (tradesBody && d.trades && d.trades.length > 0) {
                    let tHtml = '';
                    d.trades.forEach(t => {
                        const isBuy = t.side === 'BUY';
                        const badge = isBuy ? '<span class="tag-ready">🟢 COMPRA</span>' : '<span style="background:rgba(163,113,247,0.2); color:#bc8cff; padding:2px 6px; border-radius:4px; font-weight:bold;">🔴 VENTA</span>';
                        const pnl = Number(t.pnl || 0);
                        const pnlColor = pnl > 0 ? '#3fb950' : (pnl < 0 ? '#f85149' : '#8b949e');
                        const pnlStr = !isBuy ? ('<span style="color:' + pnlColor + '; font-weight:bold;">' + (pnl >= 0 ? '+' : '') + '$' + pnl.toFixed(4) + '</span>') : '<span style="color:#8b949e;">-</span>';
                        const tTime = t.timestamp ? (t.timestamp.includes('T') ? t.timestamp.split('T')[1].split('.')[0] : t.timestamp) : '--:--';
                        const noteStr = t.note || (t.mode ? ('Modo: ' + t.mode) : '');
                        tHtml += `<tr>
                            <td style="color:#8b949e;">${tTime}</td>
                            <td style="font-weight:bold; color:#f0f6fc;">${t.symbol}</td>
                            <td>${badge}</td>
                            <td style="color:#f0f6fc;">$${Number(t.price || 0).toFixed(4)}</td>
                            <td style="color:#8b949e;">${Number(t.amount || 0).toFixed(2)}</td>
                            <td>${pnlStr}</td>
                            <td style="color:#8b949e;">$${Number(t.fee || 0).toFixed(4)}</td>
                            <td style="color:#e6edf3; font-family:sans-serif; font-size:12px;">${noteStr}</td>
                        </tr>`;
                    });
                    tradesBody.innerHTML = tHtml;
                } else if (tradesBody) {
                    tradesBody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--text-dim); padding: 20px;">Esperando primera operación en Pionex...</td></tr>';
                }

            } catch (err) {
                console.error("Dashboard update error:", err);
            }
        }

        setInterval(updateDashboard, 2500);
        updateDashboard();
    </script>
</body>
</html>"""


def get_scalper_dashboard_html() -> str:
    html = _dashboard_html_raw()
    return (html.replace("1.0095", f"{1 + TARGET_PROFIT_PCT:.4f}").replace("0.9930", f"{1 - STOP_LOSS_PCT:.4f}")
            .replace("+0.95%", f"+{TARGET_PROFIT_PCT*100:.2f}%").replace("-0.70%", f"-{STOP_LOSS_PCT*100:.2f}%")
            .replace("~+$0.57 USD", f"{'MODO RÁPIDO' if FAST_MODE else 'clásico'}"))


def start_scalper_dashboard(bot: ScalperBot, port: int = SCALPER_HTTP_PORT):
    ScalperDashboardHandler.bot_ref = bot
    
    try:
        with open(SCALPER_STANDALONE_HTML, "w", encoding="utf-8") as f:
            f.write(get_scalper_dashboard_html())
    except Exception:
        pass

    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), ScalperDashboardHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        print(f"  🌐 [1-DOLLAR SCALPER DASHBOARD] Accede en vivo: http://localhost:{port}", flush=True)
    except Exception as e:
        print(f"  [Scalper HTTP Server Warning] {e}", flush=True)


# ====================== BUCLE OPERATIVO DEL SCALPER ======================
def wait_for_fill(pio_sym: str, order_id: str, attempts: int = 6, delay: float = 1.0) -> Optional[Dict]:
    """Espera a que una orden aparezca cerrada con fills y devuelve su resumen real."""
    for _ in range(attempts):
        fill = PionexLiveExecutor.summarize_fill(PionexLiveExecutor.get_order(pio_sym, order_id))
        if fill and fill["status"] == "CLOSED":
            return fill
        time.sleep(delay)
    return None


def close_trade(bot: ScalperBot, trade: ScalperTrade, fill: Optional[Dict], fallback_price: float, note: str, is_stop: bool = False):
    """Registra la salida con precio/comisiones reales (o estimados si Pionex no devolvió el fill)."""
    if fill:
        exit_price, amount, proceeds, exit_fee = fill["price"], fill["size"], fill["amount"], fill["fee_usdt"]
    else:
        exit_price, amount = fallback_price, trade.amount
        proceeds = amount * exit_price
        exit_fee = proceeds * PIONEX_FEE_RATE
        note += " [fill estimado]"

    # La comisi?n de compra de Pionex se cobra en la moneda base (ya reduce `amount`): restarla otra vez la contar?a doble.
    pnl = proceeds - exit_fee - trade.capital
    bot.log_trade(
        symbol=trade.symbol, side="SELL", price=exit_price, amount=amount, pnl=pnl, fee=exit_fee,
        note=f"{note} | PnL neto {pnl:+.4f} USDT", target_order_id=trade.target_order_id
    )
    icon = "🎯💵" if pnl > 0 else "🛑"
    bot.add_log(f"{icon} Salida {trade.symbol} @ ${exit_price:.4f}: {pnl:+.4f} USDT ({note})", "trade")
    print(f"\n  {icon} [SALIDA {trade.symbol}] {pnl:+.4f} USDT | {note}\n", flush=True)
    if is_stop or pnl < 0:
        bot.cooldowns[trade.symbol] = time.time() + STOP_COOLDOWN_SECS
    bot.active_trade = None
    bot.sync_balance()
    bot.status_msg = f"Última salida {pnl:+.2f} USDT. Caja Pionex: ${bot.cash:.2f} USDT."
    bot.save_state()


def market_exit(bot: ScalperBot, trade: ScalperTrade, curr_p: float, note: str, is_stop: bool) -> bool:
    PionexLiveExecutor.cancel_all_orders(trade.symbol)
    time.sleep(0.5)
    sell_res = PionexLiveExecutor.place_market_sell(trade.symbol, trade.amount)
    if not sell_res:
        bot.add_log(f"⚠️ Error al vender a mercado {trade.symbol}. Reintentando...", "trade")
        return False
    oid = sell_res.get("orderId")
    fill = wait_for_fill(trade.symbol, str(oid)) if oid else None
    close_trade(bot, trade, fill, curr_p, note, is_stop=is_stop)
    return True


def manage_active_trade(bot: ScalperBot, now_ts: float):
    trade = bot.active_trade
    pio_sym = trade.symbol
    ccxt_sym = pio_sym.replace("_", "/")

    try:
        curr_p = float(exchange.fetch_ticker(ccxt_sym).get("last", 0.0) or 0.0)
    except Exception:
        time.sleep(1.5)
        return
    if curr_p <= 0:
        return

    # La venta Target se considera cobrada solo si Pionex la reporta cerrada con fills (no por ausencia en la lista).
    if trade.target_order_id:
        order = PionexLiveExecutor.get_order(pio_sym, trade.target_order_id)
        fill = PionexLiveExecutor.summarize_fill(order)
        if fill and fill["status"] == "CLOSED":
            close_trade(bot, trade, fill, trade.target_price, "🎯 TARGET COBRADO en Pionex")
            time.sleep(5)
            return
    else:
        # El Target nunca se colocó: reintentar para no quedar sin salida de ganancia.
        oid = PionexLiveExecutor.place_limit_sell(pio_sym, trade.target_price, trade.amount)
        if oid:
            trade.target_order_id = oid
            bot.add_log(f"🎯 Target recolocado #{oid} @ ${trade.target_price:.4f}", "trade")
            bot.save_state()

    if curr_p <= trade.stop_price:
        bot.add_log(f"🛑 STOP DEFENSIVO {pio_sym} @ ${curr_p:.4f}", "trade")
        if market_exit(bot, trade, curr_p, "🛑 STOP DEFENSIVO", is_stop=True):
            time.sleep(5)
        return

    held = now_ts - trade.entry_time
    gain = (curr_p - trade.entry_price) / trade.entry_price
    if held >= FAST_FORCE_EXIT_SECS:
        if market_exit(bot, trade, curr_p, "⏱️ Salida forzada por tiempo", is_stop=gain < 0):
            time.sleep(2)
        return
    if held >= MAX_HOLD_TIME_SECS and gain >= FAST_MIN_PROFIT_EXIT:
        if market_exit(bot, trade, curr_p, "⏱️ Salida por tiempo (stall exit)", is_stop=False):
            time.sleep(2)
        return

    pct = (curr_p - trade.entry_price) / trade.entry_price * 100.0
    bot.status_msg = (f"En Trade {pio_sym} @ ${trade.entry_price:.4f} | Actual: ${curr_p:.4f} ({pct:+.2f}%) | "
                      f"Target: ${trade.target_price:.4f} | Stop: ${trade.stop_price:.4f}")
    time.sleep(1.5)


def manage_pending_order(bot: ScalperBot, now_ts: float, rules: Dict):
    po = bot.pending_order
    open_orders = PionexLiveExecutor.get_open_orders(po.symbol)
    if open_orders is None:
        time.sleep(3.0)  # Consulta fallida: no asumir que la orden desapareció
        return
    is_still_open = any(str(o.get("orderId")) == str(po.order_id) for o in open_orders)

    if not is_still_open:
        buy = PionexLiveExecutor.summarize_fill(PionexLiveExecutor.get_order(po.symbol, po.order_id))
        if buy:
            entry_p = buy["price"]
            amount_held = max(0.0, buy["size"] - buy["base_fee"])
            q_prec = rules.get(po.symbol, {}).get("quotePrecision", 4)
            bot.add_log(f"🟢 ORDEN MAKER EJECUTADA {buy['size']:.4f} {po.symbol} @ ${entry_p:.4f} (${buy['amount']:.2f} USDT)", "trade")

            tgt_pct = getattr(po, "target_pct", None) or TARGET_PROFIT_PCT
            stp_pct = getattr(po, "stop_pct", None) or STOP_LOSS_PCT
            target_p = round(entry_p * (1.0 + tgt_pct), q_prec)
            target_order_id = PionexLiveExecutor.place_limit_sell(po.symbol, target_p, amount_held)
            bot.add_log(f"🎯 Venta Target #{target_order_id} @ ${target_p:.4f} (+{tgt_pct*100:.2f}% ATR dinámico)", "trade")

            trade = ScalperTrade(f"pio_{po.order_id}", po.symbol, entry_p, amount_held, buy["amount"],
                                 target_order_id or "", buy["fee_usdt"],
                                 target_pct=tgt_pct, stop_pct=stp_pct, atr_val=getattr(po, "atr_pct", 0.0))
            trade.target_price = target_p
            trade.stop_price = round(entry_p * (1.0 - stp_pct), q_prec)
            bot.active_trade = trade
            bot.pending_order = None
            bot.sync_balance()
            bot.log_trade(symbol=po.symbol, side="BUY", price=entry_p, amount=buy["size"], pnl=0.0, fee=buy["fee_usdt"],
                          note=f"Maker Entry #{po.order_id} (${buy['amount']:.2f} USDT | Target ATR +{tgt_pct*100:.2f}%)", order_id=po.order_id,
                          target_order_id=target_order_id or "")
            bot.status_msg = f"Posición abierta en {po.symbol} @ ${entry_p:.4f}. Esperando Target (+{tgt_pct*100:.2f}%)."
        else:
            bot.pending_order = None
            bot.sync_balance()
            bot.status_msg = "Orden cancelada sin fills. Escaneando nuevo candidato."
        bot.save_state()
        return

    if now_ts >= po.expires_at:
        bot.add_log(f"⏱️ Orden #{po.order_id} ({po.symbol}) expiró sin retroceso. Cancelando.", "info")
        PionexLiveExecutor.cancel_all_orders(po.symbol)
        time.sleep(1.0)  # Re-evaluar en el siguiente ciclo por si se llenó (parcial) durante la cancelación
        po.expires_at = now_ts + 30
        return

    time.sleep(3.0)


def try_entry(bot: ScalperBot, rules: Dict, now_ts: float):
    with bot.data_lock:
        telemetry = list(bot.radar_telemetry)
    if not telemetry:
        return

    ready = [c for c in telemetry if c.get("trigger_ready") and bot.cooldowns.get(c["pio_symbol"], 0.0) <= now_ts]
    if not ready:
        bot.consecutive_triggers.clear()
        top = telemetry[0]
        bot.status_msg = f"Radar activo: Líder {top['name']} (Score {top['score']:.1f}/100 | OBI {top['obi']:+.2f}). Esperando gatillo."
        return

    if FAST_MODE:
        # El spread nativo de Pionex puede ser mayor que el de Binance: elegir el primer candidato barato de cruzar.
        cheap = []
        for c in ready[:5]:
            d = PionexLiveExecutor.get_market_depth(c["pio_symbol"], limit=5)
            try:
                b0, a0 = float(d["bids"][0][0]), float(d["asks"][0][0])
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            if (a0 - b0) / a0 * 100.0 <= FAST_MAX_SPREAD_PCT:
                cheap.append(c)
        if not cheap:
            bot.status_msg = f"Señal en {ready[0]['name']} pero spread Pionex > {FAST_MAX_SPREAD_PCT}%; esperando."
            return
        ready = cheap

    top = ready[0]
    pio_sym = top["pio_symbol"]

    # Anti-spoofing: persistencia en barridos distintos del radar (no en iteraciones del bucle)
    if bot.scan_cycle == bot.last_counted_cycle:
        return
    bot.last_counted_cycle = bot.scan_cycle
    bot.consecutive_triggers[pio_sym] = bot.consecutive_triggers.get(pio_sym, 0) + 1
    for s in list(bot.consecutive_triggers.keys()):
        if s != pio_sym:
            bot.consecutive_triggers[s] = 0
    if bot.consecutive_triggers[pio_sym] < FAST_TRIGGERS_REQUIRED:
        bot.status_msg = f"Validando persistencia de flujo en {pio_sym} ({bot.consecutive_triggers[pio_sym]}/{FAST_TRIGGERS_REQUIRED} barridos)..."
        return

    pio_depth = PionexLiveExecutor.get_market_depth(pio_sym, limit=5)
    p_bid_pct = 50.0
    entry_limit = top["entry_limit"]
    if pio_depth and pio_depth.get("bids") and pio_depth.get("asks"):
        p_bids_vol = sum(float(b[1]) for b in pio_depth["bids"])
        p_asks_vol = sum(float(a[1]) for a in pio_depth["asks"])
        p_tot = p_bids_vol + p_asks_vol
        p_bid_pct = (p_bids_vol / p_tot * 100.0) if p_tot > 0 else 50.0
        if p_bid_pct < (50.0 if FAST_MODE else 52.0):
            bot.add_log(f"🛑 RECHAZO NATIVO PIONEX: {pio_sym} con vendedores dominando ({100 - p_bid_pct:.1f}% Asks). Abortando.", "trade")
            bot.consecutive_triggers[pio_sym] = 0
            return
        best_bid_p, best_ask_p = float(pio_depth["bids"][0][0]), float(pio_depth["asks"][0][0])
        if FAST_MODE:
            if (best_ask_p - best_bid_p) / best_ask_p * 100.0 > FAST_MAX_SPREAD_PCT:
                bot.status_msg = f"Spread Pionex amplio en {pio_sym}; esperando."
                return
            entry_limit = best_ask_p  # fill inmediato
        else:
            entry_limit = min(entry_limit, best_bid_p)

    sym_rules = rules.get(pio_sym, {"basePrecision": 2, "quotePrecision": 4, "minAmount": 10.0, "minTradeSize": 0.01})
    bot.sync_balance()
    trade_capital = min(bot.cash * 0.86, 60.00)
    if trade_capital < sym_rules["minAmount"] or entry_limit <= 0:
        bot.status_msg = f"Saldo insuficiente (${bot.cash:.2f}) para el mínimo de {pio_sym}."
        return

    size = math.floor(trade_capital / entry_limit * 10 ** sym_rules["basePrecision"]) / 10 ** sym_rules["basePrecision"]
    if size < sym_rules.get("minTradeSize", 0.0):
        return

    bot.add_log(f"⚡ DISPARO: {pio_sym} Score {top['score']:.1f} | OBI {top['obi']:+.2f} | Rango15m {top.get('range_pct', 0):.2f}% | Libro {p_bid_pct:.1f}% Compras", "trade")
    order_id = PionexLiveExecutor.place_limit_buy(pio_sym, entry_limit, size)
    if order_id:
        dyn_tgt = top.get("dyn_target_pct", TARGET_PROFIT_PCT)
        dyn_stp = top.get("dyn_stop_pct", STOP_LOSS_PCT)
        atr_p = top.get("atr_pct", 0.60)
        bot.pending_order = ScalperPendingOrder(
            order_id=order_id, symbol=pio_sym, limit_price=entry_limit, size=size, capital=trade_capital,
            reason=f"OBI={top['obi']:+.2f} | RSI={top['rsi']:.1f} | ATR={atr_p:.2f}% (Tgt +{dyn_tgt*100:.2f}%)",
            target_pct=dyn_tgt, stop_pct=dyn_stp, atr_pct=atr_p
        )
        bot.consecutive_triggers.clear()
        bot.sync_balance()
        bot.add_log(f"✅ Compra colocada #{order_id} ({size} {pio_sym} por ~${trade_capital:.2f})", "trade")
        bot.status_msg = f"Orden Maker #{order_id} en {pio_sym} @ ${entry_limit:.4f} (Score {top['score']:.1f})"
        bot.save_state()


def run_dollar_scalper():
    bot = ScalperBot()
    start_scalper_dashboard(bot, SCALPER_HTTP_PORT)

    telemetry_thread = threading.Thread(target=telemetry_background_thread, args=(bot,), daemon=True)
    telemetry_thread.start()

    rules = PionexLiveExecutor.get_symbol_rules()
    print("=" * 80, flush=True)
    print("  THE 1-DOLLAR SCALPER - PIONEX SPOT", flush=True)
    print(f"  • Modo                           -> {'SOLO LECTURA (sin órdenes)' if DASHBOARD_ONLY else 'CUENTA REAL SPOT VIVA'}", flush=True)
    print("  • Persistencia Transaccional     -> SQLite WAL (scalper_vault.db)", flush=True)
    print(f"  • Saldo Pionex Detectado         -> ${bot.cash:.2f} USDT (Libre: ${bot.cash:.2f} | Frozen: ${bot.frozen:.2f})", flush=True)
    print(f"  • Objetivo por Disparo           -> +{TARGET_PROFIT_PCT*100:.2f}%", flush=True)
    print(f"  • Stop Defensivo                 -> -{STOP_LOSS_PCT*100:.2f}%", flush=True)
    print(f"  • Dashboard en Vivo              -> http://localhost:{SCALPER_HTTP_PORT}", flush=True)
    print("=" * 80, flush=True)

    cycle = 0
    while True:
        try:
            cycle += 1
            now_ts = time.time()

            if DASHBOARD_ONLY:
                bot.status_msg = "MODO SOLO LECTURA: radar y dashboard activos, sin enviar órdenes."
                if cycle % 10 == 1:
                    bot.sync_balance()
                bot.save_state()
                time.sleep(3.0)
                continue

            if bot.active_trade:
                manage_active_trade(bot, now_ts)
            elif bot.pending_order:
                manage_pending_order(bot, now_ts, rules)
            else:
                try_entry(bot, rules, now_ts)
                time.sleep(2.0)

            if cycle % 20 == 0 and not bot.active_trade:
                bot.sync_balance()
            bot.maybe_log_equity()
            bot.save_state()

        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"  [Error Bucle Scalper] {e}", flush=True)
            bot.add_log(f"⚠️ Error en bucle: {e}", "info")
            time.sleep(3.0)


if __name__ == "__main__":
    run_dollar_scalper()
