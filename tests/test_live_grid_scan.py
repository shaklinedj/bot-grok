import ccxt
import time
import numpy as np

def calc_hurst_exponent(series, min_window=8, max_window=32):
    series = np.asarray(series, dtype=float)
    if len(series) < max_window:
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

def detect_horizontal_channel(candles):
    if len(candles) < 24:
        return None
    closes = np.array([c[4] for c in candles], dtype=float)
    highs = np.array([c[2] for c in candles], dtype=float)
    lows = np.array([c[3] for c in candles], dtype=float)
    curr_p = closes[-1]
    
    x = np.arange(len(closes))
    slope, _ = np.polyfit(x, closes, 1)
    slope_pct = (slope * len(closes)) / closes[0] * 100.0
    if abs(slope_pct) > 1.8:  # Más de 1.8% es tendencial diagonal
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
        "channel_pos": round(channel_pos, 2),
        "slope_pct": round(slope_pct, 2)
    }

ex = ccxt.binance({"enableRateLimit": True})
top_pairs = ["SOL/USDT", "DOGE/USDT", "BNB/USDT", "XRP/USDT", "NEAR/USDT", "ADA/USDT", "SUI/USDT"]

print("Probando escaneo de Malla Acotada en vivo:")
for sym in top_pairs:
    try:
        c = ex.fetch_ohlcv(sym, "15m", limit=36)
        closes = [x[4] for x in c]
        h = calc_hurst_exponent(closes)
        chan = detect_horizontal_channel(c)
        status = "RECHAZADA"
        if chan and h < 0.48:
            status = "CALIFICA PARA MALLA"
        print(f"{sym:<10} | Hurst H: {h} | Canal: {chan is not None} | {status}")
        if chan:
            print(f"   -> Ancho: {chan['width_pct']}% | Pos: {chan['channel_pos']*100:.0f}% | Soporte: {chan['support']} | Res: {chan['resistance']}")
    except Exception as e:
        print(f"{sym} error: {e}")
