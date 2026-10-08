"""
backtest_grid_6lines.py
Simula una malla neutral de 6 etapas (Pionex-style) con los datos reales OHLCV de Binance (CCXT)
en las últimas 24 horas (velas de 5m o 1m) para todas las monedas que se cerraron.
Capital asignado: $60 USDT por moneda (o proporcional al capital base).
"""

import ccxt
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

EXCHANGE = ccxt.binance({"enableRateLimit": True})
FEE_RATE = 0.001 # 0.1% Binance spot fee
GRID_LINES = 6 # 6 etapas
TOTAL_CAPITAL = 60.0 # $60 USDT asignados a cada malla

COINS = ["ENA/USDT", "ADA/USDT", "SUI/USDT", "ZEC/USDT", "FIL/USDT", "NMR/USDT", "ORCA/USDT", "PUMP/USDT"]

def fetch_24h_klines(symbol, timeframe="5m"):
    try:
        # 24h = 288 velas de 5m
        since = EXCHANGE.milliseconds() - (24 * 3600 * 1000)
        ohlcv = EXCHANGE.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=350)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None

def simulate_6line_grid(df, symbol):
    if df is None or len(df) < 50:
        return {"symbol": symbol, "error": "Datos insuficientes"}

    # Precio inicial de partida (hace 24 horas)
    start_price = df.iloc[0]["open"]
    
    # Calcular ATR de partida para fijar el rango de la malla
    df["tr"] = np.maximum(
        df["high"] - df["low"],
        np.maximum(
            abs(df["high"] - df["close"].shift(1)),
            abs(df["low"] - df["close"].shift(1))
        )
    )
    atr = df["tr"].rolling(14).mean().iloc[14]
    if pd.isna(atr) or atr <= 0:
        atr = start_price * 0.02
        
    atr_pct = (atr / start_price) * 100.0
    
    # Amplitud para 6 etapas: ±(1.2 * ATR)
    range_pct = max(0.018, min(0.045, (atr_pct / 100.0) * 1.2))
    
    grid_upper = start_price * (1 + range_pct)
    grid_lower = start_price * (1 - range_pct)
    step_pct = ((grid_upper - grid_lower) / grid_lower) / (GRID_LINES - 1)
    
    step_price = (grid_upper - grid_lower) / (GRID_LINES - 1)
    prices = [grid_lower + i * step_price for i in range(GRID_LINES)]
    
    # Configurar las 6 etapas:
    # 3 compras por debajo del precio inicial, 3 ventas por arriba (con compra a mercado inicial)
    capital_per_line = TOTAL_CAPITAL / GRID_LINES
    
    lines = []
    cash = TOTAL_CAPITAL
    holdings_coin = 0.0
    initial_buy_cost = 0.0
    
    for p in prices:
        if p < start_price:
            # Orden de compra límite esperando bajada
            amt = capital_per_line / p
            cash -= capital_per_line
            lines.append({"price": p, "side": "buy", "amount": amt, "active": True})
        else:
            # Orden de venta límite esperando subida (requiere compra inicial al start_price)
            amt = capital_per_line / p
            cost = amt * start_price * (1 + FEE_RATE)
            cash -= cost
            holdings_coin += amt
            lines.append({"price": p, "side": "sell", "amount": amt, "active": True})
            initial_buy_cost += cost

    fills_buy = 0
    fills_sell = 0
    harvested_pnl = 0.0
    total_fees = 0.0
    
    # Iterar vela a vela por las últimas 24 horas
    for idx, row in df.iterrows():
        high = row["high"]
        low = row["low"]
        
        # Procesar órdenes
        for l in list(lines):
            if not l["active"]:
                continue
                
            if l["side"] == "buy" and low <= l["price"]:
                # Se ejecutó COMPRA
                l["active"] = False
                fills_buy += 1
                fee = (l["amount"] * l["price"]) * FEE_RATE
                total_fees += fee
                amt_after_fee = l["amount"] * (1 - FEE_RATE)
                holdings_coin += amt_after_fee
                
                # Inmediatamente colocamos una VENTA un escalón más arriba
                sell_target = l["price"] * (1 + step_pct)
                lines.append({"price": sell_target, "side": "sell", "amount": amt_after_fee, "active": True})
                
            elif l["side"] == "sell" and high >= l["price"]:
                # Se ejecutó VENTA
                l["active"] = False
                fills_sell += 1
                revenue = l["amount"] * l["price"]
                fee = revenue * FEE_RATE
                total_fees += fee
                net_rev = revenue - fee
                
                # Costo estimado de compra del escalón inferior
                buy_cost = l["amount"] * (l["price"] / (1 + step_pct))
                profit = net_rev - buy_cost
                harvested_pnl += profit
                cash += net_rev
                holdings_coin -= l["amount"]
                
                # Inmediatamente recolocamos la COMPRA un escalón abajo
                buy_target = l["price"] / (1 + step_pct)
                cost_needed = l["amount"] * buy_target
                if cash >= cost_needed:
                    cash -= cost_needed
                    lines.append({"price": buy_target, "side": "buy", "amount": l["amount"], "active": True})

    # Liquidación al precio final de las 24h
    final_price = df.iloc[-1]["close"]
    floating_holdings_val = holdings_coin * final_price
    
    # Reintegrar efectivo comprometido en compras que quedaron vivas
    committed_in_buys = sum(l["price"] * l["amount"] for l in lines if l["active"] and l["side"] == "buy")
    
    final_equity = cash + floating_holdings_val + committed_in_buys
    net_pnl = final_equity - TOTAL_CAPITAL
    roi_pct = (net_pnl / TOTAL_CAPITAL) * 100.0
    
    # Variación del precio del activo (Buy & Hold) en las mismas 24h
    asset_change_pct = ((final_price - start_price) / start_price) * 100.0

    return {
        "symbol": symbol,
        "start_price": start_price,
        "final_price": final_price,
        "asset_24h_pct": asset_change_pct,
        "step_pct": step_pct * 100.0,
        "fills_buy": fills_buy,
        "fills_sell": fills_sell,
        "total_rotations": fills_buy + fills_sell,
        "harvested_pnl": harvested_pnl,
        "fees_paid": total_fees,
        "net_pnl": net_pnl,
        "roi_pct": roi_pct
    }

def run_all():
    results = []
    print(f"\n==========================================================================")
    print(f"[BACKTEST INSTITUCIONAL] MALLAS DE 6 ETAPAS (24 HORAS EN BINANCE SPOT)")
    print(f"Capital por malla: ${TOTAL_CAPITAL:.2f} USDT | Etapas: {GRID_LINES} | Fee: 0.1% maker/taker")
    print(f"==========================================================================\n")
    
    for sym in COINS:
        time.sleep(0.3)
        df = fetch_24h_klines(sym, timeframe="5m")
        res = simulate_6line_grid(df, sym)
        if "error" not in res:
            results.append(res)
            print(f"[OK] {sym:<10} | Fills: {res['total_rotations']:>2} ({res['fills_buy']}B/{res['fills_sell']}S) | Cosechado: +${res['harvested_pnl']:>5.2f} | PnL Neto: ${res['net_pnl']:>+5.2f} ({res['roi_pct']:>+5.2f}%) | Moneda 24h: {res['asset_24h_pct']:>+5.2f}%")
        else:
            print(f"[X]  {sym:<10} | {res['error']}")

    df_res = pd.DataFrame(results)
    if not df_res.empty:
        total_pnl = df_res["net_pnl"].sum()
        total_harvested = df_res["harvested_pnl"].sum()
        total_fills = df_res["total_rotations"].sum()
        avg_roi = df_res["roi_pct"].mean()
        
        print(f"\n--------------------------------------------------------------------------")
        print(f"[RESUMEN GLOBAL] Canasta de {len(df_res)} Monedas Cerradas:")
        print(f"  * Total Rotaciones (Cruces de linea): {total_fills} ordenes ejecutadas")
        print(f"  * PnL Cosechado Bruto (Arbitraje de Malla): +${total_harvested:.2f} USDT")
        print(f"  * PnL Neto Final (despues de comisiones y flotante): ${total_pnl:+.2f} USDT")
        print(f"  * Retorno Promedio por Moneda: {avg_roi:+.2f}%")
        print(f"--------------------------------------------------------------------------\n")

if __name__ == "__main__":
    run_all()
