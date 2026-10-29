"""
Módulo de Escáner de Mercado, Contexto Macro de BTC y Telemetría de Malla Real Pionex.
"""
import time
import json
import shutil
import subprocess
import re
from datetime import datetime
from typing import List, Dict, Any, Optional

from config import (
    exchange,
    REAL_DOGE_GRID_BOT_ID,
    IGNORE_SYMBOLS,
    MIN_VOLUME_USDT
)
from scoring.indicators import calc_ema

TICKER_VALID_REGEX = re.compile(r'^[A-Z0-9]{2,10}/USDT$')


# Cache global para llamadas de red ligeras
_ohlcv_cache = {}
_ticker_cache = {"ts": 0.0, "data": {}}
_btc_performance_cache = {
    "ts": 0.0, "change_1h": 0.0, "change_4h": 0.0, "trend_4h": "neutral",
    "regime": "NEUTRAL_TRANSITION", "regime_desc": "Iniciando análisis macro...",
    "range_3h_pct": 1.0, "can_trade_alts": True
}


def fetch_real_pionex_grid_stats() -> Dict[str, Any]:
    """Consulta la API de Pionex en modo SOLO LECTURA para reportar la Malla de DOGE."""
    try:
        exe = shutil.which("pionex-trade-cli.cmd") or shutil.which("pionex-trade-cli")
        if not exe:
            return {"status": "CLI no disponible"}
        cmd = [exe, "bot", "spot_grid", "get", "--bu-order-id", REAL_DOGE_GRID_BOT_ID]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8)
        if res.returncode == 0:
            data = json.loads(res.stdout).get("data", {})
            bod = data.get("buOrderData", {})
            return {
                "bot_id": REAL_DOGE_GRID_BOT_ID,
                "symbol": "DOGE/USDT",
                "status": bod.get("status", "running"),
                "investment": float(bod.get("initUsdtInvestment", 69.71)),
                "grid_profit": float(bod.get("gridProfit", 0.0)),
                "profit_withdrawn": float(bod.get("profitWithdrawn", 0.0)),
                "total_profit_usdt": round(float(bod.get("gridProfit", 0.0)) + float(bod.get("profitWithdrawn", 0.0)), 4),
                "paired_count": int(bod.get("exchangeOrderPairedCount", 0)),
                "closed_count": int(bod.get("closedExchangeOrderCount", 0)),
                "range_bottom": float(bod.get("bottom", 0.06711)),
                "range_top": float(bod.get("top", 0.09383)),
                "auto_reinvest": bool(bod.get("profitAutoReinvest", True)),
                "trailing_up": bool(bod.get("movingTrailingUpParam")),
                "updated_at": datetime.now().strftime("%H:%M:%S")
            }
    except Exception as e:
        return {"error": str(e), "status": "offline"}
    return {}


def fetch_ohlcv_cached(symbol: str, timeframe: str, limit: int = 60) -> List:
    """Obtiene velas OHLCV con TTL en memoria para no saturar los límites de API."""
    import sys
    hsa = sys.modules.get("hourly_swing_agent")
    if hsa and "fetch_ohlcv_cached" in hsa.__dict__ and hsa.__dict__["fetch_ohlcv_cached"] is not fetch_ohlcv_cached:
        return hsa.__dict__["fetch_ohlcv_cached"](symbol, timeframe, limit=limit)

    key = f"{symbol}_{timeframe}"
    now = time.time()
    cached = _ohlcv_cache.get(key)
    ttl = 30 if timeframe in ("3m", "5m") else (60 if timeframe == "15m" else 180)
    if cached and (now - cached["ts"] < ttl):
        return cached["data"]
    try:
        data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        _ohlcv_cache[key] = {"ts": now, "data": data}
        return data
    except Exception:
        return cached["data"] if cached else []


def update_btc_context() -> Dict[str, Any]:
    """Actualiza el contexto macro de Bitcoin (Régimen de Mercado, Filtro Lateral y Fuerza Relativa)."""
    global _btc_performance_cache
    now = time.time()
    if now - _btc_performance_cache.get("ts", 0) < 45:
        return _btc_performance_cache
    try:
        c_15m = fetch_ohlcv_cached("BTC/USDT", "15m", limit=24)
        c_1h = fetch_ohlcv_cached("BTC/USDT", "1h", limit=24)
        c_4h = fetch_ohlcv_cached("BTC/USDT", "4h", limit=25)
        if len(c_1h) >= 2 and len(c_4h) >= 5:
            btc_curr = c_1h[-1][4]
            chg_1h = (c_1h[-1][4] - c_1h[-2][4]) / c_1h[-2][4] * 100.0
            chg_4h = (c_4h[-1][4] - c_4h[-5][4]) / c_4h[-5][4] * 100.0
            closes_4h = [c[4] for c in c_4h]
            ema20_4h = calc_ema(closes_4h, 20)
            trend_4h = "bullish" if c_4h[-1][4] > ema20_4h else "bearish"

            closes_1h = [c[4] for c in c_1h]
            ema20_1h = calc_ema(closes_1h, 20)

            range_3h_pct = 1.0
            if len(c_15m) >= 12:
                highs_3h = max(c[2] for c in c_15m[-12:])
                lows_3h = min(c[3] for c in c_15m[-12:])
                range_3h_pct = (highs_3h - lows_3h) / btc_curr * 100.0

            # Diagnóstico de Régimen Cuantitativo:
            if btc_curr < ema20_1h and chg_1h < -0.35:
                regime = "BEARISH_DUMP"
                regime_desc = "Corrección de BTC (< EMA20 1H). Disparos en altcoins bloqueados preventivamente."
                can_trade_alts = False
            elif range_3h_pct < 0.90 and abs(chg_1h) < 0.25:
                regime = "CHOP_COMPRESSION"
                regime_desc = "Compresión lateral de BTC (rango 3h < 0.9%). Falsas rupturas frecuentes. Exigiendo Score A+ (86+)."
                can_trade_alts = True
            elif btc_curr >= ema20_1h and chg_1h >= 0.10:
                regime = "BULLISH_EXPANSION"
                regime_desc = "Expansión alcista de BTC. Viento de cola favorable para rupturas en altcoins."
                can_trade_alts = True
            else:
                regime = "NEUTRAL_TRANSITION"
                regime_desc = "BTC en consolidación neutra."
                can_trade_alts = True

            _btc_performance_cache = {
                "ts": now,
                "price": btc_curr,
                "change_1h": chg_1h,
                "change_4h": chg_4h,
                "trend_4h": trend_4h,
                "range_3h_pct": range_3h_pct,
                "regime": regime,
                "regime_desc": regime_desc,
                "can_trade_alts": can_trade_alts
            }
    except Exception:
        pass
    return _btc_performance_cache


def scan_market_top_movers() -> List[Dict[str, Any]]:
    """
    FASE 1: Escáner Dinámico de TODO el mercado.
    Busca monedas USDT con alto volumen y rendimiento positivo (o fuerza relativa positiva vs BTC).
    No usa una whitelist fija: rastrea todo Binance.
    """
    global _ticker_cache
    now = time.time()
    if now - _ticker_cache["ts"] < 30:
        tickers = _ticker_cache["data"]
    else:
        try:
            tickers = exchange.fetch_tickers()
            _ticker_cache = {"ts": now, "data": tickers}
        except Exception:
            tickers = _ticker_cache.get("data", {})

    btc_ctx = update_btc_context()
    btc_chg_1h = btc_ctx.get("change_1h", 0.0)

    candidates = []
    for sym, t in tickers.items():
        if not sym.endswith("/USDT"):
            continue
        if not TICKER_VALID_REGEX.match(sym):
            continue
        if sym in IGNORE_SYMBOLS:
            continue
        vol = float(t.get("quoteVolume", 0) or 0)
        if vol < MIN_VOLUME_USDT:
            continue
        pct_24h = float(t.get("percentage", 0) or 0)
        last_price = float(t.get("last", 0) or 0)
        if last_price <= 0:
            continue

        # Fuerza Relativa: qué tan bien se comporta vs BTC en la última hora
        relative_strength = pct_24h - (btc_chg_1h * 0.5)  # Positivo = más fuerte que BTC

        candidates.append({
            "symbol": sym,
            "price": last_price,
            "pct_24h": round(pct_24h, 2),
            "volume_usdt": vol,
            "relative_strength": round(relative_strength, 2),
        })

    # Ordenar por fuerza relativa descendente (las que más resisten o suben vs BTC primero)
    candidates.sort(key=lambda x: x["relative_strength"], reverse=True)
    return candidates[:25]  # Top 25 para analizar en detalle
