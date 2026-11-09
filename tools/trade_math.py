import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
conn = sqlite3.connect('swing_logs/paper/swing_vault.db')
cur = conn.cursor()
cur.execute("SELECT symbol, side, capital, pnl, fee, note FROM trades WHERE side='SELL' AND pnl != 0")
rows = cur.fetchall()

wins = [r for r in rows if r[3] > 0]
losses = [r for r in rows if r[3] < 0]
win_pnls = [w[3] for w in wins]
loss_pnls = [l[3] for l in losses]
fees = [r[4] for r in rows if r[4]]

print(f"Total trades cerrados: {len(rows)}")
print(f"Wins: {len(wins)} ({len(wins)/len(rows)*100:.1f}%) | Losses: {len(losses)} ({len(losses)/len(rows)*100:.1f}%)")
print(f"Ganancia media por win:  +${sum(win_pnls)/len(win_pnls):.4f}")
print(f"Pérdida media por loss:   ${sum(loss_pnls)/len(loss_pnls):.4f}")
print(f"Total bruto ganado:      +${sum(win_pnls):.2f}")
print(f"Total bruto perdido:      ${sum(loss_pnls):.2f}")
print(f"Total comisiones (fees):   ${sum(fees):.4f}")
print(f"PnL Neto Total:           ${sum(win_pnls)+sum(loss_pnls):.4f}")
print(f"Profit Factor:            {abs(sum(win_pnls)/sum(loss_pnls)):.2f}")

print("\n--- ÚLTIMOS 12 TRADES CERRADOS ---")
for r in rows[-12:]:
    pct = (r[3] / r[2] * 100) if r[2] else 0
    print(f"{r[0]:<12} Cap: ${r[2]:>5.2f} | PnL: {r[3]:>+7.4f} ({pct:>+5.2f}%) | {r[5]}")
