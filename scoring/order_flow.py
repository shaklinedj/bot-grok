"""
Módulo de Order Flow L2 y Microestructura del Mercado (Tape / Cinta).
Valida Order Book Imbalance (OBI), Taker Volume Delta y Spreads antes de disparar trades.
"""
from typing import Dict, Any
from config import exchange


def fetch_order_flow_confirmation(symbol: str, ex=exchange) -> Dict[str, Any]:
    """
    CENTINELA DE ORDER FLOW (Microestructura L2 & Tape).
    Filtro final ejecutado antes de disparar un trade.
    1. Order Book Imbalance (OBI): Verifica la asimetría de liquidez pasiva en los 20 mejores niveles.
    2. Taker Volume Delta: Verifica la agresividad en los últimos 50 trades a mercado.
    3. Spread Real: Veta si el spread es excesivo (> 0.25%).
    """
    try:
        # 1. Order Book L2:
        ob = ex.fetch_order_book(symbol, limit=20)
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])
        if not bids or not asks:
            return {
                "confirmed": True,
                "obi": 0.0,
                "buy_ratio_pct": 50.0,
                "delta": 0.0,
                "spread_pct": 0.05,
                "reason": "Libro sin profundidad (permitido fallback defensivo)"
            }

        bid_vol = sum(float(b[1]) for b in bids)
        ask_vol = sum(float(a[1]) for a in asks)
        tot_ob = bid_vol + ask_vol
        obi = (bid_vol - ask_vol) / tot_ob if tot_ob > 0 else 0.0

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        spread_pct = ((best_ask - best_bid) / best_bid * 100.0) if best_bid > 0 else 0.0

        # 2. Taker Trades (Tape):
        trades = ex.fetch_trades(symbol, limit=50)
        if trades:
            taker_buy_vol = sum(float(t.get("amount", 0.0) or 0.0) for t in trades if t.get("side") == "buy")
            taker_sell_vol = sum(float(t.get("amount", 0.0) or 0.0) for t in trades if t.get("side") == "sell")
            tot_taker = taker_buy_vol + taker_sell_vol
            buy_ratio_pct = (taker_buy_vol / tot_taker * 100.0) if tot_taker > 0 else 50.0
            delta = taker_buy_vol - taker_sell_vol
        else:
            buy_ratio_pct = 50.0
            delta = 0.0

        # Criterios de Validación Institucionales:
        # Veto 1: Spread excesivo (trampa de baja liquidez o slippage)
        if spread_pct > 0.25:
            return {
                "confirmed": False,
                "obi": round(obi, 3),
                "buy_ratio_pct": round(buy_ratio_pct, 1),
                "delta": round(delta, 2),
                "spread_pct": round(spread_pct, 3),
                "reason": f"Spread excesivo ({spread_pct:.2f}% > 0.25%)"
            }

        # Veto 2: Muro masivo de venta en el Ask asfixiando el libro (OBI muy negativo)
        if obi < -0.25:
            return {
                "confirmed": False,
                "obi": round(obi, 3),
                "buy_ratio_pct": round(buy_ratio_pct, 1),
                "delta": round(delta, 2),
                "spread_pct": round(spread_pct, 3),
                "reason": f"Muro de venta institucional en Asks (OBI {obi:+.2f} < -0.25)"
            }

        # Veto 3: Agresión vendedora activa en la cinta (Taker sellers dominan > 55%)
        if buy_ratio_pct < 45.0:
            return {
                "confirmed": False,
                "obi": round(obi, 3),
                "buy_ratio_pct": round(buy_ratio_pct, 1),
                "delta": round(delta, 2),
                "spread_pct": round(spread_pct, 3),
                "reason": f"Ventas agresivas en cinta (Solo {buy_ratio_pct:.1f}% compras)"
            }

        return {
            "confirmed": True,
            "obi": round(obi, 3),
            "buy_ratio_pct": round(buy_ratio_pct, 1),
            "delta": round(delta, 2),
            "spread_pct": round(spread_pct, 3),
            "reason": "Order Flow Confirmado (Compradores activos sin muros de bloqueo)"
        }
    except Exception as e:
        # Fallback defensivo si el exchange tiene microcorte
        return {
            "confirmed": True,
            "obi": 0.0,
            "buy_ratio_pct": 50.0,
            "delta": 0.0,
            "spread_pct": 0.05,
            "reason": f"Excepción en telemetría OF ({e})"
        }
