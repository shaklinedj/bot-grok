"""
Orderbook Depth & Dynamic Slippage / VWAP Impact Engine (Institutional Grade 10).
Analyzes Level 2 / L2 order book depth to compute true execution VWAP and market impact.
Prevents adverse selection and fee drag from consuming statistical edge.
"""
from typing import List, Dict, Any, Tuple


def calculate_orderbook_vwap(
    levels: List[List[float]],
    target_amount_quote: float,
    side: str = "BUY"
) -> Dict[str, Any]:
    """
    Computes exact execution VWAP across L2 orderbook levels:
      levels: list of [price, amount] (asks for BUY, bids for SELL)
      target_amount_quote: order size in quote currency (e.g. USDT)
    Returns:
      vwap: volume weighted average fill price
      slippage_pct: slippage vs top-of-book (best level)
      market_impact_bps: basis points of impact
      depth_exhaustion_pct: % of top levels consumed
      is_liquid: whether sufficient depth exists within 0.25% slippage
    """
    if not levels or target_amount_quote <= 0.0:
        return {
            "vwap": 0.0,
            "best_price": 0.0,
            "slippage_pct": 0.0,
            "market_impact_bps": 0.0,
            "filled_quote": 0.0,
            "is_liquid": False,
            "levels_swept": 0
        }

    best_price = float(levels[0][0])
    accum_quote = 0.0
    accum_base = 0.0
    levels_swept = 0

    for lvl in levels:
        price = float(lvl[0])
        qty = float(lvl[1])
        level_quote = price * qty
        levels_swept += 1

        needed_quote = target_amount_quote - accum_quote
        if level_quote >= needed_quote:
            # Last level needed
            partial_base = needed_quote / price
            accum_base += partial_base
            accum_quote += needed_quote
            break
        else:
            accum_base += qty
            accum_quote += level_quote

    if accum_base <= 0.0:
        return {
            "vwap": best_price,
            "best_price": best_price,
            "slippage_pct": 0.0,
            "market_impact_bps": 0.0,
            "filled_quote": 0.0,
            "is_liquid": False,
            "levels_swept": levels_swept
        }

    vwap = accum_quote / accum_base
    if side.upper() == "BUY":
        slippage_pct = ((vwap - best_price) / best_price) * 100.0
    else:
        slippage_pct = ((best_price - vwap) / best_price) * 100.0

    slippage_pct = max(0.0, slippage_pct)
    market_impact_bps = slippage_pct * 100.0

    # Institutional standard: liquid if slippage <= 0.20% (20 bps)
    is_liquid = (slippage_pct <= 0.20) and (accum_quote >= target_amount_quote * 0.999)

    return {
        "vwap": round(vwap, 6),
        "best_price": round(best_price, 6),
        "slippage_pct": round(slippage_pct, 4),
        "market_impact_bps": round(market_impact_bps, 2),
        "filled_quote": round(accum_quote, 4),
        "is_liquid": is_liquid,
        "levels_swept": levels_swept
    }


def evaluate_execution_route(
    symbol: str,
    target_capital: float,
    expected_gain_pct: float,
    orderbook: Dict[str, Any],
    side: str = "BUY"
) -> Dict[str, Any]:
    """
    Evaluates whether an order should be routed via direct aggressive fill (Taker)
    or staged passive liquidity (Maker TWAP).
    Rule: If slippage consumes > 25% of expected trade edge (alpha), enforce Maker TWAP.
    """
    levels = orderbook.get("asks" if side.upper() == "BUY" else "bids", [])
    vwap_res = calculate_orderbook_vwap(levels, target_capital, side=side)

    slip_pct = vwap_res["slippage_pct"]
    edge_eaten_ratio = (slip_pct / max(expected_gain_pct, 0.01))

    # Threshold: if slippage eats > 25% of target edge or slippage > 0.15%
    if edge_eaten_ratio >= 0.25 or slip_pct > 0.15:
        recommended_route = "MAKER_TWAP"
        reason = f"Deslizamiento ({slip_pct:.3f}%) consume {edge_eaten_ratio*100:.1f}% del alfa esperado"
    else:
        recommended_route = "DIRECT_TAKER"
        reason = f"Libro con profundidad óptima: Deslizamiento {slip_pct:.3f}% ({vwap_res['market_impact_bps']:.1f} bps)"

    return {
        "symbol": symbol,
        "recommended_route": recommended_route,
        "reason": reason,
        "vwap": vwap_res["vwap"],
        "slippage_pct": slip_pct,
        "market_impact_bps": vwap_res["market_impact_bps"],
        "levels_swept": vwap_res["levels_swept"],
        "is_liquid": vwap_res["is_liquid"]
    }
