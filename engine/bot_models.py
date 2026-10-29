"""
Modelos de datos y entidades transaccionales para Swing y Mallas Acotadas.
"""
import time
from typing import Dict, List, Optional


class SwingTrade:
    """Representa una posición activa de Swing Trading (1H/4H)."""
    def __init__(self, trade_id: str, symbol: str, entry_price: float, amount: float,
                 capital: float, target_price: float, stop_price: float, target_pct: float,
                 stop_pct: float, atr_pct: float, rr_ratio: float, entry_time: float,
                 entry_fee: float, initial_stop: Optional[float] = None,
                 of_obi: float = 0.0, of_buy_ratio: float = 50.0,
                 parent_trade_id: Optional[str] = None,
                 leverage: float = 1.0, is_turbo: bool = False):
        self.trade_id = trade_id
        self.symbol = symbol
        self.entry_price = entry_price
        self.amount = amount
        self.capital = capital
        self.target_price = target_price
        self.stop_price = stop_price
        self.initial_stop = initial_stop if initial_stop is not None else stop_price
        self.target_pct = target_pct
        self.stop_pct = stop_pct
        self.atr_pct = atr_pct
        self.rr_ratio = rr_ratio
        self.entry_time = entry_time
        self.entry_fee = entry_fee
        self.of_obi = of_obi
        self.of_buy_ratio = of_buy_ratio
        self.parent_trade_id = parent_trade_id
        self.leverage = leverage
        self.is_turbo = is_turbo
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
            "parent_trade_id": getattr(self, "parent_trade_id", None),
            "leverage": getattr(self, "leverage", 1.0),
            "is_turbo": getattr(self, "is_turbo", False),
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
            target_pct=d["target_pct"],
            stop_pct=d["stop_pct"],
            atr_pct=d["atr_pct"],
            rr_ratio=d["rr_ratio"],
            entry_time=d["entry_time"],
            entry_fee=d["entry_fee"],
            initial_stop=d.get("initial_stop", d["stop_price"]),
            of_obi=d.get("of_obi", 0.0),
            of_buy_ratio=d.get("of_buy_ratio", 50.0),
            parent_trade_id=d.get("parent_trade_id"),
            leverage=d.get("leverage", 1.0),
            is_turbo=d.get("is_turbo", False)
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


class GridLevel:
    """Nivel individual de compra en una Malla Acotada."""
    def __init__(self, level_idx: int, price: float, amount: float, capital: float, status: str = "PENDING"):
        self.level_idx = level_idx
        self.price = price
        self.amount = amount
        self.capital = capital
        self.status = status  # PENDING, FILLED
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
        gl = cls(d["level_idx"], d["price"], d["amount"], d["capital"], d["status"])
        gl.fill_price = d.get("fill_price", 0.0)
        gl.fill_time = d.get("fill_time", 0.0)
        return gl


class BoundedMicroGrid:
    """Malla Micro-Acotada de 3 niveles con Kill-Switch estricto para mercado Chop."""
    def __init__(self, grid_id: str, symbol: str, channel_support: float, 
                 channel_resistance: float, midpoint: float, hurst_exponent: float, 
                 kill_switch_price: float, total_capital: float = 54.0):
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
        filled = self.get_filled_levels()
        if not filled:
            return 0.0
        tot_cap = sum(lvl.capital for lvl in filled)
        tot_amt = sum(lvl.amount for lvl in filled)
        return (tot_cap / tot_amt) if tot_amt > 0 else 0.0

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
            "invested_capital": self.get_invested_capital(),
            "average_entry": self.get_average_entry(),
            "filled_count": len(self.get_filled_levels())
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "BoundedMicroGrid":
        bg = cls(
            grid_id=d["grid_id"],
            symbol=d["symbol"],
            channel_support=d["channel_support"],
            channel_resistance=d["channel_resistance"],
            midpoint=d["midpoint"],
            hurst_exponent=d["hurst_exponent"],
            kill_switch_price=d["kill_switch_price"],
            total_capital=d.get("total_capital", 54.0)
        )
        bg.levels = [GridLevel.from_dict(lvl) for lvl in d.get("levels", [])]
        bg.created_at = d.get("created_at", time.time())
        bg.status = d.get("status", "ACTIVE")
        bg.pnl = d.get("pnl", 0.0)
        bg.pnl_pct = d.get("pnl_pct", 0.0)
        bg.current_price = d.get("current_price", bg.midpoint)
        bg.unrealized_pnl = d.get("unrealized_pnl", 0.0)
        return bg
