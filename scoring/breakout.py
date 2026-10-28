"""
Módulo de Detección de Rupturas (Breakouts) y Momentum Ignition en temporalidad 15m.
"""
from typing import Dict, List, Optional, Any

from config import DEFAULT_SETTINGS, RS_MIN_THRESHOLD
from scoring.indicators import calc_ema, calc_rsi, calc_atr
from scoring.market_scanner import fetch_ohlcv_cached


def analyze_breakout_15m(symbol: str, btc_ctx: Dict[str, Any], settings: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    FASE 2 + 3: Analiza un candidato en 15m buscando ruptura confirmada con volumen.
    Solo dispara si hay confirmación de que la moneda ya está subiendo.
    """
    cfg = settings or DEFAULT_SETTINGS
    stop_mult = cfg.get("stop_atr_mult", 1.2)
    target_mult = cfg.get("target_atr_mult", 3.0)
    vol_min = cfg.get("vol_spike_min", 1.2)
    min_score_target = cfg.get("min_score", 70.0)

    c_15m = fetch_ohlcv_cached(symbol, "15m", limit=40)
    c_1h = fetch_ohlcv_cached(symbol, "1h", limit=30)
    c_5m = fetch_ohlcv_cached(symbol, "5m", limit=30)

    if len(c_15m) < 20 or len(c_1h) < 15:
        return None

    closes_15m = [c[4] for c in c_15m]
    highs_15m = [c[2] for c in c_15m]
    lows_15m = [c[3] for c in c_15m]
    vols_15m = [c[5] for c in c_15m]
    closes_1h = [c[4] for c in c_1h]
    curr_p = closes_15m[-1]

    if curr_p <= 0:
        return None

    btc_regime = btc_ctx.get("regime", "NEUTRAL_TRANSITION")
    # Candado Macro BTC: Si BTC está en corrección brusca (DUMP), prohibido comprar altcoins
    if btc_regime == "BEARISH_DUMP":
        return {
            "symbol": symbol, "price": curr_p, "breakout": False, "score": 0.0,
            "vol_spike": 0.0, "is_green": False, "double_green": False,
            "rsi_15m": 50.0, "rsi_1h": 50.0, "trend_1h": False, "atr_15m_pct": 1.0,
            "rs_vs_btc": 0.0, "coin_chg_1h": 0.0, "is_falling_knife": False,
            "is_overextended": False, "has_healthy_base": False, "rsi_5m": 50.0,
            "stop_pct": 1.5, "target_pct": 3.3, "stop_price": round(curr_p * 0.985, 6),
            "target_price": round(curr_p * 1.033, 6), "rr_ratio": 2.2,
            "trigger_ready": False, "status": "🚫 BLOQUEO: BTC en Corrección"
        }

    # Si BTC está en compresión lateral (chop), se exige Score A+ (86+)
    if btc_regime == "CHOP_COMPRESSION":
        min_score_target = max(min_score_target, 86.0)

    # --- Microestructura 5m (para evitar comprar en techos de agotamiento) ---
    if c_5m and len(c_5m) >= 15:
        closes_5m = [c[4] for c in c_5m]
        rsi_5m = calc_rsi(closes_5m, 14)
        ema20_5m = calc_ema(closes_5m, 20)
        dev_5m_ema20 = (curr_p - ema20_5m) / ema20_5m * 100.0
    else:
        rsi_5m = 50.0
        dev_5m_ema20 = 0.0

    # --- Indicadores 15m ---
    atr_15m = calc_atr(c_15m, 14)
    atr_pct_15m = (atr_15m / curr_p * 100.0) if curr_p > 0 else 1.0
    rsi_15m = calc_rsi(closes_15m, 14)
    ema9_15m = calc_ema(closes_15m, 9)
    ema20_15m = calc_ema(closes_15m, 20)
    dev_15m_ema20 = (curr_p - ema20_15m) / ema20_15m * 100.0

    # Conteo de velas verdes consecutivas en 15m
    consecutive_greens = 0
    for c in reversed(c_15m[-6:]):
        if c[4] > c[1]:
            consecutive_greens += 1
        else:
            break

    # Filtro de Sobreextensión / Agotamiento (Anti-FOMO en el techo tardío)
    is_overextended = (
        rsi_15m >= 78.0
        or rsi_5m >= 80.0
        or (consecutive_greens >= 4 and rsi_15m >= 68.0)
        or (dev_15m_ema20 >= 3.8 and consecutive_greens >= 3)
    )

    # Micro-Base Saludable: precio consolidando cerca de la EMA20 sin estar en euforia
    has_healthy_base = (dev_15m_ema20 <= 2.0) and (38.0 <= rsi_5m <= 66.0) and (consecutive_greens <= 2)

    # --- Indicadores 1H (tendencia de fondo) ---
    ema20_1h = calc_ema(closes_1h, 20)
    trend_1h_bullish = curr_p > ema20_1h
    rsi_1h = calc_rsi(closes_1h, 14)

    # --- Micro-resistencia en 15m: Máximo de las últimas 8 velas (2 horas) ---
    recent_high = max(highs_15m[-9:-1]) if len(highs_15m) >= 9 else max(highs_15m[-5:-1])
    breakout_confirmed = curr_p > recent_high

    # --- Volumen Spike: Última vela 15m vs promedio de las últimas 20 ---
    avg_vol = sum(vols_15m[-20:]) / 20.0 if len(vols_15m) >= 20 else sum(vols_15m) / max(len(vols_15m), 1)
    vol_spike = (vols_15m[-1] / avg_vol) if avg_vol > 0 else 0.0

    # --- Vela actual verde y con cuerpo ---
    last_c = c_15m[-1]
    is_green = last_c[4] > last_c[1]
    body = abs(last_c[4] - last_c[1])
    full_range = last_c[2] - last_c[3]
    body_ratio = (body / full_range) if full_range > 0 else 0.0
    close_pos = ((last_c[4] - last_c[3]) / full_range) if full_range > 0 else 0.0

    # --- Momentum: Las últimas 2 velas de 15m son verdes ---
    prev_green = c_15m[-2][4] > c_15m[-2][1] if len(c_15m) >= 2 else False
    double_green = is_green and prev_green

    # --- Anti-Cuchillo: Las últimas 4 velas de 1H no deben ser todas rojas ---
    knife_count = sum(1 for c in c_1h[-4:] if c[4] < c[1])
    is_falling_knife = knife_count >= 4

    # --- Fuerza Relativa vs BTC (comparar cambio 1H de esta moneda vs BTC) ---
    if len(c_1h) >= 2:
        coin_chg_1h = (c_1h[-1][4] - c_1h[-2][4]) / c_1h[-2][4] * 100.0
    else:
        coin_chg_1h = 0.0
    rs_vs_btc = coin_chg_1h - btc_ctx.get("change_1h", 0.0)

    # --- DETECTOR DE IGNICIÓN DE MOMENTUM (arXiv:2602.11708 Trend-Following Engine) ---
    is_momentum_ignition = bool(
        is_green
        and vol_spike >= 2.0
        and full_range >= (1.20 * atr_15m)
        and body_ratio >= 0.55
        and close_pos >= 0.70
        and rs_vs_btc >= 0.8
        and not is_falling_knife
        and not is_overextended
    )

    # --- Parámetros de Trade Asimétricos con Piso Defensivo (1.20% min) y Techo (2.20% max) ---
    min_stop_pct = 0.0120  # Piso mínimo 1.20%: Erradica la muerte por micro-stops y ruido blanco
    max_stop_pct = 0.0220  # Techo máximo 2.20%: Preserva el capital ante cisnes negros
    raw_stop_dist = stop_mult * atr_15m
    stop_distance = max(curr_p * min_stop_pct, min(raw_stop_dist, curr_p * max_stop_pct))
    stop_pct = stop_distance / curr_p
    stop_price = round(curr_p - stop_distance, 6)

    # Target asimétrico:
    if is_momentum_ignition:
        target_distance = max(target_mult * atr_15m, stop_distance * 3.4)
    else:
        target_distance = max(target_mult * atr_15m, stop_distance * 2.2)
    target_pct = target_distance / curr_p
    target_price = round(curr_p + target_distance, 6)
    rr_ratio = round(target_pct / max(stop_pct, 0.001), 2)

    # =================== PUNTUACIÓN V2 ADAPTATIVA ===================
    score = 0.0

    # A. Ruptura de micro-resistencia en 15m (+30)
    if breakout_confirmed:
        score += 30.0

    # B. Volumen Spike en la vela actual (+20 si >= vol_min, +10 si >= 1.0x)
    if vol_spike >= vol_min:
        score += 20.0
    elif vol_spike >= 1.0:
        score += 10.0

    # C. Vela(s) verde(s) con cuerpo (+15 por doble verde, +8 por verde simple)
    if double_green and body_ratio >= 0.40:
        score += 15.0
    elif is_green and body_ratio >= 0.30:
        score += 8.0

    # D. RSI 15m en zona de impulso (40-65 es ideal) (+10)
    if 38.0 <= rsi_15m <= 68.0:
        score += 10.0

    # E. Tendencia 1H a favor (precio > EMA20 1H) (+15)
    if trend_1h_bullish:
        score += 15.0

    # F. Fuerza Relativa positiva vs BTC (+10 si es más fuerte que BTC)
    if rs_vs_btc >= RS_MIN_THRESHOLD:
        score += 10.0
    elif rs_vs_btc >= 0.5:
        score += 5.0

    # G. Micro-Base Saludable en 5m/15m (+15 por consolidar en soporte)
    if has_healthy_base:
        score += 15.0

    # H. Bonus Ignición de Momentum Institucional (+35 pts)
    if is_momentum_ignition:
        score += 35.0

    # Penalizaciones:
    if is_falling_knife:
        score -= 40.0
    if is_overextended:
        score -= 50.0
    elif rsi_15m > 68.0:
        score -= 15.0
    if rsi_1h > 75.0:
        score -= 15.0

    is_trigger_ready = (
        (score >= min_score_target or is_momentum_ignition)
        and (breakout_confirmed or is_momentum_ignition)
        and is_green
        and vol_spike >= 1.0
        and not is_falling_knife
        and not is_overextended
        and rr_ratio >= 2.0
    )

    if is_overextended:
        status_str = "⚠️ SOBREEXTENDIDO (Enfriando)"
    elif is_momentum_ignition and is_trigger_ready:
        status_str = f"🚀 IGNICIÓN MOMENTUM ({rr_ratio}R)"
    elif is_trigger_ready:
        status_str = "🟢 RUPTURA CONFIRMADA"
    elif breakout_confirmed and score >= 50:
        status_str = "🟡 RUPTURA SIN VOLUMEN"
    elif trend_1h_bullish:
        status_str = "🔵 TENDENCIA OK - SIN RUPTURA"
    else:
        status_str = "⚪ OBSERVANDO"

    return {
        "symbol": symbol,
        "price": curr_p,
        "breakout": breakout_confirmed,
        "vol_spike": round(vol_spike, 2),
        "is_green": is_green,
        "double_green": double_green,
        "rsi_15m": round(rsi_15m, 1),
        "rsi_1h": round(rsi_1h, 1),
        "trend_1h": trend_1h_bullish,
        "atr_15m_pct": round(atr_pct_15m, 2),
        "rs_vs_btc": round(rs_vs_btc, 2),
        "coin_chg_1h": round(coin_chg_1h, 2),
        "is_falling_knife": is_falling_knife,
        "is_overextended": is_overextended,
        "has_healthy_base": has_healthy_base,
        "rsi_5m": round(rsi_5m, 1),
        "stop_pct": round(stop_pct * 100.0, 2),
        "target_pct": round(target_pct * 100.0, 2),
        "stop_price": stop_price,
        "target_price": target_price,
        "rr_ratio": rr_ratio,
        "score": round(score, 1),
        "trigger_ready": is_trigger_ready,
        "is_momentum_ignition": is_momentum_ignition,
        "status": status_str
    }
