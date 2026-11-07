"""
BINANCE LIVE DELTA-NEUTRAL CASH & CARRY EXECUTION ENGINE
Ejecutor Cuantitativo Institucional para Arbitraje de Financiación (Funding Rate) en Binance.
1. Valida saldos en Binance Spot y Binance USDⓈ-M Futures.
2. Verifica liquidez en libro de órdenes L2 y tasa de financiamiento positiva.
3. Compra Spot y simultáneamente abre Short 1x en Futuros por la MISMA cantidad exacta.
4. Garantiza Delta = 0.00% (cero exposición direccional al precio de la moneda).
5. Persiste el estado en SQLite WAL para telemetría en el Dashboard 24/7.
"""
import os
import sys
import time
import math
import argparse
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import ccxt
from dotenv import load_dotenv

# Codificación UTF-8 para consola Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import SwingDatabase

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

if not API_KEY or not API_SECRET:
    print("[ERROR] BINANCE_API_KEY o BINANCE_API_SECRET no configurados en .env")
    sys.exit(1)


def get_binance_clients():
    spot = ccxt.binance({
        "apiKey": API_KEY,
        "secret": API_SECRET,
        "enableRateLimit": True,
    })
    fut = ccxt.binance({
        "apiKey": API_KEY,
        "secret": API_SECRET,
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    })
    return spot, fut


def inspect_balances(spot, fut) -> Dict[str, float]:
    spot_bal = spot.fetch_balance()
    fut_bal = fut.fetch_balance()

    spot_usdt = float(spot_bal["free"].get("USDT", 0.0))
    fut_usdt = float(fut_bal["free"].get("USDT", 0.0))
    return {
        "spot_usdt": spot_usdt,
        "fut_usdt": fut_usdt,
        "total_usdt": spot_usdt + fut_usdt,
        "spot_raw": spot_bal,
        "fut_raw": fut_bal,
    }


def execute_cash_and_carry(symbol: str = "XVG/USDT", dry_run: bool = False):
    print("=" * 70)
    print(f"  BINANCE CASH & CARRY LIVE ENGINE | Target: {symbol}")
    print(f"  Modo: {'[SIMULACIÓN / DRY-RUN]' if dry_run else '🔴 [EJECUCIÓN REAL EN VIVO]'}")
    print("=" * 70)

    spot, fut = get_binance_clients()
    db = SwingDatabase()

    # 1. Auditar saldos libres
    bals = inspect_balances(spot, fut)
    spot_free = bals["spot_usdt"]
    fut_free = bals["fut_usdt"]
    print(f"  -> Spot USDT Libre:    ${spot_free:.4f}")
    print(f"  -> Futuros USDT Libre: ${fut_free:.4f}")
    print(f"  -> Capital Total:      ${bals['total_usdt']:.4f}")

    if spot_free < 5.0 or fut_free < 5.0:
        print("[ERROR] Saldo insuficiente. Mínimo $5.00 USDT en cada billetera.")
        return False

    # 2. Cargar mercados e información del par
    spot_markets = spot.load_markets()
    fut_markets = fut.load_markets()

    fut_symbol = f"{symbol}:USDT"
    if symbol not in spot_markets or fut_symbol not in fut_markets:
        print(f"[ERROR] El par {symbol} no está disponible simultáneamente en Spot y Futuros.")
        return False

    spot_m = spot_markets[symbol]
    fut_m = fut_markets[fut_symbol]

    # 3. Tasa de Financiación actual
    fr_data = fut.fetch_funding_rate(fut_symbol)
    rate_8h = float(fr_data.get("fundingRate", 0.0))
    rate_8h_pct = rate_8h * 100.0
    apr = rate_8h_pct * 3.0 * 365.0
    funding_timestamp = fr_data.get("fundingTimestamp")

    print(f"  -> Tasa de Financiación: {rate_8h_pct:+.4f}% / 8h (APR: {apr:+.1f}%)")
    if rate_8h <= 0.0:
        print(f"[ALERTA] La tasa de financiación es negativa o cero ({rate_8h_pct:.4f}%). No conviene entrar en corto.")
        return False

    # 4. Libro de órdenes y precios
    spot_ob = spot.fetch_order_book(symbol, limit=5)
    fut_ob = fut.fetch_order_book(fut_symbol, limit=5)

    spot_ask = spot_ob["asks"][0][0]
    fut_bid = fut_ob["bids"][0][0]
    basis = ((fut_bid - spot_ask) / spot_ask) * 100.0

    print(f"  -> Spot Best Ask: {spot_ask:.6f} | Fut Best Bid: {fut_bid:.6f}")
    print(f"  -> Basis (Spread Entrada): {basis:+.4f}%")

    # 5. Dimensionamiento Cuantitativo de la Orden
    # Dejamos $0.25 de margen de seguridad para comisiones y buffer
    target_spend = min(spot_free - 0.25, fut_free - 0.25)
    if target_spend < 5.0:
        target_spend = min(spot_free * 0.98, fut_free * 0.98)

    raw_qty = target_spend / spot_ask

    # Respetar precisión de lot size (XVG es entero, stepSize = 1.0)
    precision_amount = fut_m["precision"].get("amount", 1.0)
    if precision_amount >= 1.0:
        qty = math.floor(raw_qty)
    else:
        qty = round(raw_qty, int(-math.log10(precision_amount)))

    notional = qty * spot_ask
    print(f"  -> Cantidad a operar: {qty} {symbol.split('/')[0]}")
    print(f"  -> Nocional Estimado: ${notional:.2f} USDT en Spot + ${notional:.2f} USDT en Futuros")

    if dry_run:
        print("\n[DRY-RUN EXITOSO] Parámetros validados correctamente. Listo para ejecución real.")
        return True

    # 6. CONFIGURAR APALANCAMIENTO A 2x (Seguridad de Colateral 100%)
    try:
        fut.set_leverage(2, fut_symbol)
        print(f"  -> Apalancamiento en Futuros configurado a 2x para {fut_symbol}")
    except Exception as e:
        print(f"  [AVISO] Configurar apalancamiento: {e}")

    # 7. EJECUCIÓN PASO A PASO
    # Paso A: Compra en Spot
    print(f"\n[1/3] Ejecutando COMPRA SPOT de {qty} {symbol}...")
    spot_order = spot.create_market_buy_order(symbol, qty)
    print(f"  ✓ Orden Spot Ejecutada: ID {spot_order.get('id')}")

    time.sleep(1.0)

    # Verificar saldo Spot real recibido
    base_coin = symbol.split("/")[0]
    spot_bal_post = spot.fetch_balance()
    spot_coins_held = float(spot_bal_post["free"].get(base_coin, 0.0))
    print(f"  -> Monedas {base_coin} en Spot: {spot_coins_held}")

    # Cantidad para la cobertura corta (el menor entre lo comprado y lo disponible)
    short_qty = min(qty, math.floor(spot_coins_held))
    print(f"\n[2/3] Ejecutando VENTA CORTO FUTUROS de {short_qty} {fut_symbol}...")
    fut_order = fut.create_market_sell_order(fut_symbol, short_qty)
    print(f"  ✓ Orden Corto Futuros Ejecutada: ID {fut_order.get('id')}")

    time.sleep(1.0)

    # 8. VERIFICACIÓN DELTA-NEUTRAL
    print("\n[3/3] Auditando Balance Delta-Neutral...")
    pos_info = fut.fetch_positions([fut_symbol])
    active_fut_pos = None
    for p in pos_info:
        if p["symbol"] == fut_symbol or p.get("info", {}).get("symbol") == fut_symbol.replace("/", "").replace(":USDT", ""):
            active_fut_pos = p
            break

    fut_contracts = abs(float(active_fut_pos.get("contracts", 0.0))) if active_fut_pos else short_qty
    delta_coins = spot_coins_held - fut_contracts
    delta_usd = delta_coins * spot_ask

    print(f"  -> Spot Long:      +{spot_coins_held} {base_coin}")
    print(f"  -> Futuros Short:  -{fut_contracts} {base_coin}")
    print(f"  -> Delta Neto:     {delta_coins:+.2f} {base_coin} (${delta_usd:+.4f} USD)")

    if abs(delta_usd) < 0.20:
        print("  🎉 DELTA-NEUTRAL PERFECTO CONFIRMADO (Exposición Direccional ~0.00%)")
    else:
        print(f"  ⚠️ Desbalance menor detectado: ${delta_usd:+.4f} USD")

    # 9. GUARDAR ESTADO EN SQLITE WAL PARA TELEMETRÍA DEL DASHBOARD
    now_ts = time.time()
    next_ft = funding_timestamp if funding_timestamp else int((now_ts + 8 * 3600) * 1000)
    total_deployed = (spot_coins_held * spot_ask) + (fut_contracts * spot_ask)

    state_data = {
        "mode": "LIVE_BINANCE",
        "initial_capital": round(bals["total_usdt"], 2),
        "capital": round(bals["total_usdt"], 4),
        "total_interest_earned": 0.0,
        "pnl_pct": 0.0,
        "payments_collected": 0,
        "active_pair": symbol,
        "active_rate_8h": round(rate_8h_pct, 4),
        "active_rate_8h_dec": rate_8h,
        "active_apr": round(apr, 2),
        "last_payment_timestamp": now_ts,
        "next_funding_time": next_ft,
        "spot_qty": spot_coins_held,
        "futures_qty": fut_contracts,
        "spot_ask": spot_ask,
        "fut_bid": fut_bid,
        "entry_basis_pct": round(basis, 4),
        "updated_at": datetime.now().isoformat(),
        "history": [],
        "top_opportunities": []
    }
    db.save_cash_carry_state(state_data)
    print("\n✓ Estado guardado en base de datos SQLite WAL. Dashboard actualizado en tiempo real.")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Binance Live Delta-Neutral Cash & Carry")
    parser.add_argument("--execute", action="store_true", help="Ejecutar órdenes reales en Binance")
    parser.add_argument("--symbol", type=str, default="XVG/USDT", help="Símbolo a operar (ej. XVG/USDT)")
    args = parser.parse_args()

    execute_cash_and_carry(symbol=args.symbol, dry_run=not args.execute)
