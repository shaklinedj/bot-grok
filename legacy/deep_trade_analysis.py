import sqlite3
import json
import math
import random
from datetime import datetime

con = sqlite3.connect('swing_logs/paper/swing_vault.db')
cur = con.cursor()

# Get all trades
rows = cur.execute('SELECT id, timestamp, symbol, side, price, amount, capital, pnl, fee, note, target_price, stop_price FROM trades ORDER BY id ASC').fetchall()

completed = []
current_buys = {}

for r in rows:
    trade_id, ts, sym, side, price, amount, cap, pnl, fee, note, target, stop = r
    if side == 'BUY':
        current_buys[sym] = r
    elif side == 'SELL':
        buy = current_buys.pop(sym, None)
        entry_p = buy[4] if buy else price
        entry_ts = buy[1] if buy else ts
        completed.append({
            'sell_id': trade_id,
            'entry_time': entry_ts,
            'exit_time': ts,
            'symbol': sym,
            'entry_price': entry_p,
            'exit_price': price,
            'capital': cap,
            'pnl_usdt': pnl,
            'pnl_pct': (pnl / cap * 100) if cap else 0,
            'target_price': target,
            'stop_price': stop,
            'note': ''.join(c for c in (note or '') if ord(c) < 128)
        })

print(f"TOTAL COMPLETED TRADES ANALYZED: {len(completed)}")

# Stats
wins = [c for c in completed if c['pnl_usdt'] > 0]
losses = [c for c in completed if c['pnl_usdt'] < 0]
breakevens = [c for c in completed if c['pnl_usdt'] == 0]

win_rate = len(wins) / len(completed) * 100 if completed else 0
total_pnl = sum(c['pnl_usdt'] for c in completed)
avg_win = sum(c['pnl_usdt'] for c in wins) / len(wins) if wins else 0
avg_loss = sum(c['pnl_usdt'] for c in losses) / len(losses) if losses else 0
payoff_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
profit_factor = sum(c['pnl_usdt'] for c in wins) / abs(sum(c['pnl_usdt'] for c in losses)) if losses else 0
ev = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss)

print("\n" + "="*70)
print("METRICAS GLOBALES REALES DEL HISTORICO:")
print(f"Total Trades: {len(completed)} | Wins: {len(wins)} | Losses: {len(losses)} | BE: {len(breakevens)}")
print(f"Win Rate: {win_rate:.2f}%")
print(f"Ganancia Promedio (Win): +{avg_win:.4f} USDT")
print(f"Perdida Promedio (Loss): {avg_loss:.4f} USDT")
print(f"Payoff Ratio (Win/Loss): {payoff_ratio:.2f}:1")
print(f"Profit Factor: {profit_factor:.2f}")
print(f"Expected Value (EV por trade): {ev:+.4f} USDT")
print(f"PnL Neto Total: {total_pnl:+.4f} USDT")
print("="*70)

# Categorize trades
stop_losses = [c for c in completed if 'STOP' in c['note']]
be_trades = [c for c in completed if 'BREAK-EVEN' in c['note']]
trailing_trades = [c for c in completed if 'TRAILING' in c['note']]
target_trades = [c for c in completed if 'TARGET' in c['note']]

print(f"\nDESGLOSE POR ARQUITECTURA DE SALIDA:")
print(f"1. Stops Defensivos: {len(stop_losses)} trades | PnL Total: {sum(c['pnl_usdt'] for c in stop_losses):+.2f} USDT | Prom: {sum(c['pnl_usdt'] for c in stop_losses)/len(stop_losses):+.2f}")
if be_trades:
    print(f"2. Break-Even:       {len(be_trades)} trades | PnL Total: {sum(c['pnl_usdt'] for c in be_trades):+.2f} USDT | Prom: {sum(c['pnl_usdt'] for c in be_trades)/len(be_trades):+.2f}")
if trailing_trades:
    print(f"3. Trailing Stops:   {len(trailing_trades)} trades | PnL Total: {sum(c['pnl_usdt'] for c in trailing_trades):+.2f} USDT | Prom: {sum(c['pnl_usdt'] for c in trailing_trades)/len(trailing_trades):+.2f}")
if target_trades:
    print(f"4. Target Profit:    {len(target_trades)} trades | PnL Total: {sum(c['pnl_usdt'] for c in target_trades):+.2f} USDT | Prom: {sum(c['pnl_usdt'] for c in target_trades)/len(target_trades):+.2f}")

# Monte Carlo Simulation of current system vs optimized system
print("\n" + "="*70)
print("SIMULACION DE MONTE CARLO (1,000 iteraciones de 50 trades cada una)")
print("Escenario A: Sistema Actual (WR 33%, Avg Win +0.47, Avg Loss -0.64)")
def run_monte_carlo(wr, avg_w, avg_l, starting_cap=63.6, n_trades=50, n_sims=1000):
    final_equities = []
    ruin_count = 0
    drawdowns = []
    
    for _ in range(n_sims):
        cap = starting_cap
        peak = cap
        max_dd = 0
        for _ in range(n_trades):
            if random.random() < wr:
                # Win with standard dev variation
                pnl = max(0.01, random.gauss(avg_w, avg_w * 0.4))
            else:
                # Loss
                pnl = -max(0.05, abs(random.gauss(abs(avg_l), abs(avg_l) * 0.3)))
            cap += pnl
            if cap > peak: peak = cap
            dd = (peak - cap) / peak * 100
            if dd > max_dd: max_dd = dd
            if cap <= 20:  # ruin threshold
                ruin_count += 1
                break
        final_equities.append(cap)
        drawdowns.append(max_dd)
    
    final_equities.sort()
    drawdowns.sort()
    med_cap = final_equities[int(n_sims * 0.5)]
    p10_cap = final_equities[int(n_sims * 0.1)]
    p90_cap = final_equities[int(n_sims * 0.9)]
    med_dd = drawdowns[int(n_sims * 0.5)]
    p95_dd = drawdowns[int(n_sims * 0.95)]
    ruin_pct = ruin_count / n_sims * 100
    return med_cap, p10_cap, p90_cap, med_dd, p95_dd, ruin_pct

med_a, p10_a, p90_a, dd_med_a, dd_95_a, ruin_a = run_monte_carlo(win_rate/100, avg_win, avg_loss)
print(f"Resultados Escenario Actual:")
print(f"  - Capital Mediano a 50 trades: ${med_a:.2f} (P10: ${p10_a:.2f} | P90: ${p90_a:.2f})")
print(f"  - Max Drawdown Mediano: {dd_med_a:.1f}% (P95: {dd_95_a:.1f}%)")
print(f"  - Probabilidad de Ruina (<$20): {ruin_a:.1f}%")

print("\nEscenario B: Sistema Optimizado Robusto (Filtro Regimen BTC, Score >= 84, Stop 2.0x ATR, R:R 2.2:1)")
print("Parámetros modelados: WR 48%, Avg Win +1.85 USDT, Avg Loss -0.80 USDT (Payoff 2.3:1)")
med_b, p10_b, p90_b, dd_med_b, dd_95_b, ruin_b = run_monte_carlo(0.48, 1.85, -0.80)
print(f"Resultados Escenario Optimizado:")
print(f"  - Capital Mediano a 50 trades: ${med_b:.2f} (P10: ${p10_b:.2f} | P90: ${p90_b:.2f})")
print(f"  - Max Drawdown Mediano: {dd_med_b:.1f}% (P95: {dd_95_b:.1f}%)")
print(f"  - Probabilidad de Ruina (<$20): {ruin_b:.1f}%")
print("="*70)
