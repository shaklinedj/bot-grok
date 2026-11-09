"""
Backtest Offline Period: 2026-10-03 02:46 to 2026-10-03 21:30
Simulates the exact bot execution (Multi-Factor + Tight Maker + TP1 + Trailing)
over the period the computer was offline.
"""
import os
import sys
import time
import datetime
import ccxt
import pandas as pd
import numpy as np

exchange = ccxt.binance({"enableRateLimit": True})

# 1. First, check ENJ/USDT trade that was opened at 02:51:46
enj_entry_price = 0.03537
enj_capital = 30.34
enj_amount = 857.789
enj_sl = 0.031811
enj_tp1 = enj_entry_price * 1.0242 # +2.42% -> 0.036226

print("================================================================================")
print("1. EVALUANDO LA POSICION ABIERTA ANTES DEL REINICIO: ENJ/USDT ($0.03537)")
print("================================================================================")

# Fetch ENJ 15m candles from 02:45 to now
since_ms = int(datetime.datetime(2026, 10, 3, 2, 45, tzinfo=datetime.timezone.utc).timestamp() * 1000)
try:
    enj_candles = exchange.fetch_ohlcv("ENJ/USDT", "15m", since=since_ms, limit=100)
    enj_df = pd.DataFrame(enj_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    enj_df["dt"] = pd.to_datetime(enj_df["timestamp"], unit="ms")
    
    max_high = enj_df["high"].max()
    min_low = enj_df["low"].min()
    curr_p = enj_df["close"].iloc[-1]
    
    print(f"  Velas analizadas: {len(enj_df)}")
    print(f"  Precio Entrada: ${enj_entry_price:.5f}")
    print(f"  Precio Maximo alcanzado: ${max_high:.5f} ({((max_high/enj_entry_price)-1)*100:+.2f}%)")
    print(f"  Precio Minimo alcanzado: ${min_low:.5f} ({((min_low/enj_entry_price)-1)*100:+.2f}%)")
    print(f"  Precio Actual: ${curr_p:.5f} ({((curr_p/enj_entry_price)-1)*100:+.2f}%)")
    print(f"  TP1 Target (+2.42%): ${enj_tp1:.5f}")
    print(f"  Stop Loss Inicial: ${enj_sl:.5f}")
    
    # Simulate step-by-step
    tp1_hit = False
    closed = False
    exit_price = curr_p
    exit_reason = "Abierta actualmente"
    realized_pnl = 0.0
    
    for idx, row in enj_df.iterrows():
        # Check TP1
        if not tp1_hit and row["high"] >= enj_tp1:
            tp1_hit = True
            tp1_amount = enj_amount * 0.15
            tp1_pnl = tp1_amount * (enj_tp1 - enj_entry_price)
            realized_pnl += tp1_pnl
            enj_sl = enj_entry_price * 1.002 # Break-even +0.20%
            print(f"  -> TP1 ALCANZADO en {row['dt']} a ${enj_tp1:.5f}! PnL parcial: +${tp1_pnl:.4f}")
        
        # Check SL / BE
        if row["low"] <= enj_sl:
            closed = True
            exit_price = enj_sl
            rem_amount = enj_amount * 0.85 if tp1_hit else enj_amount
            rem_pnl = rem_amount * (enj_sl - enj_entry_price)
            realized_pnl += rem_pnl
            exit_reason = "Escudo Break-Even (+0.20%)" if tp1_hit else "Stop Loss Inicial"
            print(f"  -> CIERRE por {exit_reason} en {row['dt']} a ${enj_sl:.5f}. PnL final: ${realized_pnl:+.4f}")
            break
            
    if not closed:
        floating_pnl = (enj_amount * (curr_p - enj_entry_price))
        print(f"  -> ESTADO ACTUAL: Posicion sigue ABIERTA. PnL Flotante: ${floating_pnl:+.4f} USDT")
        
except Exception as e:
    print(f"  Error analizando ENJ: {e}")

print("\n================================================================================")
print("2. BACKTEST COMPLETO DE OPORTUNIDADES EN LAS ~18.5 HORAS OFFLINE")
print("================================================================================")

# Candidate pool from our bot's radar
symbols = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "SUI/USDT", 
    "BNB/USDT", "DOGE/USDT", "AVAX/USDT", "ADA/USDT", "ENJ/USDT", 
    "QNT/USDT", "SCR/USDT", "GALA/USDT", "APE/USDT", "MAGIC/USDT",
    "NEAR/USDT", "WLD/USDT", "MINA/USDT"
]

all_trades = []
initial_capital = 80.0
cash = initial_capital
max_slots = 2
active_positions = {}

# We'll step through time in 15m intervals across the ~18.5 hours
start_dt = datetime.datetime(2026, 10, 3, 2, 45, tzinfo=datetime.timezone.utc)
since_ms = int(start_dt.timestamp() * 1000)

symbol_dfs = {}
for sym in symbols:
    try:
        candles = exchange.fetch_ohlcv(sym, "15m", since=since_ms, limit=100)
        if candles and len(candles) >= 15:
            df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["dt"] = pd.to_datetime(df["timestamp"], unit="ms")
            df["ema20"] = df["close"].ewm(span=20).mean()
            df["ema50"] = df["close"].ewm(span=50).mean()
            # ATR 14
            high_low = df["high"] - df["low"]
            high_close = (df["high"] - df["close"].shift()).abs()
            low_close = (df["low"] - df["close"].shift()).abs()
            df["atr"] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1).rolling(14).mean()
            # RSI 14
            delta = df["close"].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss.replace(0, np.nan)
            df["rsi"] = 100 - (100 / (1 + rs))
            symbol_dfs[sym] = df
    except Exception as e:
        pass

print(f"Descargadas series 15m para {len(symbol_dfs)} símbolos durante el período offline.")

# Time steps
if symbol_dfs:
    # Get common timestamps
    ref_sym = "BTC/USDT" if "BTC/USDT" in symbol_dfs else list(symbol_dfs.keys())[0]
    time_points = symbol_dfs[ref_sym]["timestamp"].tolist()
    
    for t_idx, t_ms in enumerate(time_points):
        t_dt = pd.to_datetime(t_ms, unit="ms")
        
        # 1. Update active positions
        to_close = []
        for sym, pos in list(active_positions.items()):
            if sym not in symbol_dfs:
                continue
            df_sym = symbol_dfs[sym]
            c_row = df_sym[df_sym["timestamp"] == t_ms]
            if c_row.empty:
                continue
            candle = c_row.iloc[0]
            
            c_high = candle["high"]
            c_low = candle["low"]
            c_close = candle["close"]
            
            # Check TP1
            if not pos["tp1_hit"] and c_high >= pos["tp1_price"]:
                pos["tp1_hit"] = True
                tp1_qty = pos["amount"] * 0.15
                tp1_pnl = tp1_qty * (pos["tp1_price"] - pos["entry_price"])
                pos["realized_pnl"] += tp1_pnl
                cash += (tp1_qty * pos["entry_price"]) + tp1_pnl
                pos["stop_loss"] = pos["entry_price"] * 1.002 # Move SL to Break-Even (+0.20%)
                pos["amount"] *= 0.85
                pos["capital_allocated"] *= 0.85
            
            # Check Trailing for runner if price keeps climbing
            if pos["tp1_hit"] and c_close > pos["highest_price"]:
                pos["highest_price"] = c_close
                # Runner trailing stop: highest - 1.2*ATR
                trailing_candidate = c_close - (pos["atr"] * 1.20)
                if trailing_candidate > pos["stop_loss"]:
                    pos["stop_loss"] = trailing_candidate
            
            # Check Stop Loss / BE / Trailing Exit
            if c_low <= pos["stop_loss"]:
                exit_price = pos["stop_loss"]
                exit_pnl = pos["amount"] * (exit_price - pos["entry_price"])
                pos["realized_pnl"] += exit_pnl
                cash += (pos["amount"] * pos["entry_price"]) + exit_pnl
                total_pnl = pos["realized_pnl"]
                reason = "Trailing Stop" if (pos["tp1_hit"] and exit_price > pos["entry_price"] * 1.005) else ("Break-Even (+0.20%)" if pos["tp1_hit"] else "Stop Loss Inicial")
                
                all_trades.append({
                    "symbol": sym,
                    "entry_time": pos["entry_time"],
                    "exit_time": str(t_dt),
                    "entry_price": pos["entry_price"],
                    "exit_price": exit_price,
                    "pnl": total_pnl,
                    "return_pct": (total_pnl / pos["initial_capital"]) * 100,
                    "reason": reason,
                    "tp1_hit": pos["tp1_hit"]
                })
                to_close.append(sym)
                
        for sym in to_close:
            del active_positions[sym]
            
        # 2. Scan for new entries if slots available
        if len(active_positions) < max_slots and cash >= 20.0:
            candidates = []
            for sym, df_sym in symbol_dfs.items():
                if sym in active_positions:
                    continue
                c_slice = df_sym[df_sym["timestamp"] <= t_ms]
                if len(c_slice) < 20:
                    continue
                row = c_slice.iloc[-1]
                
                # Check Momentum + Tight Maker criteria:
                # 1. Trend: close > ema50 and rsi between 40 and 65
                if row["close"] > row["ema50"] and 40 <= row["rsi"] <= 65:
                    # Tight Maker Limit: -0.40% below close
                    limit_entry = row["close"] * 0.9960
                    # Check if NEXT candle touched the limit (passive fill)
                    fut = df_sym[df_sym["timestamp"] > t_ms]
                    if not fut.empty:
                        next_candle = fut.iloc[0]
                        if next_candle["low"] <= limit_entry:
                            # Limit filled!
                            atr_val = row["atr"] if not np.isnan(row["atr"]) else row["close"] * 0.02
                            score = 70.0 + (10 if row["close"] > row["ema20"] else 0)
                            candidates.append({
                                "symbol": sym,
                                "limit_entry": limit_entry,
                                "atr": atr_val,
                                "score": score
                            })
                            
            # Sort by score and pick best
            candidates.sort(key=lambda x: x["score"], reverse=True)
            for cand in candidates:
                if len(active_positions) >= max_slots or cash < 20.0:
                    break
                slot_cap = min(cash * 0.48, 38.0)
                if slot_cap >= 18.0:
                    cash -= slot_cap
                    sym = cand["symbol"]
                    entry_p = cand["limit_entry"]
                    atr_v = cand["atr"]
                    active_positions[sym] = {
                        "symbol": sym,
                        "entry_time": str(t_dt),
                        "entry_price": entry_p,
                        "amount": slot_cap / entry_p,
                        "initial_capital": slot_cap,
                        "capital_allocated": slot_cap,
                        "tp1_price": entry_p * 1.0242,
                        "stop_loss": entry_p - (atr_v * 1.10),
                        "highest_price": entry_p,
                        "tp1_hit": False,
                        "realized_pnl": 0.0,
                        "atr": atr_v
                    }

print(f"\nTotal trades simulados durante las ~18.5h offline: {len(all_trades)}")
df_res = pd.DataFrame(all_trades)
if not df_res.empty:
    wins = df_res[df_res["pnl"] > 0]
    losses = df_res[df_res["pnl"] <= 0]
    total_pnl = df_res["pnl"].sum()
    win_rate = (len(wins) / len(df_res)) * 100
    print("\n------------------------- RESUMEN DE RENDIMIENTO -------------------------")
    print(f"Trades Completados: {len(df_res)}")
    print(f"Victorias (Wins):    {len(wins)} ({win_rate:.1f}%)")
    print(f"Derrotas (Losses):  {len(losses)} ({100-win_rate:.1f}%)")
    print(f"PnL Neto Total:     ${total_pnl:+.4f} USDT")
    print(f"Equity Proyectado:  ${initial_capital + total_pnl:.2f} USDT")
    print("--------------------------------------------------------------------------")
    print("\nDETALLE DE TRADES:")
    for idx, t in df_res.iterrows():
        print(f"  • {t['symbol']} | Entrada: ${t['entry_price']:.5f} -> Salida: ${t['exit_price']:.5f} | PnL: ${t['pnl']:+.4f} ({t['return_pct']:+.2f}%) | Motivo: {t['reason']}")
else:
    print("No se registraron cierres completos (mercado consolidado o posiciones aún en curso).")
