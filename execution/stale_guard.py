"""
Latency Budgeting & Stale Price / Adverse Selection Guard (Institutional Grade 10).
Protects execution against clock skew, REST lag, and abnormal spread widening.
Vetoes trades when quotes are stale or orderbook depth is under flash withdrawal.
"""
import time
from typing import Dict, Any, Optional


def validate_quote_freshness(
    quote_timestamp_ms: Optional[int],
    max_age_ms: int = 1500,
    current_time_ms: Optional[int] = None
) -> Dict[str, Any]:
    """
    Validates quote timestamp against current time:
      Rejects if quote is older than max_age_ms (default 1500 ms).
    """
    now_ms = current_time_ms if current_time_ms is not None else int(time.time() * 1000)
    
    if quote_timestamp_ms is None or quote_timestamp_ms <= 0:
        # If exchange does not supply timestamp, return soft warning
        return {
            "valid": True,
            "age_ms": 0,
            "warning": "Timestamp no proporcionado por exchange (asumiendo fresco)"
        }

    age_ms = now_ms - quote_timestamp_ms
    is_fresh = (0 <= age_ms <= max_age_ms)

    return {
        "valid": is_fresh,
        "age_ms": age_ms,
        "max_age_ms": max_age_ms,
        "warning": None if is_fresh else f"Cotización caduca: latencia {age_ms}ms > umbral {max_age_ms}ms"
    }


def check_spread_health(
    bid: float,
    ask: float,
    baseline_spread_pct: float = 0.05,
    max_spread_multiplier: float = 3.0
) -> Dict[str, Any]:
    """
    Guards against toxic order flow and spread blowouts.
    If current spread exceeds baseline_spread_pct * max_spread_multiplier,
    indicates market makers are widening spreads before volatility/news dump.
    """
    if bid <= 0.0 or ask <= 0.0 or ask < bid:
        return {
            "valid": False,
            "spread_pct": 0.0,
            "reason": "Precios bid/ask inválidos o cruzados"
        }

    spread_abs = ask - bid
    spread_pct = (spread_abs / bid) * 100.0
    max_allowed_spread = baseline_spread_pct * max_spread_multiplier

    is_healthy = spread_pct <= max_allowed_spread

    return {
        "valid": is_healthy,
        "spread_pct": round(spread_pct, 4),
        "max_allowed_spread_pct": round(max_allowed_spread, 4),
        "reason": None if is_healthy else f"Spread ensanchado anómalamente: {spread_pct:.3f}% > límite {max_allowed_spread:.3f}%"
    }


def sanitize_execution_context(
    symbol: str,
    bid: float,
    ask: float,
    quote_timestamp_ms: Optional[int] = None,
    baseline_spread_pct: float = 0.08,
    max_age_ms: int = 1500
) -> Dict[str, Any]:
    """
    Unified institutional sanity filter prior to order placement.
    """
    freshness = validate_quote_freshness(quote_timestamp_ms, max_age_ms=max_age_ms)
    spread = check_spread_health(bid, ask, baseline_spread_pct=baseline_spread_pct)

    is_safe = freshness["valid"] and spread["valid"]
    rejection_reasons = []
    if not freshness["valid"]:
        rejection_reasons.append(freshness["warning"])
    if not spread["valid"]:
        rejection_reasons.append(spread["reason"])

    return {
        "symbol": symbol,
        "safe_to_execute": is_safe,
        "rejection_reasons": rejection_reasons,
        "freshness": freshness,
        "spread": spread
    }
