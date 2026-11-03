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
from risk.dynamic_sizing import scale_capital_by_volatility


class SwingBot:
    """Contenedor de estado, telemetría y ejecución del bot."""
    def __init__(self, db_path: Optional[str] = None):
        self.db = SwingDatabase(db_path or SWING_DB_FILE)
        self.cash = PAPER_INITIAL_CAPITAL
        self.active_trades: Dict[str, SwingTrade] = {}
        self._active_grids: Dict[str, BoundedMicroGrid] = {}
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

    @property
    def active_grid(self) -> Optional[BoundedMicroGrid]:
        """Propiedad retrocompatible: primer micro-malla activa o None."""
        if not hasattr(self, "_active_grids"):
            self._active_grids = {}
        if self._active_grids:
            return next(iter(self._active_grids.values()))
        return None

    @active_grid.setter
    def active_grid(self, val: Optional[BoundedMicroGrid]):
        if not hasattr(self, "_active_grids"):
            self._active_grids = {}
        if val is None:
            self._active_grids.clear()
        else:
            self._active_grids[val.grid_id] = val

    def get_active_grids(self) -> List[BoundedMicroGrid]:
        """Devuelve la lista de todas las mallas activas en paralelo."""
        if not hasattr(self, "_active_grids"):
            self._active_grids = {}
        return list(self._active_grids.values())

    def add_active_grid(self, grid: BoundedMicroGrid):
        if not hasattr(self, "_active_grids"):
            self._active_grids = {}
        self._active_grids[grid.grid_id] = grid

    def remove_active_grid(self, grid_id: str):
        if hasattr(self, "_active_grids") and grid_id in self._active_grids:
            del self._active_grids[grid_id]

    def total_equity(self) -> float:
        """Calcula el patrimonio total en vivo: Caja disponible + Posiciones Swing + Mallas Acotadas."""
        pos_val = sum(tr.amount * getattr(tr, "current_price", tr.entry_price) for tr in self.active_trades.values())
        grid_val = sum(g.get_invested_capital() + g.unrealized_pnl for g in self.get_active_grids())
        return self.cash + pos_val + grid_val

    def get_max_concurrent_trades(self) -> int:
        """Escalabilidad de diversificación multi-trade según nivel de capital."""
        eq = self.total_equity()
        if eq >= 500.0:
            return 4
        elif eq >= 200.0:
            return 3
        elif eq >= 120.0:
            return 2
        return 1

    def get_tier_name(self) -> str:
        eq = self.total_equity()
        if eq >= 500.0:
            return "Fondo Multi-Estrategia Asimétrico (≥$500: 1 Long Core $300 + 2 Mallas $100)"
        elif eq >= 200.0:
            return "Multi-Sniper Diversificado (≥$200: 3 trades al unísono)"
        elif eq >= 120.0:
            return "Dual-Sniper ($120-$200: 2 trades simultáneos)"
        return "Mono-Sniper (<$120: Interés Compuesto Concentrado)"

    def calculate_trade_capital(self, current_atr_pct: float = 2.0) -> float:
        """
        Calcula el tamaño del trade con Interés Compuesto Institucional (Grado 10).
        Modula el capital asignado (alloc) según la volatilidad de régimen (ATR).
        """
        eq = self.total_equity()
        max_trades = self.get_max_concurrent_trades()
        alloc = self.settings.get("cash_allocation_pct", CASH_ALLOCATION_PCT)

        if max_trades == 1:
            base_cap = self.cash * alloc
        elif max_trades == 2:
            base_cap = eq * 0.45
        elif max_trades == 3:
            base_cap = eq * 0.30
        else:
            # Tier 4 (≥ $500: Gran Long Core $275 - $300 USDT)
            base_cap = eq * 0.55

        # Escalado por volatilidad (Grado 10): a volatilidad base (2.0%), factor = 1.0 (56 USDT)
        scaled_cap = scale_capital_by_volatility(
            base_capital=base_cap,
            current_atr_pct=current_atr_pct,
            baseline_atr_pct=2.0,
            min_scale=0.50,
            max_scale=1.20
        )
        return max(0.0, min(self.cash * 0.98, scaled_cap))

    def get_portfolio_allocation_plan(self, btc_regime: str = "NEUTRAL_TRANSITION") -> Dict[str, Any]:
        """
        Calcula la matriz dinámica de asignación Core + Satélite Barbell según Equity y Régimen de Mercado.
        Tier 1 (< $100): Mono-Sniper (100% concentrado en 1 trade o 1 malla).
        Tier 2 ($100-$250): Core-Satélite Dual (1 Long Core 60% + 1 Malla Satélite 35%).
        Tier 3 ($250-$500): Tridente Adaptativo (2 Longs + 1 Malla en Bullish, o 1 Long + 2 Mallas en Chop).
        Tier 4 (≥ $500): Fondo Multi-Estrategia Asimétrico (1 Gran Long $300 + 2 Mallas $100 c/u + Caja).
        """
        eq = self.total_equity()
        if eq < 100.0:
            if btc_regime == "CHOP_COMPRESSION":
                return {
                    "tier": 1,
                    "name": "Mono-Sniper (Chop)",
                    "max_swings": 0,
                    "max_grids": 1,
                    "swing_cap": 0.0,
                    "grid_cap": min(self.cash * 0.85, 75.0)
                }
            else:
                return {
                    "tier": 1,
                    "name": "Mono-Sniper (Trend)",
                    "max_swings": 1,
                    "max_grids": 0,
                    "swing_cap": self.calculate_trade_capital(),
                    "grid_cap": 0.0
                }
        elif eq < 250.0:
            core_swing_cap = eq * 0.60
            satellite_grid_cap = eq * 0.35
            return {
                "tier": 2,
                "name": "Core-Satélite Dual ($100-$250)",
                "max_swings": 1,
                "max_grids": 1,
                "swing_cap": min(self.cash * 0.95, core_swing_cap),
                "grid_cap": min(self.cash * 0.95, satellite_grid_cap)
            }
        elif eq < 500.0:
            if btc_regime in ("BULLISH_EXPANSION", "NEUTRAL_TRANSITION"):
                return {
                    "tier": 3,
                    "name": "Tridente Tendencial ($250-$500)",
                    "max_swings": 2,
                    "max_grids": 1,
                    "swing_cap": eq * 0.40,
                    "grid_cap": eq * 0.20
                }
            else:
                return {
                    "tier": 3,
                    "name": "Tridente Chop ($250-$500)",
                    "max_swings": 1,
                    "max_grids": 2,
                    "swing_cap": eq * 0.35,
                    "grid_cap": eq * 0.30
                }
        else:
            return {
                "tier": 4,
                "name": "Fondo Multi-Estrategia Asimétrico (≥$500)",
                "max_swings": 1,
                "max_grids": 2,
                "swing_cap": eq * 0.55,  # ~$275-$300 en $500
                "grid_cap": eq * 0.20   # ~$100 c/u en $500
            }

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
                self._active_grids.clear()
                raw_grids = d.get("active_grids")
                if raw_grids and isinstance(raw_grids, list):
                    for rg in raw_grids:
                        g = BoundedMicroGrid.from_dict(rg)
                        self._active_grids[g.grid_id] = g
                else:
                    raw_grid = d.get("active_grid")
                    if raw_grid and isinstance(raw_grid, dict):
                        g = BoundedMicroGrid.from_dict(raw_grid)
                        self._active_grids[g.grid_id] = g
        except Exception as e:
            self.add_log(f"Error cargando estado desde SQLite: {e}", "error")

    def save_state(self):
        d = {
            "cash": self.cash,
            "active_trade": self.active_trade.to_dict() if self.active_trade else None,
            "active_trades": [t.to_dict() for t in self.active_trades.values()],
            "active_grid": self.active_grid.to_dict() if self.active_grid else None,
            "active_grids": [g.to_dict() for g in self.get_active_grids()],
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
