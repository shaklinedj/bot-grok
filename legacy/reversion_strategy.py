"""Shared signal rules for the paper reversal agent and its historical backtest."""

DROP_MIN = -0.08
DROP_MAX = -0.03
RELATIVE_DROP_MIN = -0.07
RELATIVE_DROP_MAX = -0.015
BTC_MAX_DRAWDOWN = -0.04
MIN_RELATIVE_VOLUME = 1.2
MAX_RELATIVE_VOLUME = 3.0
MIN_QUOTE_VOLUME_24H = 10_000_000
MAX_REBOUND_CONFIRMATION = 0.015


def evaluate_rebound_signal(candles, btc_candles, index=-1, btc_index=-1):
    """Return signal metrics only for a liquid, moderate pullback with a confirmed turn."""
    if len(candles) < 25 or len(btc_candles) < 25:
        return None

    i = index if index >= 0 else len(candles) + index
    bi = btc_index if btc_index >= 0 else len(btc_candles) + btc_index
    if i < 24 or bi < 24 or i >= len(candles) or bi >= len(btc_candles):
        return None
    if candles[i, 0] != btc_candles[bi, 0]:
        return None
    if candles[i, 0] - candles[i - 24, 0] != 24 * 60 * 60 * 1000:
        return None
    if btc_candles[bi, 0] - btc_candles[bi - 24, 0] != 24 * 60 * 60 * 1000:
        return None

    close = candles[i, 4]
    open_price = candles[i, 1]
    low = candles[i, 3]
    previous_high = candles[i - 1, 2]
    previous_low = candles[i - 1, 3]
    volume_mean = candles[i - 20:i, 5].mean()
    quote_volume_24h = (candles[i - 23:i + 1, 4] * candles[i - 23:i + 1, 5]).sum()
    if min(close, candles[i - 24, 4], btc_candles[bi, 4], btc_candles[bi - 24, 4]) <= 0 or volume_mean <= 0:
        return None

    r24 = close / candles[i - 24, 4] - 1
    btc_r24 = btc_candles[bi, 4] / btc_candles[bi - 24, 4] - 1
    relative_drop = r24 - btc_r24
    volume_ratio = candles[i, 5] / volume_mean
    rebound_pct = close / previous_high - 1

    if not DROP_MIN <= r24 <= DROP_MAX:
        return None
    if not RELATIVE_DROP_MIN <= relative_drop <= RELATIVE_DROP_MAX:
        return None
    if btc_r24 < BTC_MAX_DRAWDOWN:
        return None
    if not MIN_RELATIVE_VOLUME <= volume_ratio <= MAX_RELATIVE_VOLUME:
        return None
    if quote_volume_24h < MIN_QUOTE_VOLUME_24H:
        return None
    if rebound_pct > MAX_REBOUND_CONFIRMATION:
        return None
    if close <= open_price or close <= previous_high or low <= previous_low:
        return None

    return {
        "r24": float(r24),
        "btc_r24": float(btc_r24),
        "idio": float(relative_drop),
        "volume_ratio": float(volume_ratio),
        "quote_volume_24h": float(quote_volume_24h),
        "rebound_pct": float(rebound_pct),
    }
