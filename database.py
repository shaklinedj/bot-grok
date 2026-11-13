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
        conn.execute("PRAGMA busy_timeout=5000;")
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

            # 7. Tabla de Trades de Buda Market Maker (Pilar 3)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS buda_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price REAL NOT NULL,
                    amount REAL NOT NULL,
                    total_clp REAL NOT NULL,
                    fee_clp REAL NOT NULL,
                    profit_clp REAL DEFAULT 0.0,
                    note TEXT
                );
            """)

            # 8. Tabla de Autopsias de Veto (Shadow Tracking Contrafactual)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS veto_autopsies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    veto_type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    veto_price REAL NOT NULL,
                    target_price REAL NOT NULL,
                    stop_price REAL NOT NULL,
                    target_pct REAL NOT NULL,
                    stop_pct REAL NOT NULL,
                    leverage REAL NOT NULL DEFAULT 2.0,
                    capital REAL NOT NULL,
                    max_price REAL NOT NULL,
                    min_price REAL NOT NULL,
                    final_price REAL DEFAULT 0.0,
                    mfe_pct REAL DEFAULT 0.0,
                    mae_pct REAL DEFAULT 0.0,
                    hypothetical_pnl REAL DEFAULT 0.0,
                    hypothetical_pnl_pct REAL DEFAULT 0.0,
                    outcome TEXT DEFAULT 'TRACKING',
                    learning_insight TEXT DEFAULT '',
                    duration_s REAL DEFAULT 0.0,
                    expires_at REAL NOT NULL,
                    status TEXT DEFAULT 'OPEN'
                );
            """)

            # 8. Tabla de Liquidaciones Funding Cash & Carry (Pilar 4)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cash_carry_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    rate_8h_pct REAL NOT NULL,
                    payout_usdt REAL NOT NULL,
                    new_capital REAL NOT NULL,
                    note TEXT
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

    # --- Métodos de Veto Autopsies (Shadow Tracking Contrafactual) ---
    def log_veto_candidate(self, symbol: str, veto_type: str, reason: str,
                           veto_price: float, target_price: float, stop_price: float,
                           target_pct: float, stop_pct: float, capital: float,
                           leverage: float = 2.0, horizon_seconds: float = 3600.0) -> int:
        ts = datetime.now().isoformat()
        expires_at = time.time() + horizon_seconds
        with self._get_connection() as conn:
            cur = conn.execute("""
                INSERT INTO veto_autopsies (
                    timestamp, symbol, veto_type, reason, veto_price,
                    target_price, stop_price, target_pct, stop_pct,
                    leverage, capital, max_price, min_price, expires_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
            """, (ts, symbol, veto_type, reason, veto_price,
                  target_price, stop_price, target_pct, stop_pct,
                  leverage, capital, veto_price, veto_price, expires_at))
            conn.commit()
            return cur.lastrowid

    def get_open_vetoes(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM veto_autopsies WHERE status = 'OPEN'").fetchall()
            return [dict(r) for r in rows]

    def update_veto_autopsy(self, veto_id: int, max_price: float, min_price: float,
                            final_price: float, mfe_pct: float, mae_pct: float,
                            hypothetical_pnl: float, hypothetical_pnl_pct: float,
                            outcome: str, learning_insight: str, duration_s: float,
                            status: str = "CLOSED"):
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE veto_autopsies
                SET max_price = ?, min_price = ?, final_price = ?,
                    mfe_pct = ?, mae_pct = ?, hypothetical_pnl = ?,
                    hypothetical_pnl_pct = ?, outcome = ?, learning_insight = ?,
                    duration_s = ?, status = ?
                WHERE id = ?
            """, (max_price, min_price, final_price, mfe_pct, mae_pct,
                  hypothetical_pnl, hypothetical_pnl_pct, outcome,
                  learning_insight, duration_s, status, veto_id))
            conn.commit()

    def get_recent_veto_autopsies(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM veto_autopsies ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_veto_summary_stats(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM veto_autopsies WHERE status = 'CLOSED'").fetchone()[0]
            saved = conn.execute("SELECT COUNT(*) FROM veto_autopsies WHERE status = 'CLOSED' AND outcome IN ('SAVED_LOSS_STOP', 'SAVED_LOSS_TIME')").fetchone()[0]
            missed = conn.execute("SELECT COUNT(*) FROM veto_autopsies WHERE status = 'CLOSED' AND outcome = 'MISSED_WIN'").fetchone()[0]
            capital_saved = conn.execute("""
                SELECT COALESCE(SUM(CASE WHEN hypothetical_pnl < 0 THEN -hypothetical_pnl ELSE 0 END), 0.0)
                FROM veto_autopsies WHERE status = 'CLOSED'
            """).fetchone()[0]
            capital_missed = conn.execute("""
                SELECT COALESCE(SUM(CASE WHEN hypothetical_pnl > 0 THEN hypothetical_pnl ELSE 0 END), 0.0)
                FROM veto_autopsies WHERE status = 'CLOSED'
            """).fetchone()[0]
            return {
                "total_vetoes_analyzed": total,
                "saved_losses": saved,
                "missed_wins": missed,
                "accuracy_pct": round((saved / total * 100.0), 1) if total > 0 else 100.0,
                "capital_saved_usdt": round(capital_saved, 2),
                "capital_missed_usdt": round(capital_missed, 2)
            }

    # --- Métodos de Persistencia SQLite para Buda Market Maker (Pilar 3) ---
    def save_buda_state(self, state: Dict[str, Any]):
        """Persiste el estado operativo de Buda MM en SQLite de forma atómica y segura."""
        ts = datetime.now().isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO bot_state (key, val_json, updated_at)
                VALUES ('buda_state', ?, ?)
                ON CONFLICT(key) DO UPDATE SET val_json=excluded.val_json, updated_at=excluded.updated_at
            """, (json.dumps(state), ts))
            conn.commit()

    def load_buda_state(self) -> Optional[Dict[str, Any]]:
        """Recupera el estado de Buda MM directamente desde SQLite."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT val_json FROM bot_state WHERE key = 'buda_state'").fetchone()
            if row and row["val_json"]:
                try:
                    return json.loads(row["val_json"])
                except Exception:
                    pass
        return None

    def log_buda_trade(self, side: str, price: float, amount: float, total_clp: float, fee_clp: float, profit_clp: float = 0.0, note: str = ""):
        """Registra un fill del market maker de Buda en SQLite."""
        ts = datetime.now().isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO buda_trades (timestamp, side, price, amount, total_clp, fee_clp, profit_clp, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (ts, side, price, amount, total_clp, fee_clp, profit_clp, note))
            conn.commit()

    def get_buda_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM buda_trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    # --- Métodos de Persistencia SQLite para Binance Cash & Carry (Pilar 4) ---
    def save_cash_carry_state(self, state: Dict[str, Any]):
        """Persiste el estado operativo de Cash & Carry en SQLite de forma atómica y segura."""
        ts = datetime.now().isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO bot_state (key, val_json, updated_at)
                VALUES ('cash_carry_state', ?, ?)
                ON CONFLICT(key) DO UPDATE SET val_json=excluded.val_json, updated_at=excluded.updated_at
            """, (json.dumps(state), ts))
            conn.commit()

    def load_cash_carry_state(self) -> Optional[Dict[str, Any]]:
        """Recupera el estado de Cash & Carry directamente desde SQLite."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT val_json FROM bot_state WHERE key = 'cash_carry_state'").fetchone()
            if row and row["val_json"]:
                try:
                    return json.loads(row["val_json"])
                except Exception:
                    pass
        return None

    def log_cash_carry_payout(self, pair: str, rate_8h_pct: float, payout_usdt: float, new_capital: float, note: str = ""):
        """Registra una liquidación de funding rate 8h de Binance en SQLite."""
        ts = datetime.now().isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO cash_carry_history (timestamp, pair, rate_8h_pct, payout_usdt, new_capital, note)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (ts, pair, rate_8h_pct, payout_usdt, new_capital, note))
            conn.commit()

    def get_cash_carry_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM cash_carry_history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
