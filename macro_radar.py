"""
macro_radar.py — Arsenal Cuantitativo Multi-Factor y Motor de Régimen Macro (4h, 1d, 1h, 15m)
Implementación institucional para anticipación, previsión de tendencia y confluencia técnica.
"""

import time
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd


# ====================== ARSENAL DE INDICADORES MATEMÁTICOS ======================

def compute_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def compute_rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if not np.isnan(val) else 50.0


def compute_stoch_rsi(series: pd.Series, rsi_period: int = 14, stoch_period: int = 14) -> Tuple[float, float]:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/rsi_period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/rsi_period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    rsi_min = rsi.rolling(stoch_period).min()
    rsi_max = rsi.rolling(stoch_period).max()
    denom = (rsi_max - rsi_min).replace(0, np.nan)
    stoch_k = ((rsi - rsi_min) / denom) * 100
    stoch_d = stoch_k.rolling(3).mean()

    k_val = float(stoch_k.iloc[-1]) if not np.isnan(stoch_k.iloc[-1]) else 50.0
    d_val = float(stoch_d.iloc[-1]) if not np.isnan(stoch_d.iloc[-1]) else 50.0
    return round(k_val, 1), round(d_val, 1)


def compute_adx(df: pd.DataFrame, period: int = 14) -> Tuple[float, float, float, float]:
    high, low, close = df["high"], df["low"], df["close"]
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

    adx_val = float(adx.iloc[-1]) if not np.isnan(adx.iloc[-1]) else 20.0
    pdi_val = float(plus_di.iloc[-1]) if not np.isnan(plus_di.iloc[-1]) else 20.0
    mdi_val = float(minus_di.iloc[-1]) if not np.isnan(minus_di.iloc[-1]) else 20.0
    atr_val = float(atr.iloc[-1]) if not np.isnan(atr.iloc[-1]) else 0.0

    return round(adx_val, 1), round(pdi_val, 1), round(mdi_val, 1), atr_val


def compute_obv_slope(df: pd.DataFrame, period: int = 10) -> float:
    """Mide la pendiente del On-Balance Volume para detectar acumulación de ballenas."""
    close = df["close"]
    volume = df["volume"]
    obv = (np.sign(close.diff()) * volume).fillna(0).cumsum()
    if len(obv) < period:
        return 0.0
    x = np.arange(period)
    y = obv.iloc[-period:].values
    denom = np.sum((x - np.mean(x)) ** 2)
    if denom == 0:
        return 0.0
    slope = np.sum((x - np.mean(x)) * (y - np.mean(y))) / denom
    # Normalizar pendiente respecto al volumen medio
    mean_vol = volume.iloc[-period:].mean()
    norm_slope = slope / (mean_vol if mean_vol > 0 else 1.0)
    return round(float(norm_slope), 3)


def compute_kaufman_efficiency_ratio(series: pd.Series, period: int = 14) -> float:
    if len(series) < period + 1:
        return 0.50
    change = abs(series.iloc[-1] - series.iloc[-period])
    volatility = series.diff().abs().iloc[-period:].sum()
    if volatility <= 0 or np.isnan(volatility):
        return 0.0
    ker = change / volatility
    return round(float(np.clip(ker, 0.0, 1.0)), 3)


def compute_ttm_squeeze(df: pd.DataFrame) -> Dict:
    """
    Squeeze de Carter: Bollinger Bands (20, 2.0) vs Keltner Channels (20, 1.5 ATR).
    Ratio = BB_Width / KC_Width. Ratio <= 1.0 indica compresión extrema previa a explosión.
    """
    close = df["close"]
    high = df["high"]
    low = df["low"]
    n = len(close)
    if n < 20:
        return {"sq_ratio": 1.0, "is_coiling": False, "squeeze_state": "NEUTRAL"}

    std20 = close.rolling(20).std()
    bb_width = 4.0 * std20
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()
    kc_width = 3.0 * atr14

    last_bb = float(bb_width.iloc[-1]) if not np.isnan(bb_width.iloc[-1]) else 1.0
    last_kc = float(kc_width.iloc[-1]) if not np.isnan(kc_width.iloc[-1]) and float(kc_width.iloc[-1]) > 0 else 1.0
    ratio = last_bb / last_kc if last_kc > 0 else 1.0

    if ratio <= 0.85:
        state = "EXTREME_COIL"
    elif ratio <= 1.02:
        state = "COILING"
    elif ratio > 1.25:
        state = "EXPANDING"
    else:
        state = "TRANSITION"

    return {
        "sq_ratio": round(ratio, 2),
        "is_coiling": ratio <= 1.05,
        "squeeze_state": state
    }


def compute_pid_dynamics(df: pd.DataFrame) -> Dict:
    """
    Física de derivadas de precio:
    v(t) = velocidad (1ra derivada)
    a(t) = aceleración (2da derivada) -> Exigimos aceleración positiva a(t) > 0 para prever el despegue.
    """
    close = df["close"]
    if len(close) < 5:
        return {"v": 0.0, "a": 0.0, "acc_positive": False}
    v = close.diff()
    a = v.diff()
    v_last = float(v.iloc[-1]) if not np.isnan(v.iloc[-1]) else 0.0
    a_last = float(a.iloc[-1]) if not np.isnan(a.iloc[-1]) else 0.0
    return {
        "v": round(v_last, 6),
        "a": round(a_last, 6),
        "acc_positive": a_last > 0
    }


# ====================== MOTOR DE RÉGIMEN MACRO (4h y 1d) ======================

class MacroRegimeEngine:
    """
    Analizador Macro Multi-Timeframe.
    Se actualiza cada 60 segundos para no saturar las cuotas de red de Binance.
    Examina BTC y altcoins candidatas en 4h y 1d para dictar la dirección estratégica de fondo.
    """

    def __init__(self, exchange_client):
        self.exchange = exchange_client
        self.last_macro_update = 0.0
        self.macro_interval_seconds = 60.0  # Análisis macro cada 1 minuto
        self.btc_macro_state: Dict = {
            "regime": "NEUTRAL",
            "trend_4h": "CHOP",
            "price": 0.0,
            "ema50_4h": 0.0,
            "ema200_4h": 0.0,
            "adx_4h": 0.0,
            "change_24h": 0.0,
            "is_risk_off": False,
            "summary": "Iniciando análisis macro..."
        }
        self.coin_macro_cache: Dict[str, Dict] = {}

    def is_update_due(self) -> bool:
        return (time.time() - self.last_macro_update) >= self.macro_interval_seconds

    def update_btc_macro(self) -> Dict:
        """Examina Bitcoin en 4h y 1d para calibrar el semáforo institucional del mercado completo."""
        try:
            ohlcv_4h = self.exchange.fetch_ohlcv("BTC/USDT", "4h", limit=250)
            if not ohlcv_4h or len(ohlcv_4h) < 30:
                return self.btc_macro_state

            df_4h = pd.DataFrame(ohlcv_4h, columns=["ts", "open", "high", "low", "close", "volume"])
            close = df_4h["close"]
            current_p = float(close.iloc[-1])
            ema20 = float(compute_ema(close, 20).iloc[-1])
            ema50 = float(compute_ema(close, 50).iloc[-1])
            ema200 = float(compute_ema(close, 200).iloc[-1]) if len(close) >= 200 else float(compute_ema(close, 50).iloc[-1])
            adx_4h, pdi, mdi, _ = compute_adx(df_4h, 14)

            # Cambio últimas 24h (6 velas de 4h)
            chg_24h = ((current_p / float(close.iloc[-7])) - 1) * 100 if len(close) >= 7 else 0.0

            # Detección de Régimen Institucional:
            # 1. EXPANSION ALCISTA: Precio > EMA50 > EMA200 y PDI > MDI
            # 2. PULLBACK SALUDABLE: Precio retesteando EMA50 pero con tendencia alcista previa
            # 3. CHOP/RANGO: ADX < 20 o medias cruzadas planas
            # 4. RIESGO/BAJISTA: Precio bajo EMA50 y EMA200 con MDI > PDI
            if current_p >= ema50 and ema50 >= ema200 and adx_4h >= 22.0:
                regime = "BULLISH_EXPANSION"
                risk_off = False
                summary = f"BTC en expansion alcista macro 4h (P=${current_p:.0f} > EMA50=${ema50:.0f} > EMA200=${ema200:.0f} | ADX: {adx_4h})"
            elif current_p >= ema50 * 0.985 and pdi >= mdi:
                regime = "HEALTHY_PULLBACK"
                risk_off = False
                summary = f"BTC en pullback controlado en 4h sobre soporte EMA50 (${ema50:.0f})"
            elif adx_4h < 20.0 or abs(ema20 - ema50) / ema50 < 0.005:
                regime = "CHOPPY_RANGE"
                risk_off = False
                summary = f"BTC en compresion/rango lateral sucio en 4h (ADX: {adx_4h:.1f})"
            elif current_p < ema50 and mdi > pdi:
                regime = "BEARISH_CORRECTION"
                risk_off = (chg_24h <= -3.0) or (current_p < ema200 * 0.98)
                summary = f"BTC en correccion bajista en 4h (P=${current_p:.0f} < EMA50=${ema50:.0f})"
            else:
                regime = "NEUTRAL"
                risk_off = False
                summary = f"BTC en transicion neutral (P=${current_p:.0f})"

            self.btc_macro_state = {
                "regime": regime,
                "price": current_p,
                "ema50_4h": ema50,
                "ema200_4h": ema200,
                "adx_4h": adx_4h,
                "change_24h": round(chg_24h, 2),
                "is_risk_off": risk_off,
                "summary": summary
            }
            return self.btc_macro_state
        except Exception as e:
            print(f"  [Error Macro BTC] {e}", flush=True)
            return self.btc_macro_state

    def analyze_coin_macro(self, symbol: str) -> Dict:
        """
        Analiza una altcoin en 4h:
        - Triple EMA (20/50/200)
        - Escudo Anti-Cuchillo Cayendo (Anti-Knife Shield): 3 velas rojas consecutivas con volumen creciente
        - Estructura de soportes y resistencias 4h
        """
        now = time.time()
        cached = self.coin_macro_cache.get(symbol)
        if cached and (now - cached.get("cached_at", 0)) < 90.0:
            return cached

        try:
            ohlcv_4h = self.exchange.fetch_ohlcv(symbol, "4h", limit=50)
            if not ohlcv_4h or len(ohlcv_4h) < 25:
                return {"macro_bias": "NEUTRAL", "anti_knife_safe": True, "support_4h": 0.0, "resistance_4h": 0.0}

            df = pd.DataFrame(ohlcv_4h, columns=["ts", "open", "high", "low", "close", "volume"])
            close = df["close"]
            high = df["high"]
            low = df["low"]
            vol = df["volume"]
            current_p = float(close.iloc[-1])

            ema20 = float(compute_ema(close, 20).iloc[-1])
            ema50 = float(compute_ema(close, 50).iloc[-1])
            adx_4h, pdi_4h, mdi_4h, _ = compute_adx(df, 14)

            # ESCUDO ANTI-CUCHILLO (Anti-Knife Shield - crypto-quant-mastery):
            # Si las últimas 3 velas de 4h son rojas haciendo mínimos decrecientes con volumen en expansión,
            # el activo está en caída libre. PROHIBIDO COMPRAR LONG.
            last_3_red = (close.iloc[-1] < df["open"].iloc[-1]) and (close.iloc[-2] < df["open"].iloc[-2]) and (close.iloc[-3] < df["open"].iloc[-3])
            lower_lows = (low.iloc[-1] < low.iloc[-2]) and (low.iloc[-2] < low.iloc[-3])
            vol_expanding = vol.iloc[-1] >= vol.iloc[-2]
            knife_detected = bool(last_3_red and lower_lows and vol_expanding)

            # Soportes y Resistencias 4h (Pivotes de Swing)
            support_4h = float(low.iloc[-15:].min())
            resistance_4h = float(high.iloc[-15:].max())

            # Sesgo Macro:
            # - ALCISTA: Precio por encima de EMA50 y PDI > MDI
            # - EN RETESTEO: Precio cerca de EMA50 (a menos de 2% de la media)
            # - BAJISTA: Precio claramente bajo EMA50 con momentum negativo
            if current_p >= ema50 and pdi_4h >= mdi_4h:
                macro_bias = "BULLISH"
            elif abs(current_p - ema50) / ema50 <= 0.025:
                macro_bias = "RETEST_SUPPORT"
            else:
                macro_bias = "BEARISH"

            res = {
                "macro_bias": macro_bias,
                "anti_knife_safe": not knife_detected,
                "ema20_4h": round(ema20, 5),
                "ema50_4h": round(ema50, 5),
                "adx_4h": adx_4h,
                "support_4h": support_4h,
                "resistance_4h": resistance_4h,
                "cached_at": now
            }
            self.coin_macro_cache[symbol] = res
            return res
        except Exception:
            return {"macro_bias": "NEUTRAL", "anti_knife_safe": True, "support_4h": 0.0, "resistance_4h": 0.0}

    def run_macro_cycle(self, candidate_symbols: List[str]):
        """Ejecuta el ciclo de actualización macro cada 60s."""
        self.update_btc_macro()
        for sym in candidate_symbols[:15]:
            self.analyze_coin_macro(sym)
        self.last_macro_update = time.time()


# ====================== ARSENAL MULTI-FACTOR CONFLUENCE ======================

def evaluate_multi_factor_arsenal(
    symbol: str,
    df_15m: pd.DataFrame,
    df_1h: pd.DataFrame,
    macro_info: Dict,
    btc_macro: Dict,
    volume_m: float
) -> Dict:
    """
    Evalúa el ARSENAL COMPLETO DE INDICADORES (6 Pilares Cuantitativos):
    1. Pilar Macro 4h (Tendencia de fondo + Escudo Anti-Cuchillo)
    2. Pilar Volatilidad / Squeeze 15m (Compresión TTM previa a explosión)
    3. Pilar Volumen y Flujo Institucional (Volume Surge + OBV Slope)
    4. Pilar Osciladores y Momentum (RSI 14 + StochRSI)
    5. Pilar Dinámica PID (Velocidad, Aceleración positiva a > 0)
    6. Pilar Eficiencia Kaufman (KER >= 0.22)
    """
    if len(df_15m) < 20 or len(df_1h) < 20:
        return {"recommendation": "skip", "score": 0.0, "reason": "Datos insuficientes"}

    close_15m = df_15m["close"]
    close_1h = df_1h["close"]
    current_price = float(close_15m.iloc[-1])

    # 1. PILAR MACRO 4h:
    macro_bias = macro_info.get("macro_bias", "NEUTRAL")
    anti_knife_safe = macro_info.get("anti_knife_safe", True)
    if not anti_knife_safe:
        return {
            "score": -100.0,
            "recommendation": "skip",
            "reason": "VETO ANTI-CUCHILLO: Moneda en caida libre 4h (3 velas rojas expansivas)",
            "p_win": 0.15,
            "current_price": current_price,
            "limit_buy_price": current_price,
            "limit_order_price": current_price,
            "forward_target": current_price,
            "rr_ratio": 0.0,
            "macro_bias": macro_bias,
            "anti_knife_safe": anti_knife_safe,
            "adx_1h": 0.0,
            "rsi_15m": 50.0,
            "stoch_k": 50.0,
            "stoch_d": 50.0,
            "sq_ratio": 1.0,
            "squeeze_state": "NEUTRAL",
            "obv_slope": 0.0,
            "vol_surge": 1.0,
            "ker": 0.0,
            "pid_acc": 0.0,
            "atr_pct": 0.0,
            "atr_value": 0.0,
            "dist_ema20": 0.0,
            "features": {
                "macro_bias": 0.0,
                "adx": 0.0,
                "rsi": 50.0,
                "stoch_k": 50.0,
                "sq_ratio": 1.0,
                "obv_slope": 0.0,
                "vol_surge": 1.0,
                "ker": 0.0,
                "pid_acc": 0.0,
                "dist_ema20": 0.0,
                "atr_pct": 0.0,
                "score": -100.0,
                "rr_ratio": 0.0
            }
        }

    # 2. PILAR MOMENTUM & OSCILADORES:
    rsi_15m = compute_rsi(close_15m, 14)
    stoch_k, stoch_d = compute_stoch_rsi(close_15m, 14, 14)
    adx_1h, pdi_1h, mdi_1h, atr_val_1h = compute_adx(df_1h, 14)
    atr_pct_1h = (atr_val_1h / current_price) * 100 if current_price > 0 else 1.0

    # 3. PILAR VOLATILIDAD & SQUEEZE:
    squeeze = compute_ttm_squeeze(df_15m)
    sq_ratio = squeeze["sq_ratio"]

    # 4. PILAR VOLUMEN & FLUJO (ORDER FLOW):
    obv_slope = compute_obv_slope(df_15m, 10)
    vol_mean_20 = float(df_15m["volume"].rolling(20).mean().iloc[-1])
    vol_last = float(df_15m["volume"].iloc[-1])
    vol_surge_ratio = (vol_last / vol_mean_20) if vol_mean_20 > 0 else 1.0

    # 5. PILAR DINÁMICA PID & EQUILIBRIO:
    ema20_15m = float(compute_ema(close_15m, 20).iloc[-1])
    dist_to_ema20 = ((current_price / ema20_15m) - 1) * 100 if ema20_15m > 0 else 0.0
    pid = compute_pid_dynamics(df_15m)

    # 6. PILAR EFICIENCIA DE KAUFMAN (KER):
    ker_val = compute_kaufman_efficiency_ratio(close_15m, 14)

    # ================= CÁLCULO DE CONFLUENCIA PONDERADA (0 a 100) =================
    score = 0.0

    # A. Confluencia Macro 4h (hasta +25 pts)
    if macro_bias == "BULLISH":
        score += 25.0
    elif macro_bias == "RETEST_SUPPORT":
        score += 20.0
    else:
        score -= 20.0  # Penalización severa por operar contra la marea macro 4h

    # B. Confluencia Squeeze de Volatilidad & Acumulación Silenciosa (hasta +25 pts)
    # DETECTOR DE ACUMULACIÓN SILENCIOSA: El resorte está comprimido y el OBV sube mientras el precio está plano
    if squeeze["is_coiling"] and abs(dist_to_ema20) <= 0.90 and obv_slope > 0.02:
        score += 25.0  # Ballena acumulando en silencio antes del despegue
    elif squeeze["is_coiling"]:
        score += 18.0  # El resorte está comprimido, anticipa explosión
    elif sq_ratio <= 1.15:
        score += 8.0

    # C. Confluencia Flujo y Volumen (hasta +20 pts)
    if obv_slope > 0.05 and vol_surge_ratio >= 1.2:
        score += 20.0  # Acumulación clara de volumen
    elif obv_slope > 0:
        score += 10.0

    # D. Confluencia Osciladores RSI/StochRSI & VETO ANTI-FOMO (hasta +15 pts)
    if 36.0 <= rsi_15m <= 58.0 and stoch_k > stoch_d:
        score += 15.0  # Zona dulce de despegue con giro alcista
    elif rsi_15m > 68.0 or dist_to_ema20 > 1.80:
        score -= 35.0  # VETO ANTI-FOMO: Vela ya despegó, no perseguir techos

    # E. Confluencia PID & Aceleración (hasta +10 pts)
    if pid["acc_positive"] and -2.5 <= dist_to_ema20 <= 1.20:
        score += 10.0  # En soporte/pullback con aceleración positiva iniciando

    # F. Confluencia Eficiencia de Mercado & Canal Malla Lateral (hasta +15 pts)
    if ker_val >= 0.30:
        score += 10.0  # Tendencia limpia
    elif ker_val < 0.12 and not squeeze["is_coiling"]:
        # ESTRATEGIA DE MALLA LATERAL: Si está en rango y cerca del piso del canal
        if dist_to_ema20 < -0.30 and rsi_15m <= 48.0:
            score += 15.0  # Rebote predecible en piso de canal lateral (Malla Maker)
        else:
            score -= 15.0

    # G. Fuerza Alfa Relativa vs BTC
    if btc_macro.get("regime") == "BULLISH_EXPANSION":
        score += 5.0
    elif btc_macro.get("is_risk_off", False):
        if obv_slope > 0.05 and vol_surge_ratio >= 1.2:
            score += 15.0  # Moneda con Fuerza Alfa independiente desacoplada de BTC
        else:
            score -= 35.0  # BTC en caída, congelar compras normales

    # ================= EVALUACIÓN SIMÉTRICA LONG VS SHORT =================
    # Proyección Predictiva LONG (Tight Maker Pasivo: -0.35% a -0.65% de micro-retroceso):
    maker_offset_long = max(0.0035, min(0.0065, (current_price - ema20_15m) / current_price)) if (ema20_15m > 0 and ema20_15m < current_price) else 0.0040
    pullback_long = current_price * (1 - maker_offset_long)
    limit_buy_price = round(pullback_long, 5)
    res_4h = macro_info.get("resistance_4h", current_price * 1.04)
    target_gain = max(atr_val_1h * 1.60, limit_buy_price * 0.035)
    projected_target_long = min(res_4h, limit_buy_price + target_gain)
    expected_sl_long = limit_buy_price - (atr_val_1h * 1.10)
    risk_long = limit_buy_price - expected_sl_long
    reward_long = projected_target_long - limit_buy_price
    rr_long = round(reward_long / risk_long, 2) if risk_long > 0 else 1.0

    # Proyección Predictiva SHORT (Tight Maker Pasivo: +0.35% a +0.65% de micro-rebote):
    maker_offset_short = max(0.0035, min(0.0065, (ema20_15m - current_price) / current_price)) if (ema20_15m > 0 and ema20_15m > current_price) else 0.0040
    pullback_short = current_price * (1 + maker_offset_short)
    limit_short_price = round(pullback_short, 5)
    sup_4h = macro_info.get("support_4h", current_price * 0.96)
    target_drop = max(atr_val_1h * 1.60, limit_short_price * 0.035)
    projected_target_short = max(sup_4h, limit_short_price - target_drop)
    expected_sl_short = limit_short_price + (atr_val_1h * 1.10)
    risk_short = expected_sl_short - limit_short_price
    reward_short = limit_short_price - projected_target_short
    rr_short = round(reward_short / risk_short, 2) if risk_short > 0 else 1.0

    # Score SHORT: penaliza compras y premia debilidad macro / rechazo en resistencia
    score_short = 0.0
    if macro_bias == "BEARISH":
        score_short += 25.0
    elif macro_bias == "RETEST_RESISTANCE":
        score_short += 20.0
    
    if obv_slope < -0.05 and vol_surge_ratio >= 1.2:
        score_short += 20.0
    elif obv_slope < 0:
        score_short += 10.0
    
    if 56.0 <= rsi_15m <= 75.0 and stoch_k < stoch_d:
        score_short += 15.0  # Sobrecomprado girando hacia abajo
    
    if not pid["acc_positive"] and -0.80 <= dist_to_ema20 <= 3.0:
        score_short += 10.0  # Cerca de resistencia perdiendo aceleración
        
    if ker_val >= 0.25:
        score_short += 10.0
    elif ker_val < 0.12 and not squeeze["is_coiling"]:
        score_short -= 15.0

    if btc_macro.get("is_risk_off", False):
        score_short += 15.0  # BTC cayendo favorece shorts en alts débiles

    is_approved_long = (
        (score >= 45.0)
        and (ker_val >= 0.12 or squeeze["is_coiling"])
        and (rsi_15m <= 66.0)
        and (-3.5 <= dist_to_ema20 <= 1.80)
        and (rr_long >= 0.85)
        and anti_knife_safe
        and not btc_macro.get("is_risk_off", False)
    )

    is_approved_short = (
        (score_short >= 45.0)
        and (ker_val >= 0.12 or squeeze["is_coiling"])
        and (rsi_15m >= 38.0)
        and (-1.80 <= dist_to_ema20 <= 3.5)
        and (rr_short >= 0.85)
    )

    if is_approved_long and score >= score_short:
        recommendation = "long"
        final_score = score
        forward_target = projected_target_long
        limit_order_price = limit_buy_price
        final_rr = rr_long
    elif is_approved_short and score_short > score:
        recommendation = "short"
        final_score = score_short
        forward_target = projected_target_short
        limit_order_price = limit_short_price
        final_rr = rr_short
    else:
        recommendation = "skip"
        final_score = max(score, score_short)
        forward_target = projected_target_long
        limit_order_price = limit_buy_price
        final_rr = max(rr_long, rr_short)

    return {
        "score": round(final_score, 1),
        "recommendation": recommendation,
        "current_price": current_price,
        "limit_buy_price": limit_order_price,
        "limit_order_price": limit_order_price,
        "forward_target": round(forward_target, 5),
        "rr_ratio": final_rr,
        "macro_bias": macro_bias,
        "anti_knife_safe": anti_knife_safe,
        "adx_1h": adx_1h,
        "rsi_15m": rsi_15m,
        "stoch_k": stoch_k,
        "stoch_d": stoch_d,
        "sq_ratio": sq_ratio,
        "squeeze_state": squeeze["squeeze_state"],
        "obv_slope": obv_slope,
        "vol_surge": round(vol_surge_ratio, 2),
        "ker": ker_val,
        "pid_acc": pid["a"],
        "atr_pct": round(atr_pct_1h, 2),
        "atr_value": atr_val_1h,
        "dist_ema20": round(dist_to_ema20, 2),
        "features": {
            "macro_bias": 1.0 if macro_bias == "BULLISH" else 0.0,
            "adx": adx_1h,
            "rsi": rsi_15m,
            "stoch_k": stoch_k,
            "sq_ratio": sq_ratio,
            "obv_slope": obv_slope,
            "vol_surge": vol_surge_ratio,
            "ker": ker_val,
            "pid_acc": pid["a"],
            "dist_ema20": dist_to_ema20,
            "atr_pct": atr_pct_1h,
            "score": final_score,
            "rr_ratio": final_rr
        }
    }


# ====================== MICROESTRUCTURA DE LIBRO DE ÓRDENES (OBI DEPTH 10) ======================

def fetch_order_book_microstructure(exchange, symbol: str, depth: int = 10) -> Dict:
    """
    Descarga el libro de órdenes en profundidad (L2 Depth 10) y evalúa:
    1. OBI (Order Book Imbalance) = (Bids - Asks) / (Bids + Asks) en [-1.0, 1.0]
    2. Spread Porcentual = (BestAsk - BestBid) / BestBid * 100
    3. Detección de Absorción Pasiva Institucional
    """
    try:
        ob = exchange.fetch_order_book(symbol, limit=depth)
        bids = ob.get("bids", [])[:depth]
        asks = ob.get("asks", [])[:depth]
        if not bids or not asks:
            return {"obi": 0.0, "spread_pct": 0.03, "is_safe": True, "reason": "LOB sin datos"}

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        spread_pct = ((best_ask - best_bid) / best_bid) * 100 if best_bid > 0 else 0.0

        bid_vol = sum(float(b[1]) for b in bids)
        ask_vol = sum(float(a[1]) for a in asks)
        total_vol = bid_vol + ask_vol

        obi = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0.0

        # Reglas Cuantitativas Institucionales para Cripto Spot:
        # - Spread <= 0.35% (35 bps, normal para altcoins en spot)
        # - OBI >= -0.35 (evita comprar bajo muros pesados de venta)
        is_safe = (spread_pct <= 0.35) and (obi >= -0.35)
        reason = "LOB Balanceado"
        if spread_pct > 0.35:
            reason = f"VETO MICROESTRUCTURA: Spread muy amplio ({spread_pct:.3f}% > 0.35%)"
        elif obi < -0.35:
            reason = f"VETO MICROESTRUCTURA: Muro de venta pesado en contra (OBI: {obi:+.2f} < -0.35)"
        elif obi > 0.20:
            reason = f"ABSORCION INSTITUCIONAL: Fuerte soporte de compra pasiva (OBI: {obi:+.2f})"

        return {
            "obi": round(float(obi), 3),
            "spread_pct": round(float(spread_pct), 4),
            "bid_vol": round(bid_vol, 2),
            "ask_vol": round(ask_vol, 2),
            "is_safe": is_safe,
            "reason": reason
        }
    except Exception as e:
        return {"obi": 0.0, "spread_pct": 0.03, "is_safe": True, "reason": f"LOB OK (Fallback)"}

