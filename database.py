"""
Capa de persistencia SQLite WAL de alta fiabilidad para Swing Sniper & Grid Desk.
Gestiona el libro mayor de trades con parent_trade_id determinístico, autopsias post-mortem,
configuración de faders, historial de patrimonio y registro de eventos.
"""
import sqlite3
import datetime
from datetime import datetime
import json
import os
from typing import Dict, Any, List, Optional
from config import SWING_DB_FILE, DEFAULT_SETTINGS


class SwingDatabase:
    """Base de datos relacional SQLite con WAL mode para consistencia transaccional."""
    def __init__(self, db_path: str = SWING_DB_FILE):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            # 1. Tabla de Trades (con parent_trade_id para emparejamiento estricto)
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
                    parent_trade_id TEXT,
                    target_price REAL,
                    stop_price REAL,
                    note TEXT,
                    mode TEXT DEFAULT 'PAPER_SWING'
                );
            """)

            # Migración automática si la columna parent_trade_id no existía
            try:
                cols = [r["name"] for r in conn.execute("PRAGMA table_info(trades);").fetchall()]
                if "parent_trade_id" not in cols:
                    conn.execute("ALTER TABLE trades ADD COLUMN parent_trade_id TEXT;")
            except Exception:
                pass

            # 2. Tabla de Eventos
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL
                );
            """)

            # 3. Tabla de Historial de Patrimonio (Equity Curve)
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

            # 4. Tabla de Configuración y Faders
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key TEXT PRIMARY KEY,
                    val_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

            # 5. Tabla de Estado Operativo
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    val_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

            # 6. Tabla de Autopsias Cuantitativas Post-Trade
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
                  pnl: float = 0.0, fee: Any = 0.0, order_id: str = "",
                  target_price: float = 0.0, stop_price: float = 0.0, note: str = "",
                  mode: str = "PAPER_SWING", parent_trade_id: Optional[str] = None):
        """Registra una operación en el libro mayor con trazabilidad a la orden padre."""
        ts = datetime.now().isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO trades (timestamp, symbol, side, price, amount, capital, pnl, fee, order_id, parent_trade_id, target_price, stop_price, note, mode)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (ts, symbol, side, price, amount, capital, pnl, fee, order_id, parent_trade_id, target_price, stop_price, note, mode))
            conn.commit()

    def insert_event(self, event_type: str, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        with self._get_connection() as conn:
            conn.execute("INSERT INTO events (timestamp, event_type, message) VALUES (?, ?, ?)",
                         (ts, event_type, message))
            conn.commit()

    def log_event(self, event_type: str, message: str):
        self.insert_event(event_type, message)

    def insert_equity(self, cash: float, equity: float, realized_pnl: float, win_rate: float, total_trades: int):
        ts = datetime.now().isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO equity_history (timestamp, cash, equity, realized_pnl, win_rate, total_trades)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (ts, cash, equity, realized_pnl, win_rate, total_trades))
            conn.commit()

    def get_stats(self) -> Dict[str, Any]:
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
            return {
                "total": tot,
                "total_trades": tot,
                "pnl": pnl,
                "total_pnl": pnl,
                "wins": wins,
                "losses": int(row["losses"]),
                "win_rate": wr
            }

    def get_trade_count(self) -> int:
        with self._get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM trades WHERE side='SELL'").fetchone()
            return int(row[0]) if row else 0

    def get_recent_trades(self, limit: int = 25) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_full_history(self) -> Dict[str, Any]:
        """Recupera el historial completo de operaciones y la curva de patrimonio acumulada."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM trades ORDER BY id DESC").fetchall()
            all_trades = [dict(r) for r in rows]

            asc_rows = conn.execute("SELECT * FROM trades ORDER BY id ASC").fetchall()
            eq = 70.0
            curve = [{"idx": 0, "time": "Inicio", "equity": 70.0, "pnl": 0.0, "symbol": "CASH", "side": "INIT", "note": "Capital Inicial"}]
            for r in asc_rows:
                pnl = float(r["pnl"] or 0.0)
                if pnl != 0.0:
                    eq += pnl
                    ts = r["timestamp"]
                    ts_short = ts[5:16].replace("T", " ") if ts else ""
                    curve.append({
                        "id": r["id"],
                        "time": ts_short,
                        "equity": round(eq, 2),
                        "pnl": round(pnl, 4),
                        "symbol": r["symbol"],
                        "side": r["side"],
                        "mode": r["mode"] or "PAPER_SWING",
                        "note": r["note"] or ""
                    })
            return {
                "trades": all_trades,
                "equity_curve": curve,
                "stats": self.get_stats()
            }

    def get_last_closed_trade(self) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM trades WHERE side='SELL' ORDER BY id DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    def get_recent_events(self, limit: int = 40) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT timestamp as time, event_type as type, message as text FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

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

    def save_settings(self, settings: Dict[str, Any]):
        self.save_all_settings(settings)

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

    def load_settings(self) -> Dict[str, Any]:
        return self.get_all_settings()

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

    def get_recent_autopsies(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Recupera las autopsias clínicas más recientes de SQLite."""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT timestamp, trade_id, symbol, pnl, pnl_pct, duration_s,
                       mfe_pct, mae_pct, exit_reason, classification, btc_regime,
                       lesson_learned, adaptive_action
                FROM trade_autopsies
                ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]
