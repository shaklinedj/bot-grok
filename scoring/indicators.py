"""
Indicadores técnicos matemáticos y algoritmos cuantitativos (EMA, RSI, ATR, Hurst y Canales).
Implementaciones exactas y determinísticas del sistema Swing & Grid.
"""
from typing import List, Optional, Dict
import numpy as np


def calc_ema(series: List[float], period: int) -> float:
    if not series:
        return 0.0
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


def calc_hurst_exponent(series: List[float], min_window: int = 8, max_window: int = 32) -> float:
    """
    Calcula el Exponente de Hurst (H) mediante análisis Rescaled Range (R/S).
    - H < 0.45: Serie anti-persistente (Reversión a la Media). Ideal para Malla Acotada.
    - H = 0.50: Paseo Aleatorio puro.
    - H > 0.50: Serie persistente (Tendencial). Prohibido para Malla.
    """
    arr = np.asarray(series, dtype=float)
    if len(arr) < max_window:
        return 0.50
    returns = np.diff(arr)
    if len(returns) < min_window:
        return 0.50
    window_sizes = [w for w in [8, 12, 16, 24, 32] if w <= len(returns)]
    if len(window_sizes) < 3:
        return 0.50
    rs_values = []
    for w in window_sizes:
        num_chunks = len(returns) // w
        rs_chunk_vals = []
        for i in range(num_chunks):
            chunk = returns[i*w:(i+1)*w]
            mean = np.mean(chunk)
            deviations = chunk - mean
            cum_dev = np.cumsum(deviations)
            r = np.max(cum_dev) - np.min(cum_dev)
            s = np.std(chunk, ddof=1)
            if s > 1e-8:
                rs_chunk_vals.append(r / s)
        if rs_chunk_vals:
            rs_values.append((w, np.mean(rs_chunk_vals)))
    if len(rs_values) < 2:
        return 0.50
    log_w = [np.log(w) for w, rs in rs_values]
    log_rs = [np.log(rs) for w, rs in rs_values]
    poly = np.polyfit(log_w, log_rs, 1)
    return round(float(np.clip(poly[0], 0.05, 0.95)), 3)


def detect_horizontal_channel(candles: List) -> Optional[Dict]:
    """
    Detecta si el par se encuentra confinado en un canal horizontal acotado.
    - Pendiente lineal plana (|slope_pct| < 1.8%).
    - Ancho del canal entre 1.0% y 5.0%.
    - Precio dentro del canal o cerca del soporte.
    """
    if len(candles) < 24:
        return None
    closes = np.array([c[4] for c in candles], dtype=float)
    highs = np.array([c[2] for c in candles], dtype=float)
    lows = np.array([c[3] for c in candles], dtype=float)
    curr_p = closes[-1]

    x = np.arange(len(closes))
    slope, _ = np.polyfit(x, closes, 1)
    slope_pct = (slope * len(closes)) / closes[0] * 100.0
    if abs(slope_pct) > 1.8:
        return None

    support = float(np.percentile(lows, 5))
    resistance = float(np.percentile(highs, 95))
    if support <= 0:
        return None

    channel_width_pct = (resistance - support) / support * 100.0
    if not (1.0 <= channel_width_pct <= 5.0):
        return None

    if curr_p < support * 0.985 or curr_p > resistance * 1.015:
        return None

    midpoint = (support + resistance) / 2.0
    channel_pos = (curr_p - support) / max((resistance - support), 1e-8)

    return {
        "support": round(support, 6),
        "resistance": round(resistance, 6),
        "midpoint": round(midpoint, 6),
        "width_pct": round(channel_width_pct, 2),
        "channel_pos": round(channel_pos, 3),
        "slope_pct": round(slope_pct, 2)
    }
