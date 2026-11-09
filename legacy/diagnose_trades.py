import sqlite3
import json

con = sqlite3.connect('swing_logs/paper/swing_vault.db')
cur = con.cursor()

# Get state
state = dict(cur.execute("SELECT key, val_json FROM bot_state").fetchall())
cash = float(state.get('cash', 0))
active_trade = json.loads(state.get('active_trade', 'null'))

print("="*60)
print(f"CASH ACTUAL: {cash:.2f} USDT")
if active_trade:
    print(f"OPERACION ABIERTA: {active_trade.get('symbol')} | Cap: {active_trade.get('capital')} | Entry: {active_trade.get('entry_price')} | Stop: {active_trade.get('stop_price')}")
    total_val = cash + active_trade.get('capital', 0)
    print(f"VALOR TOTAL ESTIMADO DE LA CUENTA: {total_val:.2f} USDT")
else:
    print("SIN OPERACION ABIERTA")

rows = cur.execute("SELECT id, timestamp, symbol, side, price, amount, capital, pnl, fee, note FROM trades WHERE side='SELL' ORDER BY id ASC").fetchall()
print("="*60)
print(f"TOTAL VENTAS REGISTRADAS: {len(rows)}")
total_pnl = sum(r[7] for r in rows)
wins = [r for r in rows if r[7] > 0]
losses = [r for r in rows if r[7] <= 0]
print(f"PNL NETO TOTAL: {total_pnl:+.4f} USDT | WINS: {len(wins)} | LOSSES: {len(losses)}")
if len(rows) > 0:
    win_rate = (len(wins) / len(rows)) * 100
    print(f"WIN RATE: {win_rate:.1f}%")

print("\n--- ULTIMOS 15 TRADES CERRADOS ---")
for r in rows[-15:]:
    clean_note = ''.join(c for c in (r[9] or '') if ord(c) < 128)
    print(f"#{r[0]:<3} | {r[1][:19]} | {r[2]:<10} | PnL: {r[7]:+6.2f} USDT | Cap: {r[6]:5.2f} | {clean_note}")

# Check reasons for exit
reasons = {}
for r in rows:
    note = r[9] or ''
    tag = "OTHER"
    if "STOP" in note: tag = "STOP DEFENSIVO"
    elif "TARGET" in note: tag = "TARGET ALCANZADO"
    elif "BREAK-EVEN" in note: tag = "BREAK-EVEN"
    elif "TRAILING" in note: tag = "TRAILING STOP"
    reasons[tag] = reasons.get(tag, 0) + 1

print("\n--- DESGLOSE POR MOTIVO DE SALIDA ---")
for k, v in reasons.items():
    print(f"{k}: {v}")
