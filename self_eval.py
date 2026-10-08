import os
import sys
import io
import json
import pandas as pd
import numpy as np
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

def safe_float(v, default=0.0):
    try:
        if v is None or v == "":
            return default
        f = float(v)
        return default if (np.isnan(f) or np.isinf(f)) else f
    except (ValueError, TypeError):
        return default

class TradeAuditor:
    def __init__(self, logs_dir="paper_logs"):
        self.logs_dir = logs_dir
        self.trades_path = os.path.join(logs_dir, "trades.csv")
    
    def _get_cycles(self):
        """Reconstruct complete trade cycles from trades.csv with multi-schema robustness."""
        if not os.path.exists(self.trades_path):
            return pd.DataFrame()
            
        import csv
        raw_trades = []
        with open(self.trades_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row or row[0].startswith("timestamp"):
                    continue
                # 12-column modern format:
                # [timestamp, symbol, strategy, side, price, amount, pnl, fee, slippage, extra_info, position_id, status]
                if len(row) >= 12:
                    raw_trades.append({
                        "timestamp": row[0],
                        "symbol": row[1],
                        "strategy": row[2],
                        "side": str(row[3]).lower(),
                        "price": safe_float(row[4]),
                        "amount": safe_float(row[5]),
                        "pnl": safe_float(row[6]),
                        "fee": safe_float(row[7]),
                        "slippage": safe_float(row[8]),
                        "extra_info": str(row[9]) if row[9] and row[9] != "nan" else "",
                        "position_id": row[10],
                        "status": row[11]
                    })
                elif len(row) == 11:
                    raw_trades.append({
                        "timestamp": row[0],
                        "symbol": row[1],
                        "strategy": row[2],
                        "side": str(row[3]).lower(),
                        "price": safe_float(row[4]),
                        "amount": safe_float(row[5]),
                        "pnl": safe_float(row[6]),
                        "fee": safe_float(row[7]),
                        "slippage": safe_float(row[8]),
                        "extra_info": str(row[9]) if row[9] and row[9] != "nan" else "",
                        "position_id": row[10],
                        "status": "CLOSED" if str(row[3]).lower() == "sell" else "OPEN"
                    })

        if not raw_trades:
            return pd.DataFrame()

        df = pd.DataFrame(raw_trades)
        cycles = []
        for pos_id, group in df.groupby('position_id'):
            if not pos_id:
                continue
            group = group.copy()
            group['ts'] = pd.to_datetime(group['timestamp'])
            group = group.sort_values('ts')
            
            entry = group[group['side'] == 'buy']
            exits = group[group['side'] == 'sell']
            final_exit = exits[exits['status'].isin(['CLOSED', 'closed'])]
            if final_exit.empty and not exits.empty:
                final_exit = exits.iloc[[-1]]
            
            if entry.empty or exits.empty:
                continue
                
            entry_row = entry.iloc[0]
            exit_row = final_exit.iloc[-1]
            has_tp1 = not exits[exits['strategy'].str.contains('tp1', case=False, na=False)].empty
            
            net_pnl = exits['pnl'].sum()
            total_fees = group['fee'].sum()
            total_slippage = group['slippage'].sum()
            gross_pnl = net_pnl + total_fees + total_slippage
            
            hold_duration = (exit_row['ts'] - entry_row['ts']).total_seconds() / 60.0
            
            exit_reason_raw = str(exit_row.get('extra_info', '') or '')
            if 'Runner Trailing' in exit_reason_raw:
                exit_reason = 'Runner Trailing'
            elif 'Break-Even' in exit_reason_raw or 'Escudo' in exit_reason_raw:
                exit_reason = 'Break-Even'
            elif 'Stop Loss' in exit_reason_raw:
                exit_reason = 'Stop Loss'
            elif 'TP1' in exit_reason_raw:
                exit_reason = 'TP1 Exit'
            else:
                exit_reason = exit_reason_raw[:30] if exit_reason_raw else 'Take Profit / Cierre'
            
            cycles.append({
                'position_id': pos_id,
                'symbol': entry_row['symbol'],
                'entry_time': entry_row['timestamp'],
                'exit_time': exit_row['timestamp'],
                'entry_price': float(entry_row['price']),
                'exit_price': float(exit_row['price']),
                'direction': 'LONG',
                'net_pnl': round(float(net_pnl), 4),
                'total_fees': round(float(total_fees), 4),
                'total_slippage': round(float(total_slippage), 4),
                'gross_pnl': round(float(gross_pnl), 4),
                'hold_duration_min': round(hold_duration, 2),
                'exit_reason': exit_reason,
                'had_tp1': has_tp1,
                'is_win': net_pnl > 0
            })
            
        if not cycles:
            return pd.DataFrame()
        return pd.DataFrame(cycles).sort_values('exit_time', ascending=False)

    def evaluate_last_n_trades(self, n=10):
        """Self-Evaluation Engine for the last N trades."""
        cycles_df = self._get_cycles()
        if cycles_df.empty:
            return {"error": "No completed trade cycles found."}
            
        recent = cycles_df.head(n)
        
        # Overall stats
        wins = recent[recent['is_win']]
        losses = recent[~recent['is_win']]
        
        win_rate = len(wins) / len(recent) if len(recent) > 0 else 0
        avg_win = wins['net_pnl'].mean() if not wins.empty else 0
        avg_loss = losses['net_pnl'].mean() if not losses.empty else 0
        
        gross_profit = wins['net_pnl'].sum()
        gross_loss = abs(losses['net_pnl'].sum())
        profit_factor = gross_profit / gross_loss if gross_loss != 0 else (999 if gross_profit > 0 else 0)
        expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
        
        # Groupings
        by_coin = recent.groupby('symbol')['net_pnl'].agg(['count', 'sum', 'mean']).to_dict('index')
        by_exit = recent['exit_reason'].value_counts(normalize=True).to_dict()
        tp1_rate = recent['had_tp1'].mean() if 'had_tp1' in recent.columns else 0
        
        # Friction
        avg_fee = recent['total_fees'].mean()
        avg_slippage = recent['total_slippage'].mean()
        total_friction = recent['total_fees'].sum() + recent['total_slippage'].sum()
        
        # Time
        avg_hold_wins = wins['hold_duration_min'].mean() if not wins.empty else 0
        avg_hold_losses = losses['hold_duration_min'].mean() if not losses.empty else 0
        
        return {
            "n_trades": len(recent),
            "overall": {
                "win_rate": round(safe_float(win_rate), 4),
                "avg_win": round(safe_float(avg_win), 4),
                "avg_loss": round(safe_float(avg_loss), 4),
                "profit_factor": round(safe_float(profit_factor), 4),
                "expectancy": round(safe_float(expectancy), 4),
                "tp1_hit_rate": round(safe_float(tp1_rate), 4)
            },
            "by_coin": by_coin,
            "by_exit_reason": {k: round(safe_float(v), 4) for k, v in by_exit.items()},
            "friction": {
                "avg_fee_per_trade": round(safe_float(avg_fee), 4),
                "avg_slip_per_trade": round(safe_float(avg_slippage), 4),
                "total_friction_cost": round(safe_float(total_friction), 4)
            },
            "time_analysis": {
                "avg_hold_wins_min": round(safe_float(avg_hold_wins), 2),
                "avg_hold_losses_min": round(safe_float(avg_hold_losses), 2)
            }
        }

    def generate_adaptations(self):
        """Generate parameter adaptation recommendations based on performance."""
        cycles_df = self._get_cycles()
        if cycles_df.empty:
            return {"recommendations": ["Not enough data for adaptations."]}
            
        recs = {}
        wins = cycles_df[cycles_df['is_win']]
        losses = cycles_df[~cycles_df['is_win']]
        
        # 1. Friction drag check
        total_gross_wins = wins['gross_pnl'].sum() if not wins.empty else 0
        total_friction = cycles_df['total_fees'].sum() + cycles_df['total_slippage'].sum()
        if total_gross_wins > 0 and total_friction > (0.4 * total_gross_wins):
            recs["friction_high"] = f"Fee+Slippage (${total_friction:.2f}) > 40% of gross wins (${total_gross_wins:.2f}). REDUCIR frecuencia de trades (subir min_score)."
            
        # 2. SL Exits check  
        sl_count = cycles_df[cycles_df['exit_reason'] == 'Stop Loss'].shape[0]
        sl_pct = sl_count / len(cycles_df)
        if sl_pct > 0.5:
            recs["sl_too_frequent"] = f"SL exits = {sl_pct:.0%} de trades. Ampliar SL o endurecer criterios de entrada."
            
        # 3. Coin consecutive losses
        cycles_asc = cycles_df.sort_values('entry_time', ascending=True)
        coin_recs = []
        for symbol, group in cycles_asc.groupby('symbol'):
            last_3 = group.tail(3)
            if len(last_3) >= 3 and not last_3['is_win'].any():
                coin_recs.append(f"{symbol} (3+ pérdidas consecutivas -> blacklist 12h)")
        if coin_recs:
            recs["coin_blacklist"] = coin_recs

        # 4. TP1 success rate
        tp1_rate = cycles_df['had_tp1'].mean() if 'had_tp1' in cycles_df.columns else 0
        if tp1_rate < 0.30:
            recs["tp1_too_ambitious"] = f"Solo {tp1_rate:.0%} de trades alcanzan TP1. Considerar bajar TP1 a +1.20%."

        # 5. Hold time for losers
        avg_hold_losses = losses['hold_duration_min'].mean() if not losses.empty else 0
        if 0 < avg_hold_losses < 5:
            recs["late_entries"] = f"Avg hold losers = {avg_hold_losses:.1f}m (< 5m). Entradas tardías; usar órdenes LIMIT."
            
        # 6. Overall win rate
        win_rate = len(wins) / len(cycles_df) if not cycles_df.empty else 0
        if win_rate < 0.45:
            recs["low_winrate"] = f"Win rate = {win_rate:.0%} (< 45%). Subir min_score_required +2.0."
            
        return recs

    def get_pnl_audit(self):
        """Returns a list of dicts representing completed trade cycles for P&L audit dashboard."""
        cycles_df = self._get_cycles()
        if cycles_df.empty:
            return []
            
        # We need a running total, so sort ascending first
        cycles_df = cycles_df.sort_values('exit_time', ascending=True)
        cycles_df['cumulative_pnl'] = cycles_df['net_pnl'].cumsum()
        
        # Sort back to most recent first
        cycles_df = cycles_df.sort_values('exit_time', ascending=False)
        
        audit_logs = []
        for _, row in cycles_df.iterrows():
            pnl = row['net_pnl']
            if pnl > 0:
                verdict = '🟢 Ganancia'
            elif pnl < 0:
                verdict = '🔴 Pérdida'
            else:
                verdict = '⚪ Break-Even'
                
            audit_logs.append({
                'symbol': row['symbol'],
                'entry_time': str(row['entry_time']),
                'exit_time': str(row['exit_time']),
                'entry_price': round(safe_float(row['entry_price']), 5),
                'exit_price': round(safe_float(row['exit_price']), 5),
                'direction': str(row['direction']),
                'net_pnl': round(safe_float(pnl), 4),
                'fees': round(safe_float(row['total_fees']), 4),
                'slippage': round(safe_float(row['total_slippage']), 4),
                'exit_reason': str(row['exit_reason']),
                'hold_duration_min': round(safe_float(row['hold_duration_min']), 2),
                'cumulative_pnl': round(safe_float(row['cumulative_pnl']), 4),
                'verdict': verdict
            })
            
        return audit_logs

if __name__ == "__main__":
    # Test execution
    print("=== Paper Trading Bot Self-Evaluation ===")
    auditor = TradeAuditor(logs_dir=r"c:\Users\Dell\Desktop\bot grok\paper_logs")
    
    # Check if directory and file exists, if not use current dir
    if not os.path.exists(auditor.trades_path):
        print(f"Warning: {auditor.trades_path} not found. Creating a dummy file for testing.")
        os.makedirs(auditor.logs_dir, exist_ok=True)
        # Create a tiny dummy dataset for testing if none exists
        with open(auditor.trades_path, "w") as f:
            f.write("timestamp,symbol,strategy,side,price,amount,pnl,fee,slippage,extra_info,position_id,status\n")
            f.write('2023-10-01 10:00:00,BTCUSDT,long,buy,30000,0.1,0,1.5,1.0,"{""pid_stage"": ""launchpad""}",pos_1,OPEN\n')
            f.write('2023-10-01 10:30:00,BTCUSDT,long_exit,sell,31000,0.1,100,1.5,1.0,"{""exit_reason"": ""TP""}",pos_1,CLOSED\n')
    
    # 1. Evaluation
    print("\n--- Last 10 Trades Evaluation ---")
    eval_report = auditor.evaluate_last_n_trades(10)
    print(json.dumps(eval_report, indent=2))
    
    # 2. Adaptations
    print("\n--- Adaptive Recommendations ---")
    adaptations = auditor.generate_adaptations()
    for k, v in adaptations.items():
        if isinstance(v, list):
            print(f"- {k}:")
            for item in v:
                print(f"  * {item}")
        else:
            print(f"- {k}: {v}")
            
    # 3. P&L Audit
    print("\n--- P&L Audit Summary (Latest 3) ---")
    audit = auditor.get_pnl_audit()
    for row in audit[:3]:
        print(f"{row['exit_time']} | {row['symbol']} | PnL: ${row['net_pnl']} | {row['verdict']} | Reason: {row['exit_reason']}")
