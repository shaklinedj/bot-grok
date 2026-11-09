import numpy as np

def calc_hurst_exponent(series, min_window=8, max_window=32):
    """Calcula el exponente de Hurst usando Rescaled Range (R/S)."""
    series = np.asarray(series, dtype=float)
    N = len(series)
    if N < max_window:
        return 0.50
    
    returns = np.diff(series)
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

if __name__ == "__main__":
    # 1. Prueba oscilador puro (mean reverting)
    sine = [10.0 + np.sin(i * 0.5) * 0.5 for i in range(80)]
    h_sine = calc_hurst_exponent(sine)
    print(f"Hurst Onda Senoidal (Mean Reverting): {h_sine} (Esperado < 0.45)")

    # 2. Prueba tendencia vertical
    trend = [10.0 + i * 0.25 for i in range(80)]
    h_trend = calc_hurst_exponent(trend)
    print(f"Hurst Tendencia (Trending): {h_trend} (Esperado > 0.50)")
def detect_horizontal_channel(candles):
    """Detecta si un activo está en un canal horizontal acotado válido para Malla."""
    if len(candles) < 30:
        return None
    closes = np.array([c[4] for c in candles], dtype=float)
    highs = np.array([c[2] for c in candles], dtype=float)
    lows = np.array([c[3] for c in candles], dtype=float)
    curr_p = closes[-1]
    
    # 1. Pendiente lineal: Debe ser casi horizontal (|slope_pct| < 1.2%)
    x = np.arange(len(closes))
    slope, _ = np.polyfit(x, closes, 1)
    slope_pct = (slope * len(closes)) / closes[0] * 100.0
    if abs(slope_pct) > 1.2:
        return None
        
    # 2. Soporte y Resistencia por percentiles (95% y 5%)
    support = float(np.percentile(lows, 5))
    resistance = float(np.percentile(highs, 95))
    if support <= 0:
        return None
        
    channel_width_pct = (resistance - support) / support * 100.0
    # Ancho debe ser rentable (>1.2%) pero no excesivo (<4.0%)
    if not (1.2 <= channel_width_pct <= 4.0):
        return None
        
    # Precio actual debe estar dentro del canal
    if curr_p < support * 0.99 or curr_p > resistance * 1.01:
        return None
        
    midpoint = (support + resistance) / 2.0
    channel_pos = (curr_p - support) / (resistance - support)
    
    return {
        "support": round(support, 6),
        "resistance": round(resistance, 6),
        "midpoint": round(midpoint, 6),
        "width_pct": round(channel_width_pct, 2),
        "channel_pos": round(channel_pos, 2),
        "slope_pct": round(slope_pct, 2)
    }

# Prueba canal horizontal sintético
mock_channel_candles = []
for i in range(40):
    o = 10.0 + np.sin(i * 0.5) * 0.15
    c = 10.0 + np.sin((i + 1) * 0.5) * 0.15
    h = max(o, c) + 0.05
    l = min(o, c) - 0.05
    mock_channel_candles.append([1000 + i * 900, o, h, l, c, 1000])

chan = detect_horizontal_channel(mock_channel_candles)
print("Canal Detectado:", chan)
