"""
Paper Trading Agent - Versión Dual Strategy (v4)
================================================
Estrategias:
1. GRID          → mercados laterales / ranging
2. LONG + Trailing Stop + SL → tendencias alcistas fuertes

Mecánicas realistas incluidas:
- Comisiones
- Slippage
- Fills no garantizados (en grids)
- Tracking exacto de costo (lotes)
- Análisis profundo + predicción de rango
- Trailing Stop dinámico basado en ATR
- Stop Loss inicial
- Supervivencia + logging + gráficos
"""

import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import time
import csv
import os
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
import random

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ====================== CONFIGURACIÓN GENERAL ======================
INITIAL_CAPITAL = 80.0
MIN_EQUITY_RATIO = 0.62
MAX_OPEN_POSITIONS = 2
TOP_N = 3
CHECK_INTERVAL_MINUTES = 10
FEE_RATE = 0.001

# Realismo
BASE_FILL_PROBABILITY = 0.82
SLIPPAGE_ATR_FACTOR = 0.15
MIN_VOLUME_FOR_GOOD_FILL = 12_000_000

# ====================== PERFORMANCE & RISK ======================
COMPOUND_PROFITS = True                 # Reinvertir ganancias
MIN_SCORE_TO_ENTER = 48                 # Score mínimo para abrir cualquier posición
MAX_DAILY_TRADES = 6                    # Evitar overtrading
COOLDOWN_AFTER_LOSS_MINUTES = 45        # Pausa después de un loss
BTC_DUMP_PROTECTION = True              # Reducir riesgo si BTC está cayendo fuerte
BTC_DUMP_THRESHOLD_PCT = -2.8           # Caída de BTC en las últimas 6h para activar protección
DYNAMIC_POSITION_SIZING = True          # Tamaño según fuerza de la señal + volatilidad

# ====================== CONFIG GRID ======================
GRID_LEVELS = 14
GRID_RANGE_PCT = 7.0                    # Se ajustará dinámicamente con ATR
MIN_ORDER_USDT = 5.0
PREFER_RANGING = True

# ====================== CONFIG LONG + TRAILING ======================
LONG_RISK_PCT = 0.32
LONG_ATR_SL_MULTIPLIER = 1.7
LONG_TRAILING_ACTIVATION_ATR = 1.15
LONG_TRAILING_DISTANCE_ATR = 1.35
LONG_MIN_STRENGTH = 63
LONG_MIN_PERSISTENCE = 0.38

LOG_DIR = "paper_logs"
EQUITY_LOG = os.path.join(LOG_DIR, "equity_history.csv")
TRADES_LOG = os.path.join(LOG_DIR, "trades.csv")

# ====================== EXCHANGE ======================
exchange = ccxt.binance({
    "enableRateLimit": True,
    "options": {"defaultType": "spot"}
})

# ====================== ESTRUCTURAS ======================
@dataclass
class Order:
    side: str
    price: float
    amount: float
    level_idx: int
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "open"

@dataclass
class PositionLot:
    amount: float
    entry_price: float
    timestamp: str

@dataclass
class Grid:
    symbol: str
    lower: float
    upper: float
    levels: List[float]
    orders: List[Order]
    capital_allocated: float
    lots: List[PositionLot] = field(default_factory=list)
    realized_pnl: float = 0.0
    fills: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    active: bool = True
    range_persistence_prob: float = 0.5
    strategy: str = "grid"

@dataclass
class LongPosition:
    symbol: str
    amount: float
    entry_price: float
    stop_loss: float
    trailing_stop: float
    trailing_activated: bool = False
    highest_price: float = 0.0
    capital_allocated: float = 0.0
    realized_pnl: float = 0.0
    atr_at_entry: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    active: bool = True
    strategy: str = "long"

class PaperBot:
    def __init__(self):
        self.cash = INITIAL_CAPITAL
        self.holdings: Dict[str, float] = {}
        self.grids: Dict[str, Grid] = {}
        self.longs: Dict[str, LongPosition] = {}
        self.is_alive = True
        self.death_reason: Optional[str] = None
        self.start_time = datetime.now()
        self.total_fees_paid = 0.0
        self.total_slippage_cost = 0.0

        # Performance tracking
        self.wins = 0
        self.losses = 0
        self.total_trades = 0
        self.consecutive_losses = 0
        self.last_loss_time: Optional[datetime] = None
        self.daily_trades = 0
        self.current_day = datetime.now().date()
        self.peak_equity = INITIAL_CAPITAL
        self.max_drawdown = 0.0

        os.makedirs(LOG_DIR, exist_ok=True)
        self._init_logs()

    def _init_logs(self):
        if not os.path.exists(EQUITY_LOG):
            with open(EQUITY_LOG, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "equity", "cash", "holdings_value",
                                 "open_grids", "open_longs", "realized_pnl_total",
                                 "fees_paid", "slippage_cost"])
        if not os.path.exists(TRADES_LOG):
            with open(TRADES_LOG, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "symbol", "strategy", "side", "price", "amount",
                                 "pnl", "fee", "slippage", "extra_info"])

    def get_holdings_value(self, prices: Dict[str, float]) -> float:
        return sum(amount * prices.get(symbol, 0.0) for symbol, amount in self.holdings.items())

    def get_equity(self, prices: Dict[str, float]) -> float:
        return self.cash + self.get_holdings_value(prices)

    def total_realized_pnl(self) -> float:
        grid_pnl = sum(g.realized_pnl for g in self.grids.values())
        long_pnl = sum(l.realized_pnl for l in self.longs.values())
        return grid_pnl + long_pnl

    def open_positions_count(self) -> int:
        return len(self.grids) + len([l for l in self.longs.values() if l.active])

    def check_survival(self, equity: float) -> bool:
        if not self.is_alive:
            return False
        if equity < INITIAL_CAPITAL * MIN_EQUITY_RATIO:
            self.is_alive = False
            self.death_reason = (
                f"Equity cayó a {equity:.2f} USDT "
                f"({equity / INITIAL_CAPITAL * 100:.1f}% del capital inicial)"
            )
            return False
        return True

    def log_equity(self, equity: float, prices: Dict[str, float]):
        with open(EQUITY_LOG, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(),
                round(equity, 4),
                round(self.cash, 4),
                round(self.get_holdings_value(prices), 4),
                len(self.grids),
                len([l for l in self.longs.values() if l.active]),
                round(self.total_realized_pnl(), 4),
                round(self.total_fees_paid, 4),
                round(self.total_slippage_cost, 4)
            ])

    def log_trade(self, symbol, strategy, side, price, amount, pnl, fee, slippage, extra=""):
        with open(TRADES_LOG, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(), symbol, strategy, side,
                round(price, 6), round(amount, 6), round(pnl, 4),
                round(fee, 4), round(slippage, 4), extra
            ])

        # Actualizar estadísticas solo en cierres con PnL
        if side == "sell" and pnl != 0:
            self.total_trades += 1
            self.daily_trades += 1
            if pnl > 0:
                self.wins += 1
                self.consecutive_losses = 0
            else:
                self.losses += 1
                self.consecutive_losses += 1
                self.last_loss_time = datetime.now()

    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.wins / self.total_trades * 100

    def can_open_new_position(self) -> bool:
        """Filtros de rendimiento y riesgo para evitar overtrading."""
        now = datetime.now()

        # Reset contador diario
        if now.date() != self.current_day:
            self.current_day = now.date()
            self.daily_trades = 0

        if self.daily_trades >= MAX_DAILY_TRADES:
            return False

        # Cooldown después de losses
        if self.last_loss_time and self.consecutive_losses >= 2:
            minutes_since_loss = (now - self.last_loss_time).total_seconds() / 60
            if minutes_since_loss < COOLDOWN_AFTER_LOSS_MINUTES:
                return False

        return True

    def update_drawdown(self, equity: float):
        if equity > self.peak_equity:
            self.peak_equity = equity
        dd = (self.peak_equity - equity) / self.peak_equity
        if dd > self.max_drawdown:
            self.max_drawdown = dd

    def calc_position_size(self, equity: float, score: float, atr_pct: float, base_risk: float) -> float:
        """Position sizing dinámico según fuerza de señal y volatilidad."""
        if not DYNAMIC_POSITION_SIZING:
            return min(equity * base_risk, self.cash * 0.80)

        # Score factor (0.7 a 1.25)
        score_factor = 0.70 + min(0.55, (score - 40) / 80)

        # Volatilidad: menos tamaño si ATR muy alto
        vol_factor = 1.0
        if atr_pct > 7.0:
            vol_factor = 0.75
        elif atr_pct > 5.0:
            vol_factor = 0.88
        elif atr_pct < 2.5:
            vol_factor = 1.10

        size = equity * base_risk * score_factor * vol_factor
        return min(size, self.cash * 0.82, equity * 0.42)

# ====================== ANÁLISIS PROFUNDO + ADX AVANZADO ======================
def _compute_adx_full(df: pd.DataFrame, period: int = 14):
    """Calcula ADX, +DI, -DI y series completas para análisis avanzado."""
    high = df["high"]
    low = df["low"]
    close = df["close"]

    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean() / atr
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)) * 100
    adx = dx.ewm(alpha=1/period, adjust=False).mean()

    return adx, plus_di, minus_di, atr


def _find_pivots(series: pd.Series, left: int = 3, right: int = 3, mode: str = "high"):
    """Encuentra pivotes (máximos o mínimos locales)."""
    pivots = []
    values = series.values
    for i in range(left, len(values) - right):
        window = values[i - left: i + right + 1]
        if mode == "high" and values[i] == np.max(window):
            pivots.append((i, values[i]))
        elif mode == "low" and values[i] == np.min(window):
            pivots.append((i, values[i]))
    return pivots


def detect_adx_divergences(df: pd.DataFrame, adx_series: pd.Series, lookback: int = 32) -> Dict:
    """
    Detección completa de divergencias ADX vs Precio (regulares + ocultas).
    Usa pivotes reales + confirmación por volumen.
    """
    result = {
        # Regulares
        "bearish_regular": False,
        "bullish_regular": False,
        "bearish_strength": 0.0,
        "bullish_strength": 0.0,
        "volume_confirmed_bearish": False,
        "volume_confirmed_bullish": False,
        # Ocultas (Hidden)
        "hidden_bullish": False,
        "hidden_bearish": False,
        "hidden_bullish_strength": 0.0,
        "hidden_bearish_strength": 0.0,
        "volume_confirmed_hidden_bullish": False,
        "volume_confirmed_hidden_bearish": False,
    }

    if len(df) < lookback + 10:
        return result

    close = df["close"].tail(lookback + 10).reset_index(drop=True)
    high = df["high"].tail(lookback + 10).reset_index(drop=True)
    low = df["low"].tail(lookback + 10).reset_index(drop=True)
    volume = df["volume"].tail(lookback + 10).reset_index(drop=True) if "volume" in df.columns else None
    adx = adx_series.tail(lookback + 10).reset_index(drop=True)

    price_highs = _find_pivots(high, left=3, right=2, mode="high")
    price_lows = _find_pivots(low, left=3, right=2, mode="low")
    adx_highs = _find_pivots(adx, left=3, right=2, mode="high")
    adx_lows = _find_pivots(adx, left=3, right=2, mode="low")

    def _vol_confirmed(idx1, idx2):
        if volume is None:
            return False
        vol1 = volume.iloc[max(0, idx1-1):idx1+2].mean()
        vol2 = volume.iloc[max(0, idx2-1):idx2+2].mean()
        return vol2 < vol1 * 0.92

    # ========== DIVERGENCIAS REGULARES ==========
    # Bajista Regular: Precio HH + ADX LH
    if len(price_highs) >= 2 and len(adx_highs) >= 2:
        p1_idx, p1_val = price_highs[-2]
        p2_idx, p2_val = price_highs[-1]
        a1 = [a for a in adx_highs if abs(a[0] - p1_idx) <= 4]
        a2 = [a for a in adx_highs if abs(a[0] - p2_idx) <= 4]
        if a1 and a2:
            a1_val, a2_val = a1[-1][1], a2[-1][1]
            if p2_val > p1_val and a2_val < a1_val and a2_val > 25:
                result["bearish_regular"] = True
                result["bearish_strength"] = min(100, (p2_val / p1_val - 1) * 200 + (a1_val - a2_val) * 2)
                if _vol_confirmed(p1_idx, p2_idx):
                    result["volume_confirmed_bearish"] = True
                    result["bearish_strength"] += 15

    # Alcista Regular: Precio LL + ADX HL
    if len(price_lows) >= 2 and len(adx_lows) >= 2:
        p1_idx, p1_val = price_lows[-2]
        p2_idx, p2_val = price_lows[-1]
        a1 = [a for a in adx_lows if abs(a[0] - p1_idx) <= 4]
        a2 = [a for a in adx_lows if abs(a[0] - p2_idx) <= 4]
        if a1 and a2:
            a1_val, a2_val = a1[-1][1], a2[-1][1]
            if p2_val < p1_val and a2_val > a1_val:
                result["bullish_regular"] = True
                result["bullish_strength"] = min(100, (p1_val / p2_val - 1) * 200 + (a2_val - a1_val) * 2)
                if _vol_confirmed(p1_idx, p2_idx):
                    result["volume_confirmed_bullish"] = True
                    result["bullish_strength"] += 15

    # ========== DIVERGENCIAS OCULTAS (HIDDEN) ==========
    # Hidden Bullish: Precio Higher Low + ADX Lower Low → continuación alcista
    if len(price_lows) >= 2 and len(adx_lows) >= 2:
        p1_idx, p1_val = price_lows[-2]
        p2_idx, p2_val = price_lows[-1]
        a1 = [a for a in adx_lows if abs(a[0] - p1_idx) <= 4]
        a2 = [a for a in adx_lows if abs(a[0] - p2_idx) <= 4]
        if a1 and a2:
            a1_val, a2_val = a1[-1][1], a2[-1][1]
            if p2_val > p1_val and a2_val < a1_val:
                result["hidden_bullish"] = True
                result["hidden_bullish_strength"] = min(100, (p2_val / p1_val - 1) * 180 + (a1_val - a2_val) * 2.2)
                if _vol_confirmed(p1_idx, p2_idx):
                    result["volume_confirmed_hidden_bullish"] = True
                    result["hidden_bullish_strength"] += 12

    # Hidden Bearish: Precio Lower High + ADX Higher High → continuación bajista
    if len(price_highs) >= 2 and len(adx_highs) >= 2:
        p1_idx, p1_val = price_highs[-2]
        p2_idx, p2_val = price_highs[-1]
        a1 = [a for a in adx_highs if abs(a[0] - p1_idx) <= 4]
        a2 = [a for a in adx_highs if abs(a[0] - p2_idx) <= 4]
        if a1 and a2:
            a1_val, a2_val = a1[-1][1], a2[-1][1]
            if p2_val < p1_val and a2_val > a1_val and a2_val > 25:
                result["hidden_bearish"] = True
                result["hidden_bearish_strength"] = min(100, (p1_val / p2_val - 1) * 180 + (a2_val - a1_val) * 2.2)
                if _vol_confirmed(p1_idx, p2_idx):
                    result["volume_confirmed_hidden_bearish"] = True
                    result["hidden_bearish_strength"] += 12

    return result


def get_deep_analysis(symbol: str, df: pd.DataFrame, df_4h: Optional[pd.DataFrame] = None,
                      btc_df: Optional[pd.DataFrame] = None) -> Dict:
    """
    Análisis avanzado con todas las mejoras de ADX:
    1. ADX rising
    2. Cruce +DI / -DI
    3. DI Spread mínimo
    4. Divergencia ADX vs Precio
    5. Multi-timeframe (1h + 4h)
    6. ADX adaptativo según volatilidad
    """
    if len(df) < 90:
        return {"error": "Datos insuficientes", "recommendation": "skip", "score": 0}

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # ---------- ATR y régimen de volatilidad ----------
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr_series = tr.rolling(14).mean()
    atr_pct = (atr_series.iloc[-1] / close.iloc[-1]) * 100
    atr_value = float(atr_series.iloc[-1])
    atr_pct_series = (atr_series / close) * 100
    vol_regime = "high" if atr_pct > atr_pct_series.quantile(0.75) else \
                 "low" if atr_pct < atr_pct_series.quantile(0.30) else "normal"

    # ---------- ADX completo (1h) ----------
    adx_series, plus_di, minus_di, _ = _compute_adx_full(df, 14)
    adx = float(adx_series.iloc[-1])
    adx_prev_3 = float(adx_series.iloc[-4]) if len(adx_series) >= 4 else adx
    adx_prev_5 = float(adx_series.iloc[-6]) if len(adx_series) >= 6 else adx
    current_plus = float(plus_di.iloc[-1])
    current_minus = float(minus_di.iloc[-1])
    prev_plus = float(plus_di.iloc[-2]) if len(plus_di) >= 2 else current_plus
    prev_minus = float(minus_di.iloc[-2]) if len(minus_di) >= 2 else current_minus

    # 1. ADX rising
    adx_rising = adx > adx_prev_3 and adx >= adx_prev_5

    # 2. Cruce +DI / -DI
    di_cross_up = (current_plus > current_minus) and (prev_plus <= prev_minus)
    di_cross_down = (current_minus > current_plus) and (prev_minus <= prev_plus)
    di_bullish = current_plus > current_minus

    # 3. DI Spread
    di_spread = abs(current_plus - current_minus)

    # 4. Divergencias ADX completas (regulares + ocultas + volumen + 4h)
    divergences = detect_adx_divergences(df, adx_series, lookback=32)
    bearish_divergence = divergences["bearish_regular"]
    bullish_divergence = divergences["bullish_regular"]
    bearish_div_strength = divergences["bearish_strength"]
    bullish_div_strength = divergences["bullish_strength"]
    vol_confirmed_bearish = divergences["volume_confirmed_bearish"]
    vol_confirmed_bullish = divergences["volume_confirmed_bullish"]

    hidden_bullish = divergences["hidden_bullish"]
    hidden_bearish = divergences["hidden_bearish"]
    hidden_bullish_strength = divergences["hidden_bullish_strength"]
    hidden_bearish_strength = divergences["hidden_bearish_strength"]
    vol_confirmed_hidden_bullish = divergences["volume_confirmed_hidden_bullish"]
    vol_confirmed_hidden_bearish = divergences["volume_confirmed_hidden_bearish"]

    # Divergencias en 4h
    bearish_div_4h = False
    bullish_div_4h = False
    hidden_bullish_4h = False
    hidden_bearish_4h = False
    if df_4h is not None and len(df_4h) >= 40:
        adx_4h_series_full, _, _, _ = _compute_adx_full(df_4h, 14)
        div_4h = detect_adx_divergences(df_4h, adx_4h_series_full, lookback=28)
        bearish_div_4h = div_4h["bearish_regular"]
        bullish_div_4h = div_4h["bullish_regular"]
        hidden_bullish_4h = div_4h["hidden_bullish"]
        hidden_bearish_4h = div_4h["hidden_bearish"]

    # 5. Multi-timeframe ADX (4h)
    adx_4h = None
    plus_di_4h = None
    minus_di_4h = None
    adx_4h_rising = False
    if df_4h is not None and len(df_4h) >= 40:
        adx_4h_series, plus_4h, minus_4h, _ = _compute_adx_full(df_4h, 14)
        adx_4h = float(adx_4h_series.iloc[-1])
        plus_di_4h = float(plus_4h.iloc[-1])
        minus_di_4h = float(minus_4h.iloc[-1])
        adx_4h_prev = float(adx_4h_series.iloc[-3]) if len(adx_4h_series) >= 3 else adx_4h
        adx_4h_rising = adx_4h > adx_4h_prev

    # 6. ADX adaptativo según volatilidad
    # En alta volatilidad exigimos ADX más alto para confirmar tendencia
    if vol_regime == "high":
        adx_threshold_trend = 29
        adx_threshold_range = 22
    elif vol_regime == "low":
        adx_threshold_trend = 23
        adx_threshold_range = 18
    else:
        adx_threshold_trend = 26
        adx_threshold_range = 20

    # EMAs
    ema20 = close.ewm(span=20).mean().iloc[-1]
    ema50 = close.ewm(span=50).mean().iloc[-1]
    ema_trend = "up" if ema20 > ema50 else "down"

    # Drawdown reciente
    recent = close.tail(40)
    rolling_max = recent.cummax()
    drawdown = (recent - rolling_max) / rolling_max
    max_dd_recent = float(drawdown.min())

    # Correlación BTC
    corr_btc = 0.0
    if btc_df is not None and len(btc_df) >= 50:
        try:
            common_len = min(len(close), len(btc_df["close"]))
            corr_btc = float(close.tail(common_len).corr(btc_df["close"].tail(common_len)))
        except Exception:
            pass

    # Persistencia de rango
    lookback = 60
    range_pct = GRID_RANGE_PCT / 100
    current_price = close.iloc[-1]
    lower_test = current_price * (1 - range_pct / 2)
    upper_test = current_price * (1 + range_pct / 2)
    stays_in_range = 0
    total_windows = 0
    for i in range(max(0, len(close) - lookback - 12), len(close) - 12):
        window = close.iloc[i:i+12]
        if len(window) < 12:
            continue
        total_windows += 1
        if window.min() >= lower_test * 0.97 and window.max() <= upper_test * 1.03:
            stays_in_range += 1
    range_persistence_prob = stays_in_range / total_windows if total_windows > 0 else 0.45

    # Momentum
    momentum = (close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) >= 6 else 0

    # ---------- LÓGICA DE DECISIÓN MEJORADA ----------
    strength = min(100.0, adx * 2.1)

    # Condiciones de tendencia alcista fuerte (Long)
    mtf_confirm = True
    if adx_4h is not None:
        mtf_confirm = adx_4h >= 22 and plus_di_4h > minus_di_4h

    is_strong_up = (
        adx >= adx_threshold_trend and
        adx_rising and
        di_bullish and
        di_spread >= 5.0 and
        not bearish_divergence and
        not bearish_div_4h and
        ema_trend == "up" and
        strength >= LONG_MIN_STRENGTH and
        momentum > 0.6 and
        mtf_confirm
    )

    # Condiciones de rango (Grid)
    is_ranging = (
        adx < adx_threshold_range and
        range_persistence_prob > 0.38 and
        di_spread < 12
    )

    # Recomendación final
    if is_strong_up and range_persistence_prob < 0.58:
        recommendation = "long"
    elif is_ranging or (PREFER_RANGING and not is_strong_up and adx < 28):
        recommendation = "grid"
    else:
        recommendation = "skip"

    # Score de ranking más sofisticado
    score = strength * 0.25
    if recommendation == "long":
        score += 20
        if adx_rising:
            score += 8
        if di_cross_up:
            score += 6
        if di_spread > 10:
            score += 5
        if mtf_confirm and adx_4h and adx_4h_rising:
            score += 7
        score += min(momentum * 1.3, 12)

        # Divergencias regulares (penalizan)
        if bearish_divergence:
            score -= 18
            if vol_confirmed_bearish:
                score -= 8
        if bearish_div_4h:
            score -= 12
        if bullish_divergence:
            score += 4

        # Divergencias ocultas (continuación)
        if hidden_bullish:
            score += 8
            if vol_confirmed_hidden_bullish:
                score += 5
            if hidden_bullish_strength > 45:
                score += 4
        if hidden_bullish_4h:
            score += 6
        if hidden_bearish:
            score -= 11
            if vol_confirmed_hidden_bearish:
                score -= 5
        if hidden_bearish_4h:
            score -= 7

    elif recommendation == "grid":
        score += range_persistence_prob * 28
        if di_spread < 8:
            score += 6
        if bullish_divergence and vol_confirmed_bullish:
            score += 5
        if hidden_bullish:
            score += 3

    score += max(0, 10 + max_dd_recent * 30)
    if vol_regime == "normal":
        score += 5

    return {
        "strength_score": round(strength, 1),
        "adx": round(adx, 1),
        "adx_rising": adx_rising,
        "adx_4h": round(adx_4h, 1) if adx_4h is not None else None,
        "adx_4h_rising": adx_4h_rising,
        "atr_pct": round(atr_pct, 2),
        "atr_value": atr_value,
        "vol_regime": vol_regime,
        "di_spread": round(di_spread, 1),
        "di_cross_up": di_cross_up,
        "bearish_divergence": bearish_divergence,
        "bullish_divergence": bullish_divergence,
        "bearish_div_strength": round(bearish_div_strength, 1),
        "bullish_div_strength": round(bullish_div_strength, 1),
        "vol_confirmed_bearish": vol_confirmed_bearish,
        "vol_confirmed_bullish": vol_confirmed_bullish,
        "bearish_div_4h": bearish_div_4h,
        "bullish_div_4h": bullish_div_4h,
        # Hidden
        "hidden_bullish": hidden_bullish,
        "hidden_bearish": hidden_bearish,
        "hidden_bullish_strength": round(hidden_bullish_strength, 1),
        "hidden_bearish_strength": round(hidden_bearish_strength, 1),
        "vol_confirmed_hidden_bullish": vol_confirmed_hidden_bullish,
        "vol_confirmed_hidden_bearish": vol_confirmed_hidden_bearish,
        "hidden_bullish_4h": hidden_bullish_4h,
        "hidden_bearish_4h": hidden_bearish_4h,
        "max_dd_recent": round(max_dd_recent * 100, 2),
        "corr_btc": round(corr_btc, 3),
        "range_persistence_prob": round(range_persistence_prob, 3),
        "momentum": round(momentum, 2),
        "ema_trend": ema_trend,
        "plus_di": round(current_plus, 1),
        "minus_di": round(current_minus, 1),
        "is_ranging": is_ranging,
        "is_strong_up": is_strong_up,
        "recommendation": recommendation,
        "score": round(max(0, score), 1),
        "label": recommendation,
        "adx_threshold_used": adx_threshold_trend
    }

# ====================== SELECCIÓN ======================
def select_best_opportunities(bot: PaperBot, top_n: int = 3) -> List[Dict]:
    print("  → Análisis ADX avanzado (multi-timeframe + divergencias)...")
    try:
        markets = exchange.load_markets()
        usdt_pairs = [s for s in markets if s.endswith("/USDT") and markets[s].get("spot") and markets[s].get("active")]
        tickers = exchange.fetch_tickers(usdt_pairs[:90])
        candidates = sorted(
            [s for s in usdt_pairs if s in tickers],
            key=lambda x: tickers[x].get("quoteVolume", 0) or 0,
            reverse=True
        )[:32]
    except Exception as e:
        print(f"  Error mercados: {e}")
        return []

    try:
        btc_ohlcv = exchange.fetch_ohlcv("BTC/USDT", "1h", limit=120)
        btc_df = pd.DataFrame(btc_ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    except Exception:
        btc_df = None

    results = []
    for symbol in candidates:
        if symbol in bot.grids or symbol in bot.longs:
            continue
        try:
            # Timeframe principal 1h
            ohlcv = exchange.fetch_ohlcv(symbol, "1h", limit=130)
            df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])

            # Timeframe 4h para confirmación multi-TF
            try:
                ohlcv_4h = exchange.fetch_ohlcv(symbol, "4h", limit=60)
                df_4h = pd.DataFrame(ohlcv_4h, columns=["ts", "open", "high", "low", "close", "volume"])
            except Exception:
                df_4h = None

            analysis = get_deep_analysis(symbol, df, df_4h, btc_df)
            if "error" in analysis or analysis["recommendation"] == "skip":
                continue

            volume = tickers[symbol].get("quoteVolume", 0) or 0
            if volume < 7_500_000:
                continue
            if not (1.5 <= analysis["atr_pct"] <= 12.0):
                continue

            liquidity_bonus = min(10, np.log10(volume) * 1.0)
            final_score = analysis["score"] + liquidity_bonus

            results.append({
                "symbol": symbol,
                "score": round(final_score, 1),
                "analysis": analysis,
                "volume": volume,
                "price": tickers[symbol]["last"]
            })
        except Exception:
            continue

    ranked = sorted(results, key=lambda x: x["score"], reverse=True)
    return ranked[:top_n]

# ====================== HELPERS REALISTAS ======================
def apply_slippage(price: float, side: str, atr_pct: float, volume_24h: float) -> Tuple[float, float]:
    max_slip_pct = (atr_pct / 100) * SLIPPAGE_ATR_FACTOR
    if volume_24h < 12_000_000:
        max_slip_pct *= 1.5
    slip_pct = random.uniform(0, max_slip_pct)
    if side == "buy":
        executed = price * (1 + slip_pct)
    else:
        executed = price * (1 - slip_pct)
    return executed, slip_pct

def calculate_fill_probability(volume_24h: float, atr_pct: float, order_usdt: float) -> float:
    prob = BASE_FILL_PROBABILITY
    if volume_24h > 40_000_000:
        prob += 0.09
    elif volume_24h < MIN_VOLUME_FOR_GOOD_FILL:
        prob -= 0.13
    if order_usdt > 22:
        prob -= 0.05
    if atr_pct > 6.5:
        prob -= 0.04
    return float(np.clip(prob, 0.35, 0.94))

# ====================== LONG + TRAILING ======================
def open_long(bot: PaperBot, symbol: str, capital: float, current_price: float,
              analysis: Dict, volume_24h: float) -> bool:
    atr_value = analysis["atr_value"]
    atr_pct = analysis["atr_pct"]

    # Slippage en la entrada
    executed_price, slip_pct = apply_slippage(current_price, "buy", atr_pct, volume_24h)
    amount = capital / executed_price
    fee = capital * FEE_RATE
    total_cost = capital + fee

    if bot.cash < total_cost:
        print(f"  ✗ Cash insuficiente para Long en {symbol}")
        return False

    bot.cash -= total_cost
    bot.holdings[symbol] = bot.holdings.get(symbol, 0.0) + amount
    bot.total_fees_paid += fee
    bot.total_slippage_cost += abs(executed_price - current_price) * amount

    # Stop Loss inicial
    sl_price = executed_price - (atr_value * LONG_ATR_SL_MULTIPLIER)
    # Trailing inicial (todavía no activado)
    trailing = sl_price

    long_pos = LongPosition(
        symbol=symbol,
        amount=amount,
        entry_price=executed_price,
        stop_loss=sl_price,
        trailing_stop=trailing,
        highest_price=executed_price,
        capital_allocated=capital,
        atr_at_entry=atr_value
    )
    bot.longs[symbol] = long_pos

    bot.log_trade(symbol, "long", "buy", executed_price, amount, 0.0, fee,
                  abs(executed_price - current_price) * amount,
                  f"SL={sl_price:.5f} | ATR={atr_value:.5f}")

    print(f"  ✓ LONG abierto: {symbol}")
    print(f"     Entrada: {executed_price:.5f} | SL inicial: {sl_price:.5f}")
    print(f"     ADX: {analysis['adx']} (rising={analysis['adx_rising']}) | DI Spread: {analysis['di_spread']}")
    print(f"     Hidden Bullish: {analysis.get('hidden_bullish')} (str={analysis.get('hidden_bullish_strength')}) | Hidden Bearish: {analysis.get('hidden_bearish')}")
    print(f"     Div Regular Bajista: {analysis.get('bearish_divergence')} | 4h: {analysis.get('bearish_div_4h')}")
    return True


def manage_longs(bot: PaperBot, prices: Dict[str, float], atrs: Dict[str, float]):
    """
    Gestiona Longs:
    - Actualiza Trailing Stop
    - Cierra por SL / Trailing
    - Cierre anticipado por divergencia bajista fuerte de ADX
    """
    for symbol, pos in list(bot.longs.items()):
        if not pos.active:
            continue

        price = prices.get(symbol)
        if price is None:
            continue

        atr = atrs.get(symbol, pos.atr_at_entry)
        exit_reason = None

        # ----- 1. Actualizar máximo y trailing -----
        if price > pos.highest_price:
            pos.highest_price = price

            gain_atr = (price - pos.entry_price) / pos.atr_at_entry if pos.atr_at_entry > 0 else 0
            if not pos.trailing_activated and gain_atr >= LONG_TRAILING_ACTIVATION_ATR:
                pos.trailing_activated = True
                print(f"     Trailing ACTIVADO en {symbol} (ganancia {gain_atr:.2f} ATR)")

            if pos.trailing_activated:
                new_trailing = price - (atr * LONG_TRAILING_DISTANCE_ATR)
                if new_trailing > pos.trailing_stop:
                    pos.trailing_stop = new_trailing
                    pos.stop_loss = max(pos.stop_loss, pos.trailing_stop)

        # ----- 2. Divergencias (regulares + ocultas) -----
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, "1h", limit=70)
            df_tmp = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
            adx_tmp, _, _, _ = _compute_adx_full(df_tmp, 14)
            divs = detect_adx_divergences(df_tmp, adx_tmp, lookback=32)

            current_pnl_pct = (price / pos.entry_price - 1) * 100

            # Cierre anticipado por divergencia regular bajista fuerte
            if divs["bearish_regular"] and divs["bearish_strength"] >= 35:
                if current_pnl_pct > 0.4 or divs["bearish_strength"] >= 55 or divs["volume_confirmed_bearish"]:
                    exit_reason = f"Divergencia Bajista ADX (str={divs['bearish_strength']:.0f})"

            # Hidden Bearish → hacer trailing más agresivo
            if divs["hidden_bearish"] and divs["hidden_bearish_strength"] >= 30 and pos.trailing_activated:
                aggressive_trailing = price - (atr * LONG_TRAILING_DISTANCE_ATR * 0.75)
                if aggressive_trailing > pos.trailing_stop:
                    pos.trailing_stop = aggressive_trailing
                    pos.stop_loss = max(pos.stop_loss, pos.trailing_stop)
                    print(f"     Trailing AGRESIVO por Hidden Bearish en {symbol}")

            # Hidden Bullish → relajar trailing (dar más aire al pullback)
            if divs["hidden_bullish"] and divs["hidden_bullish_strength"] >= 30 and pos.trailing_activated:
                # Solo relajamos si el precio está corrigiendo
                if price < pos.highest_price * 0.995:
                    relaxed_trailing = price - (atr * LONG_TRAILING_DISTANCE_ATR * 1.35)
                    # No bajamos el stop_loss, solo evitamos subirlo demasiado rápido
                    if relaxed_trailing < pos.trailing_stop:
                        pos.trailing_stop = max(pos.stop_loss, relaxed_trailing)
                        print(f"     Trailing RELAJADO por Hidden Bullish en {symbol}")

        except Exception:
            pass

        # ----- 3. Verificar Stop Loss / Trailing -----
        if exit_reason is None and price <= pos.stop_loss:
            exit_reason = "Trailing Stop" if pos.trailing_activated else "Stop Loss"

        # ----- 4. Ejecutar cierre si corresponde -----
        if exit_reason:
            executed_price, slip_pct = apply_slippage(
                price, "sell",
                (atr / price) * 100 if price > 0 else 3.0,
                20_000_000
            )
            revenue = pos.amount * executed_price
            fee = revenue * FEE_RATE
            pnl = revenue - fee - (pos.amount * pos.entry_price)

            bot.cash += (revenue - fee)
            bot.holdings[symbol] = bot.holdings.get(symbol, 0.0) - pos.amount
            if bot.holdings.get(symbol, 0) < 1e-10:
                bot.holdings.pop(symbol, None)

            bot.total_fees_paid += fee
            bot.total_slippage_cost += abs(executed_price - price) * pos.amount
            pos.realized_pnl = pnl
            pos.active = False

            bot.log_trade(symbol, "long", "sell", executed_price, pos.amount, pnl, fee,
                          abs(executed_price - price) * pos.amount, exit_reason)

            print(f"     LONG CERRADO {symbol} @ {executed_price:.5f} | PnL: {pnl:+.4f} ({exit_reason})")
            del bot.longs[symbol]

# ====================== GRID (se mantiene) ======================
def create_paper_grid(bot: PaperBot, symbol: str, capital: float, current_price: float,
                      analysis: Dict, volume_24h: float) -> bool:
    range_pct = GRID_RANGE_PCT / 100
    lower = current_price * (1 - range_pct / 2)
    upper = current_price * (1 + range_pct / 2)
    levels = np.linspace(lower, upper, GRID_LEVELS + 1).tolist()

    usable = capital * 0.92
    buy_levels = [l for l in levels if l < current_price]
    n_buy = max(1, len(buy_levels))
    usdt_per_order = usable / (n_buy + 1)

    if usdt_per_order < MIN_ORDER_USDT:
        return False

    orders = []
    for i, level in enumerate(levels):
        if level < current_price:
            amount = usdt_per_order / level
            orders.append(Order(side="buy", price=level, amount=amount, level_idx=i))

    base_usdt = usable * 0.30
    base_amount = base_usdt / current_price
    bot.cash -= base_usdt
    bot.holdings[symbol] = bot.holdings.get(symbol, 0.0) + base_amount
    lots = [PositionLot(amount=base_amount, entry_price=current_price, timestamp=datetime.now().isoformat())]

    for i, level in enumerate(levels):
        if level > current_price:
            amount = (base_amount / max(1, len([l for l in levels if l > current_price]))) * 0.85
            orders.append(Order(side="sell", price=level, amount=amount, level_idx=i))

    bot.cash = max(0.0, bot.cash - usable * 0.05)

    grid = Grid(
        symbol=symbol, lower=lower, upper=upper, levels=levels,
        orders=orders, capital_allocated=capital, lots=lots,
        range_persistence_prob=analysis.get("range_persistence_prob", 0.5)
    )
    bot.grids[symbol] = grid

    print(f"  ✓ GRID creado: {symbol} | Rango {lower:.5f}-{upper:.5f}")
    print(f"     Persistencia: {grid.range_persistence_prob*100:.1f}% | ADX: {analysis.get('adx')} | DI Spread: {analysis.get('di_spread')}")
    return True


def process_grids(bot: PaperBot, prices: Dict[str, float], volumes: Dict[str, float], atrs: Dict[str, float]):
    for symbol, grid in list(bot.grids.items()):
        if not grid.active:
            continue
        price = prices.get(symbol)
        if price is None:
            continue
        volume_24h = volumes.get(symbol, 10_000_000)
        atr_pct = atrs.get(symbol, 3.0)

        remaining_orders = []
        for order in grid.orders:
            if order.status != "open":
                continue

            should_try = (order.side == "buy" and price <= order.price) or \
                         (order.side == "sell" and price >= order.price)
            if not should_try:
                remaining_orders.append(order)
                continue

            order_usdt = order.amount * order.price
            fill_prob = calculate_fill_probability(volume_24h, atr_pct, order_usdt)
            if random.random() > fill_prob:
                remaining_orders.append(order)
                continue

            executed_price, slip_pct = apply_slippage(order.price, order.side, atr_pct, volume_24h)
            slip_cost = abs(executed_price - order.price) * order.amount
            fee = 0.0
            pnl = 0.0

            if order.side == "buy":
                cost = order.amount * executed_price
                fee = cost * FEE_RATE
                if bot.cash >= cost + fee:
                    bot.cash -= (cost + fee)
                    bot.holdings[symbol] = bot.holdings.get(symbol, 0.0) + order.amount
                    bot.total_fees_paid += fee
                    bot.total_slippage_cost += slip_cost
                    grid.lots.append(PositionLot(amount=order.amount, entry_price=executed_price,
                                                 timestamp=datetime.now().isoformat()))
                    next_idx = min(order.level_idx + 1, len(grid.levels) - 1)
                    remaining_orders.append(Order(side="sell", price=grid.levels[next_idx],
                                                  amount=order.amount, level_idx=next_idx))
                    grid.fills += 1
                    bot.log_trade(symbol, "grid", "buy", executed_price, order.amount, 0.0, fee, slip_cost)
                    print(f"     GRID BUY  {symbol} @ {executed_price:.5f}")
            else:
                if bot.holdings.get(symbol, 0) >= order.amount * 0.998:
                    remaining_to_sell = order.amount
                    total_entry_cost = 0.0
                    for lot in grid.lots:
                        if remaining_to_sell <= 0:
                            break
                        take = min(lot.amount, remaining_to_sell)
                        total_entry_cost += take * lot.entry_price
                        lot.amount -= take
                        remaining_to_sell -= take
                    grid.lots = [l for l in grid.lots if l.amount > 1e-10]

                    revenue = order.amount * executed_price
                    fee = revenue * FEE_RATE
                    pnl = revenue - fee - total_entry_cost
                    bot.cash += (revenue - fee)
                    bot.holdings[symbol] -= order.amount
                    bot.total_fees_paid += fee
                    bot.total_slippage_cost += slip_cost
                    grid.realized_pnl += pnl

                    prev_idx = max(order.level_idx - 1, 0)
                    remaining_orders.append(Order(side="buy", price=grid.levels[prev_idx],
                                                  amount=order.amount, level_idx=prev_idx))
                    grid.fills += 1
                    bot.log_trade(symbol, "grid", "sell", executed_price, order.amount, pnl, fee, slip_cost)
                    print(f"     GRID SELL {symbol} @ {executed_price:.5f} | PnL: {pnl:+.4f}")

        grid.orders = remaining_orders

# ====================== LOOP PRINCIPAL ======================
def run_paper_trading():
    bot = PaperBot()

    print("=" * 72)
    print("  PAPER TRADING AGENT v4 - DUAL STRATEGY")
    print("  • GRID          → mercados laterales")
    print("  • LONG+Trailing → tendencias alcistas fuertes")
    print(f"  Capital inicial: {INITIAL_CAPITAL:.2f} USDT | Umbral muerte: {MIN_EQUITY_RATIO*100:.0f}%")
    print("=" * 72)

    cycle = 0
    while bot.is_alive:
        try:
            cycle += 1
            print(f"\n----- Ciclo {cycle} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} -----")

            # Datos de mercado
            prices, volumes, atrs = {}, {}, {}
            symbols = set(list(bot.holdings.keys()) + list(bot.grids.keys()) + list(bot.longs.keys()))
            for symbol in symbols:
                try:
                    t = exchange.fetch_ticker(symbol)
                    prices[symbol] = t["last"]
                    volumes[symbol] = t.get("quoteVolume", 10_000_000) or 10_000_000
                    ohlcv = exchange.fetch_ohlcv(symbol, "1h", limit=20)
                    df = pd.DataFrame(ohlcv, columns=["ts","o","h","l","c","v"])
                    tr = pd.concat([df["h"]-df["l"], (df["h"]-df["c"].shift()).abs(),
                                   (df["l"]-df["c"].shift()).abs()], axis=1).max(axis=1)
                    atrs[symbol] = float(tr.mean())
                except Exception:
                    pass

            # Gestionar Longs (trailing + SL)
            if bot.longs:
                print("  Gestionando Longs (Trailing / SL)...")
                manage_longs(bot, prices, atrs)

            # Procesar Grids
            if bot.grids:
                print("  Procesando Grids...")
                process_grids(bot, prices, volumes, {s: (atrs.get(s, 0)/prices.get(s, 1))*100 for s in atrs})

            equity = bot.get_equity(prices)
            bot.log_equity(equity, prices)
            bot.update_drawdown(equity)

            print(f"  Equity: {equity:.2f} USDT | Cash: {bot.cash:.2f} | Peak: {bot.peak_equity:.2f}")
            print(f"  PnL: {bot.total_realized_pnl():+.4f} | Fees+Slip: {bot.total_fees_paid + bot.total_slippage_cost:.4f}")
            print(f"  WinRate: {bot.win_rate():.1f}% ({bot.wins}W/{bot.losses}L) | MaxDD: {bot.max_drawdown*100:.1f}% | Trades hoy: {bot.daily_trades}")
            print(f"  Posiciones: {len(bot.grids)} grids | {len([l for l in bot.longs.values() if l.active])} longs")

            if not bot.check_survival(equity):
                print("\n" + "!" * 72)
                print("  BOT MUERTO")
                print(f"  {bot.death_reason}")
                print("!" * 72)
                break

            # Protección BTC dump
            btc_risk_off = False
            if BTC_DUMP_PROTECTION:
                try:
                    btc_ohlcv = exchange.fetch_ohlcv("BTC/USDT", "1h", limit=8)
                    btc_close = [x[4] for x in btc_ohlcv]
                    btc_change = (btc_close[-1] / btc_close[0] - 1) * 100
                    if btc_change <= BTC_DUMP_THRESHOLD_PCT:
                        btc_risk_off = True
                        print(f"  ⚠ BTC dump detectado ({btc_change:.2f}%) → modo riesgo reducido")
                except Exception:
                    pass

            # Buscar nuevas oportunidades
            if (bot.open_positions_count() < MAX_OPEN_POSITIONS and bot.cash > 16
                    and bot.can_open_new_position()):
                opportunities = select_best_opportunities(bot, TOP_N)
                for opp in opportunities:
                    if bot.open_positions_count() >= MAX_OPEN_POSITIONS:
                        break
                    if opp["score"] < MIN_SCORE_TO_ENTER:
                        continue

                    symbol = opp["symbol"]
                    analysis = opp["analysis"]

                    # Position sizing dinámico
                    base_risk = LONG_RISK_PCT * (0.65 if btc_risk_off else 1.0)
                    capital = bot.calc_position_size(
                        equity, opp["score"], analysis.get("atr_pct", 4.0), base_risk
                    )
                    if capital < 13:
                        continue

                    if analysis["recommendation"] == "long" and not btc_risk_off:
                        open_long(bot, symbol, capital, opp["price"], analysis, opp["volume"])
                    elif analysis["recommendation"] == "grid":
                        # Rango de grid dinámico según ATR
                        global GRID_RANGE_PCT
                        atr_pct = analysis.get("atr_pct", 4.0)
                        dynamic_range = max(5.0, min(11.0, atr_pct * 1.6))
                        old_range = GRID_RANGE_PCT
                        GRID_RANGE_PCT = dynamic_range
                        create_paper_grid(bot, symbol, capital, opp["price"], analysis, opp["volume"])
                        GRID_RANGE_PCT = old_range

            print(f"  Activos → Grids: {list(bot.grids.keys())} | Longs: {list(bot.longs.keys())}")
            print(f"  Próximo ciclo en {CHECK_INTERVAL_MINUTES} min...")
            time.sleep(CHECK_INTERVAL_MINUTES * 60)

        except KeyboardInterrupt:
            print("\n  Detenido manualmente.")
            break
        except Exception as e:
            print(f"  Error: {e}")
            time.sleep(30)

    # Resumen final
    final_prices = {}
    for s in set(list(bot.holdings.keys()) + list(bot.grids.keys()) + list(bot.longs.keys())):
        try:
            final_prices[s] = exchange.fetch_ticker(s)["last"]
        except Exception:
            final_prices[s] = 0.0

    final_equity = bot.get_equity(final_prices)

    print("\n" + "=" * 72)
    print("  RESUMEN FINAL - DUAL STRATEGY + PERFORMANCE")
    print("=" * 72)
    print(f"  Capital inicial     : {INITIAL_CAPITAL:.2f} USDT")
    print(f"  Equity final        : {final_equity:.2f} USDT")
    print(f"  Rendimiento         : {(final_equity/INITIAL_CAPITAL-1)*100:+.2f}%")
    print(f"  Peak Equity         : {bot.peak_equity:.2f} USDT")
    print(f"  Max Drawdown        : {bot.max_drawdown*100:.2f}%")
    print(f"  PnL realizado       : {bot.total_realized_pnl():+.4f} USDT")
    print(f"  Fees + Slippage     : {bot.total_fees_paid + bot.total_slippage_cost:.4f} USDT")
    print(f"  Trades totales      : {bot.total_trades} | WinRate: {bot.win_rate():.1f}% ({bot.wins}W / {bot.losses}L)")
    print(f"  Tiempo vivo         : {datetime.now() - bot.start_time}")
    if bot.death_reason:
        print(f"  Razón de muerte     : {bot.death_reason}")
    print("=" * 72)

    generate_equity_chart()


def generate_equity_chart():
    try:
        if not os.path.exists(EQUITY_LOG):
            return
        df = pd.read_csv(EQUITY_LOG)
        if len(df) < 2:
            return
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
        fig.suptitle("Paper Trading Agent v4 - Dual Strategy (Grid + Long/Trailing)", fontsize=13, fontweight="bold")

        ax1 = axes[0]
        ax1.plot(df["timestamp"], df["equity"], color="#00c853", linewidth=2, label="Equity")
        ax1.axhline(INITIAL_CAPITAL, color="gray", linestyle="--", alpha=0.7, label="Inicial")
        ax1.axhline(INITIAL_CAPITAL * MIN_EQUITY_RATIO, color="red", linestyle="--", alpha=0.7, label="Umbral muerte")
        ax1.set_ylabel("Equity (USDT)")
        ax1.legend(loc="upper left")
        ax1.grid(True, alpha=0.3)

        ax2 = axes[1]
        ax2.plot(df["timestamp"], df["cash"], color="#2196f3", label="Cash")
        ax2.plot(df["timestamp"], df["holdings_value"], color="#ff9800", label="Holdings")
        ax2.plot(df["timestamp"], df["realized_pnl_total"], color="#9c27b0", label="PnL Realizado")
        ax2.set_ylabel("USDT")
        ax2.set_xlabel("Tiempo")
        ax2.legend(loc="upper left")
        ax2.grid(True, alpha=0.3)

        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
        fig.autofmt_xdate()
        plt.tight_layout()
        path = os.path.join(LOG_DIR, "equity_chart.png")
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"\n  Gráfico guardado: {path}")
    except Exception as e:
        print(f"  Error gráfico: {e}")


if __name__ == "__main__":
    run_paper_trading()
