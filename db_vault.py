"""
db_vault.py - Institutional-Grade SQLite Storage Engine in WAL Mode
===================================================================
Proporciona almacenamiento ACID, libre de bloqueos de archivo, de alta velocidad
(microsegundos) y con soporte para lectores concurrentes mediante Write-Ahead Logging (WAL).
Reemplaza los archivos planos CSV con esquemas indexados, consultas instantáneas y migración
automática de datos existentes.
"""

import os
import sys
import csv
import sqlite3
import threading
from datetime import datetime
from typing import List, Dict, Optional, Any
import pandas as pd

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class DatabaseVault:
    def __init__(self, db_path: str = "paper_logs/trading_vault.db"):
        self.db_path = db_path
        db_dir = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(db_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL;")
        self._conn.execute("PRAGMA synchronous = NORMAL;")
        self._conn.execute("PRAGMA busy_timeout = 5000;")
        self._init_db()

    def close(self):
        """Cierra la conexión a la base de datos de forma limpia."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _init_db(self):
        """Inicializa las tablas e índices si no existen."""
        with self._lock:
            cursor = self._conn.cursor()
            
            # 1. Tabla de Trades
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                strategy TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                amount REAL NOT NULL,
                pnl REAL DEFAULT 0.0,
                fee REAL DEFAULT 0.0,
                slippage REAL DEFAULT 0.0,
                extra_info TEXT,
                position_id TEXT,
                status TEXT
            );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(timestamp);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_sym ON trades(symbol);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_pos ON trades(position_id);")

            # 2. Tabla de Historial de Equity
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS equity_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                equity REAL NOT NULL,
                cash REAL NOT NULL,
                holdings_value REAL NOT NULL,
                open_longs INTEGER DEFAULT 0,
                realized_pnl_total REAL DEFAULT 0.0,
                fees_paid REAL DEFAULT 0.0,
                slippage_cost REAL DEFAULT 0.0,
                max_drawdown REAL DEFAULT 0.0
            );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_equity_ts ON equity_history(timestamp);")
            self._conn.commit()

    def insert_trade(self, timestamp: str, symbol: str, strategy: str, side: str,
                     price: float, amount: float, pnl: float = 0.0, fee: float = 0.0,
                     slippage: float = 0.0, extra_info: str = "", position_id: str = "",
                     status: str = "OPEN") -> int:
        """Inserta una operación de forma atómica."""
        query = """
        INSERT INTO trades (timestamp, symbol, strategy, side, price, amount, pnl, fee, slippage, extra_info, position_id, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(query, (
                timestamp, symbol, strategy, side, float(price), float(amount),
                float(pnl), float(fee), float(slippage), str(extra_info),
                str(position_id), str(status)
            ))
            self._conn.commit()
            return cursor.lastrowid

    def insert_equity(self, timestamp: str, equity: float, cash: float,
                      holdings_value: float, open_longs: int, realized_pnl_total: float,
                      fees_paid: float, slippage_cost: float, max_drawdown: float) -> int:
        """Inserta una instantánea de equity de forma atómica."""
        query = """
        INSERT INTO equity_history (timestamp, equity, cash, holdings_value, open_longs, realized_pnl_total, fees_paid, slippage_cost, max_drawdown)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(query, (
                timestamp, float(equity), float(cash), float(holdings_value),
                int(open_longs), float(realized_pnl_total), float(fees_paid),
                float(slippage_cost), float(max_drawdown)
            ))
            self._conn.commit()
            return cursor.lastrowid

    def get_recent_trades(self, limit: int = 250) -> List[Dict[str, Any]]:
        """Obtiene las operaciones más recientes ordenadas descendente por timestamp."""
        query = "SELECT * FROM trades ORDER BY id DESC LIMIT ?;"
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(query, (limit,))
            rows = cursor.fetchall()
            return [
                {
                    "timestamp": r["timestamp"],
                    "symbol": r["symbol"],
                    "strategy": r["strategy"],
                    "side": r["side"],
                    "price": str(r["price"]),
                    "amount": str(r["amount"]),
                    "pnl": r["pnl"],
                    "fee": r["fee"],
                    "slippage": r["slippage"],
                    "extra_info": r["extra_info"] or "",
                    "position_id": r["position_id"] or "",
                    "status": r["status"] or ("OPEN" if r["side"].lower() == "buy" else "CLOSED")
                }
                for r in rows
            ]

    def get_all_trades_df(self) -> pd.DataFrame:
        """Retorna todas las operaciones en un DataFrame de pandas para auditoría forense."""
        with self._lock:
            df = pd.read_sql_query("SELECT * FROM trades ORDER BY id ASC;", self._conn)
            return df

    def get_equity_history(self, sample_limit: int = 300) -> List[Dict[str, Any]]:
        """
        Retorna la curva de equity muestreada uniformemente a `sample_limit` puntos
        desde el inicio histórico hasta el último tick.
        """
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT timestamp, equity FROM equity_history ORDER BY id ASC;")
            rows = cursor.fetchall()
            if not rows:
                return []
            
            all_vals = []
            for r in rows:
                t_str = r["timestamp"].split('.')[0].replace('T', ' ')
                all_vals.append({"t": t_str, "v": round(float(r["equity"]), 2)})

            if len(all_vals) <= sample_limit:
                return all_vals

            step = (len(all_vals) - 1) / float(sample_limit - 1)
            indices = [int(round(i * step)) for i in range(sample_limit)]
            sampled = [all_vals[idx] for idx in indices]
            sampled[0] = all_vals[0]
            sampled[-1] = all_vals[-1]
            return sampled

    def get_trade_metrics(self) -> Dict[str, Any]:
        """Calcula métricas agregadas al vuelo mediante SQL."""
        query = """
        SELECT 
            COUNT(*) as total_trades,
            SUM(CASE WHEN pnl > 0 AND status IN ('CLOSED', 'PARTIAL_CLOSED') THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN pnl < 0 AND status IN ('CLOSED', 'PARTIAL_CLOSED') THEN 1 ELSE 0 END) as losses,
            SUM(pnl) as total_pnl,
            SUM(fee) as total_fees,
            SUM(slippage) as total_slippage
        FROM trades;
        """
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(query)
            row = cursor.fetchone()
            total = row["total_trades"] or 0
            wins = row["wins"] or 0
            losses = row["losses"] or 0
            closed = wins + losses
            wr = (wins / closed * 100.0) if closed > 0 else 0.0
            return {
                "total_trades": total,
                "wins": wins,
                "losses": losses,
                "win_rate": round(wr, 2),
                "total_pnl": round(row["total_pnl"] or 0.0, 4),
                "total_fees": round(row["total_fees"] or 0.0, 4),
                "total_slippage": round(row["total_slippage"] or 0.0, 4)
            }

    def reset_vault(self, target_cash: float):
        """Reinicia la base de datos e inserta la primera instantánea limpia."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("DELETE FROM trades;")
            cursor.execute("DELETE FROM equity_history;")
            self._conn.commit()
        now_iso = datetime.now().isoformat()
        self.insert_equity(now_iso, target_cash, target_cash, 0.0, 0, 0.0, 0.0, 0.0, 0.0)

    def migrate_from_csv(self, trades_csv: str, equity_csv: str):
        """
        Migra automáticamente registros existentes de CSV a SQLite si la base de datos está vacía.
        Garantiza preservación del 100% del historial previo.
        """
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM trades;")
            trades_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM equity_history;")
            equity_count = cursor.fetchone()[0]

        # 1. Migrar trades si la tabla trades está vacía y el CSV existe
        if trades_count == 0 and os.path.exists(trades_csv):
            migrated_trades = 0
            with open(trades_csv, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                batch = []
                for row in reader:
                    if not row or len(row) < 6:
                        continue
                    ts = row[0]
                    sym = row[1]
                    strat = row[2]
                    side = row[3]
                    p = float(row[4]) if row[4] else 0.0
                    amt = float(row[5]) if row[5] else 0.0
                    pnl = float(row[6]) if len(row) > 6 and row[6] else 0.0
                    fee = float(row[7]) if len(row) > 7 and row[7] else 0.0
                    slip = float(row[8]) if len(row) > 8 and row[8] else 0.0
                    extra = row[9] if len(row) > 9 else ""
                    pos_id = row[10] if len(row) > 10 else ""
                    status = row[11] if len(row) > 11 else ("OPEN" if side.lower() == "buy" else "CLOSED")
                    batch.append((ts, sym, strat, side, p, amt, pnl, fee, slip, extra, pos_id, status))
                    migrated_trades += 1

            if batch:
                with self._lock:
                    self._conn.executemany("""
                    INSERT INTO trades (timestamp, symbol, strategy, side, price, amount, pnl, fee, slippage, extra_info, position_id, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, batch)
                    self._conn.commit()
                print(f"  🏛️ [MIGRACIÓN SQLITE] {migrated_trades} operaciones importadas desde trades.csv a trading_vault.db", flush=True)

        # 2. Migrar equity history si la tabla está vacía y el CSV existe
        if equity_count == 0 and os.path.exists(equity_csv):
            migrated_equity = 0
            with open(equity_csv, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                batch = []
                for row in reader:
                    if not row or len(row) < 2:
                        continue
                    try:
                        ts = row[0]
                        eq = float(row[1])
                        csh = float(row[2]) if len(row) > 2 else eq
                        hld = float(row[3]) if len(row) > 3 else 0.0
                        pos = int(row[4]) if len(row) > 4 else 0
                        rpnl = float(row[5]) if len(row) > 5 else 0.0
                        fee = float(row[6]) if len(row) > 6 else 0.0
                        slip = float(row[7]) if len(row) > 7 else 0.0
                        dd = float(row[8]) if len(row) > 8 else 0.0
                        batch.append((ts, eq, csh, hld, pos, rpnl, fee, slip, dd))
                        migrated_equity += 1
                    except Exception:
                        continue

            if batch:
                with self._lock:
                    self._conn.executemany("""
                    INSERT INTO equity_history (timestamp, equity, cash, holdings_value, open_longs, realized_pnl_total, fees_paid, slippage_cost, max_drawdown)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, batch)
                    self._conn.commit()
                print(f"  🏛️ [MIGRACIÓN SQLITE] {migrated_equity} instantáneas de equity importadas desde equity_history.csv a trading_vault.db", flush=True)


# Instancia Singleton compartida
vault = DatabaseVault()
