"""
Contenedor del estado operativo del bot Swing Sniper & Bounded Grid.
Coordina balances, posiciones activas, límites de riesgo y persistencia en SQLite.
"""
import time
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any

from config import (
    SWING_DB_FILE,
    PAPER_INITIAL_CAPITAL,
    DEFAULT_SETTINGS,
    CASH_ALLOCATION_PCT
)
from database import SwingDatabase
from engine.bot_models import SwingTrade, BoundedMicroGrid


class SwingBot:
    """Contenedor de estado, telemetría y ejecución del bot."""
    def __init__(self, db_path: Optional[str] = None):
        self.db = SwingDatabase(db_path or SWING_DB_FILE)
        self.cash = PAPER_INITIAL_CAPITAL
        self.active_trades: Dict[str, SwingTrade] = {}
        self.active_grid: Optional[BoundedMicroGrid] = None
        self.active_mode: str = "SWING_SNIPER"
        self.radar_telemetry: List[Dict[str, Any]] = []
        self.real_grid_stats: Dict[str, Any] = {}
        self.cooldowns: Dict[str, float] = {}
        self.last_stop_time: float = 0.0
        self.global_cooldown_until: float = 0.0
        self.settings: Dict[str, Any] = dict(DEFAULT_SETTINGS)
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
                self.db.save_all_settings(self.settings)
        except Exception as e:
            self.add_log(f"Error cargando settings desde SQLite: {e}", "error")

    def save_settings(self):
        try:
            self.db.save_all_settings(self.settings)
        except Exception as e:
            self.add_log(f"Error guardando settings en SQLite: {e}", "error")

    def update_settings(self, new_cfg: Dict[str, Any]):
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
        be_pct = self.settings.get("be_trigger_pct", 0.016) * 100.0
        mode_str = "AUTO ATR" if self.settings.get("auto_atr_mode") else "MANUAL"
        self.add_log(
            f"⚙️ Parámetros actualizados en SQLite [{mode_str}]: BE=+{be_pct:.2f}% | "
            f"Stop={self.settings.get('stop_atr_mult', 1.2)}x ATR | "
            f"Target={self.settings.get('target_atr_mult', 3.0)}x ATR | "
            f"Trail={self.settings.get('trail_distance_atr', 1.5)}x ATR | "
            f"Score={self.settings.get('min_score', 70.0):.0f}",
            "info"
        )

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
            return 3
        elif eq >= 120.0:
            return 2
        return 1

    def get_tier_name(self) -> str:
        eq = self.total_equity()
        if eq >= 200.0:
            return "Multi-Sniper Diversificado (≥$200: 3 trades al unísono)"
        elif eq >= 120.0:
            return "Dual-Sniper ($120-$200: 2 trades simultáneos)"
        return "Mono-Sniper (<$120: Interés Compuesto Concentrado)"

    def calculate_trade_capital(self) -> float:
        """Calcula el tamaño del trade con interés compuesto dinámico (Modo Sniper 80%-95% capital)."""
        eq = self.total_equity()
        max_trades = self.get_max_concurrent_trades()
        alloc = self.settings.get("cash_allocation_pct", CASH_ALLOCATION_PCT)
        if max_trades == 1:
            target_cap = self.cash * alloc
        elif max_trades == 2:
            target_cap = eq * 0.45
        else:
            target_cap = eq * 0.30
        return max(0.0, min(self.cash * 0.98, target_cap))

    def add_log(self, msg: str, event_type: str = "info"):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [{event_type.upper()}] {msg}", flush=True)
        self.db.insert_event(event_type, msg)

    def load_state(self):
        try:
            d = self.db.load_bot_state()
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
            self.db.save_bot_state(d)
        except Exception as e:
            self.add_log(f"Error guardando estado en SQLite: {e}", "error")
