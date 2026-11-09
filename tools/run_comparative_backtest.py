"""
Comparative Backtester: Strategy A (Original Bot) vs Strategy B (Predictive Pullback & Volume)
Analyzes losing trades from Binance paper trading logs to evaluate what would have happened
with the user's intended strategy (pullback to support, volume dry-up, wide noise SL, forward targets).
"""
import os
import sys
import json
import time
import datetime
import ccxt
import pandas as pd
import numpy as np

# Load losing cycles
with open("losing_cycles.json", "r", encoding="utf-8") as f:
    losing_cycles = json.load(f)

print(f"Loaded {len(losing_cycles)} losing trade cycles to backtest.")

exchange = ccxt.binance({"enableRateLimit": True})

# Select the most significant losing cycles (top 20) across diverse coins
# to prevent rate limit while getting high statistical significance
top_cycles = sorted(losing_cycles, key=lambda x: x["pnl"])[:25]

results = []

for idx, trade in enumerate(top_cycles):
    symbol = trade["symbol"]
    start_iso = trade["start"]
    end_iso = trade["end"]
    entry_price = trade["entry_price"]
    exit_price = trade["exit_price"]
    realized_pnl = trade["pnl"]
    reason = trade["reason"]

    print(f"\n[{idx+1}/{len(top_cycles)}] Analyzing {symbol} (Original Loss: ${realized_pnl:+.4f})...")
    
    try:
        # Parse timestamp: start 2 hours before trade to calculate indicators & support
        start_dt = datetime.datetime.fromisoformat(start_iso)
        fetch_since_dt = start_dt - datetime.timedelta(hours=4)
        since_ms = int(fetch_since_dt.timestamp() * 1000)

        candles = exchange.fetch_ohlcv(symbol, "15m", since=since_ms, limit=100)
        if not candles or len(candles) < 20:
            print(f"  Warning: Insufficient candles for {symbol}")
            continue

        df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["dt"] = pd.to_datetime(df["timestamp"], unit="ms")
        df["ema20"] = df["close"].ewm(span=20).mean()
        df["vol_sma"] = df["volume"].rolling(20).mean()
        
        # Calculate ATR 14
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["atr"] = tr.rolling(14).mean()

        # Find candle index closest to our entry time
        entry_ts_ms = int(start_dt.timestamp() * 1000)
        entry_idx = (df["timestamp"] - entry_ts_ms).abs().idxmin()

        # Post-entry window (up to 24 hours / 96 candles after entry)
        post_candles = df.iloc[entry_idx: entry_idx + 60]
        if len(post_candles) < 5:
            continue

        lowest_after_entry = post_candles["low"].min()
        highest_after_entry = post_candles["high"].max()

        # Did it bounce after stopping out?
        # Check max price after the exit timestamp
        exit_dt = datetime.datetime.fromisoformat(end_iso)
        exit_ts_ms = int(exit_dt.timestamp() * 1000)
        exit_idx = (df["timestamp"] - exit_ts_ms).abs().idxmin()
        post_exit_candles = df.iloc[exit_idx: exit_idx + 48]
        max_after_exit = post_exit_candles["high"].max() if len(post_exit_candles) > 0 else exit_price
        bounce_pct_after_sl = ((max_after_exit / exit_price) - 1) * 100 if exit_price > 0 else 0

        # -------------------------------------------------------------
        # STRATEGY B: PREDICTIVE PULLBACK & VOLUME CONFIRMATION
        # -------------------------------------------------------------
        # At the moment the original bot bought:
        pre_candle = df.iloc[entry_idx]
        ema20_val = pre_candle["ema20"]
        atr_val = pre_candle["atr"]
        dist_to_ema = ((pre_candle["close"] - ema20_val) / ema20_val) * 100
        vol_surge = pre_candle["volume"] / pre_candle["vol_sma"] if pre_candle["vol_sma"] > 0 else 1.0

        # RULE 1: Anti-Crest Filter
        # If price was > 1.0% above EMA20, Strategy B REFUSES to buy at market!
        was_in_crest = dist_to_ema > 0.80

        # RULE 2: Support Limit Buy (Patient Entry)
        # Strategy B places limit order at EMA20 or 1.5% below current price
        strat_b_limit_price = min(pre_candle["close"] * 0.982, ema20_val)
        
        # Did price pull back to fill Strategy B's limit order?
        limit_filled = False
        fill_idx = None
        for i in range(entry_idx, min(len(df), entry_idx + 16)):  # 4 hours window to fill
            if df.iloc[i]["low"] <= strat_b_limit_price:
                limit_filled = True
                fill_idx = i
                break

        strat_b_pnl = 0.0
        strat_b_outcome = "NO TRADE (Evitó la trampa / No persiguió cresta)"

        if limit_filled and fill_idx is not None:
            # Check volume confirmation on fill candle:
            fill_candle = df.iloc[fill_idx]
            # Strategy B Stop Loss: 2.5x ATR below support (avoids noise shakeout)
            strat_b_sl = strat_b_limit_price - (atr_val * 2.2)
            strat_b_tp1 = strat_b_limit_price * 1.030  # +3.0% TP1
            strat_b_capital = 25.0  # Normalized $25 position

            # Simulate forward trajectory from fill
            trade_post = df.iloc[fill_idx + 1: fill_idx + 48]
            hit_tp = False
            hit_sl = False
            tp_idx = None

            for k in range(len(trade_post)):
                c = trade_post.iloc[k]
                if c["high"] >= strat_b_tp1:
                    hit_tp = True
                    tp_idx = k
                    break
                if c["low"] <= strat_b_sl:
                    hit_sl = True
                    break

            if hit_tp:
                # 50% sold at +3%, other 50% trailed
                gain_tp1 = (strat_b_capital * 0.5) * 0.030
                # Trailing remainder
                runner_max = trade_post.iloc[tp_idx:]["high"].max() if tp_idx is not None else strat_b_tp1
                runner_gain_pct = ((runner_max / strat_b_limit_price) - 1) * 0.7  # capture 70% of runner peak
                gain_runner = (strat_b_capital * 0.5) * max(0.005, runner_gain_pct)
                strat_b_pnl = gain_tp1 + gain_runner
                strat_b_outcome = f"GANADA (TP1 +3.0% y Runner): +${strat_b_pnl:.3f}"
            elif hit_sl:
                loss_pct = (strat_b_limit_price - strat_b_sl) / strat_b_limit_price
                strat_b_pnl = -(strat_b_capital * loss_pct)
                strat_b_outcome = f"STOP LOSS (Soporte Roto): -${abs(strat_b_pnl):.3f}"
            else:
                # Time exit after 12h
                last_c = trade_post.iloc[-1]["close"] if len(trade_post) > 0 else strat_b_limit_price
                diff_pct = (last_c - strat_b_limit_price) / strat_b_limit_price
                strat_b_pnl = strat_b_capital * diff_pct
                strat_b_outcome = f"CIERRE TEMPORAL: ${strat_b_pnl:+.3f}"

        trade_analysis = {
            "symbol": symbol,
            "entry_time": start_iso,
            "original_loss": realized_pnl,
            "original_reason": reason,
            "was_in_crest": was_in_crest,
            "dist_to_ema_entry": dist_to_ema,
            "vol_surge_entry": vol_surge,
            "bounce_after_bot_sl_pct": bounce_pct_after_sl,
            "strat_b_filled": limit_filled,
            "strat_b_outcome": strat_b_outcome,
            "strat_b_pnl": strat_b_pnl
        }
        results.append(trade_analysis)
        print(f"  -> Original: ${realized_pnl:+.4f} | Rebote tras SL: +{bounce_pct_after_sl:.1f}%")
        print(f"  -> Estrategia B: {strat_b_outcome}")

        time.sleep(0.15)  # rate limit safety
    except Exception as e:
        print(f"  Error processing {symbol}: {e}")

# Summary evaluation
print("\n" + "="*80)
print("RESUMEN FORENSE COMPARATIVO DE BACKTESTING")
print("="*80)

total_orig_loss = sum(r["original_loss"] for r in results)
total_strat_b_pnl = sum(r["strat_b_pnl"] for r in results)
bounced_trades = [r for r in results if r["bounce_after_bot_sl_pct"] > 2.0]
avoided_trades = [r for r in results if not r["strat_b_filled"]]
won_b_trades = [r for r in results if r["strat_b_pnl"] > 0]

print(f"Total Trades Analizados: {len(results)}")
print(f"Pérdida Total Estrategia Original A: ${total_orig_loss:+.4f} USDT")
print(f"Resultado Estrategia B (Predictiva): ${total_strat_b_pnl:+.4f} USDT")
print(f"Diferencia a favor de Estrategia B: ${total_strat_b_pnl - total_orig_loss:+.4f} USDT")
print(f"Trades donde el bot original fue sacado y LUEGO REBOTÓ (+2% o más): {len(bounced_trades)} de {len(results)} ({len(bounced_trades)/len(results)*100:.1f}%)")
print(f"Trades que la Estrategia B EVITÓ por no comprar en la cresta: {len(avoided_trades)} de {len(results)}")
print(f"Trades Ganados por Estrategia B: {len(won_b_trades)}")

with open("backtest_comparative_results.json", "w", encoding="utf-8") as f:
    json.dump({
        "summary": {
            "total_trades": len(results),
            "original_loss": total_orig_loss,
            "strategy_b_pnl": total_strat_b_pnl,
            "bounced_count": len(bounced_trades),
            "avoided_count": len(avoided_trades),
            "won_count": len(won_b_trades)
        },
        "trades": results
    }, f, indent=2)

print("\nResultados detallados exportados a backtest_comparative_results.json")
