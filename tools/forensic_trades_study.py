import sqlite3
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

conn = sqlite3.connect('swing_logs/paper/swing_vault.db')
c = conn.cursor()

# Buscar los trades de entrada y salida para reconstruir la historia completa
def get_trade_details(trade_id):
    # Buscar el cierre
    c.execute('SELECT * FROM trades WHERE id = ?', (trade_id,))
    close_trade = c.fetchone()
    if not close_trade:
        return None
    
    # close_trade schema:
    # 0: id, 1: timestamp, 2: symbol, 3: side, 4: price, 5: amount, 6: capital, 7: pnl, 8: fee, 9: order_id, 10: target_price, 11: stop_price, 12: note, 13: mode, 14: parent_trade_id
    sym = close_trade[2]
    order_id = close_trade[9]
    parent_id = close_trade[14]
    
    # Buscar la entrada correspondiente
    c.execute('''
        SELECT * FROM trades 
        WHERE symbol = ? AND side = 'BUY' AND id < ?
        ORDER BY id DESC LIMIT 1
    ''', (sym, trade_id))
    entry_trade = c.fetchone()
    
    return {
        "close": close_trade,
        "entry": entry_trade
    }

# Seleccionar 3 Ganadores y 3 Perdedores representativos
winner_ids = [2, 194, 94]      # INJ (+6.4%), UNI (+4.4%), FET (+2.6%)
loser_ids = [203, 190, 84]      # HYPE, SOL, o similares de swing

print("=== RECONSTRUCCIÓN FORENSE DE 3 TRADES GANADORES Y 3 PERDEDORES ===")

print("\n" + "="*80)
print("1. TRADES GANADORES SELECCIONADOS")
print("="*80)
for wid in winner_ids:
    d = get_trade_details(wid)
    cl = d["close"]
    en = d["entry"]
    print(f"\n🟢 GANADOR: {cl[2]} (ID Salida: {cl[0]})")
    if en:
        print(f"  • Entrada:  Fecha: {en[1]} | Precio: ${en[4]:.4f} | Capital: ${en[6]:.2f}")
        print(f"  • Setup:    {en[12]}")
    print(f"  • Salida:   Fecha: {cl[1]} | Precio: ${cl[4]:.4f} | PnL: +${cl[7]:.4f} USD")
    print(f"  • Razón:    {cl[12]}")

print("\n" + "="*80)
print("2. TRADES PERDEDORES SELECCIONADOS")
print("="*80)

# Encontrar 3 perdedores netos en Swing
c.execute('''
    SELECT id FROM trades 
    WHERE side = 'SELL' AND mode != 'BOUNDED_GRID' AND pnl < -0.30
    ORDER BY id DESC LIMIT 5
''')
bad_candidates = [r[0] for r in c.fetchall()]
for lid in bad_candidates[:3]:
    d = get_trade_details(lid)
    cl = d["close"]
    en = d["entry"]
    print(f"\n🔴 PERDEDOR: {cl[2]} (ID Salida: {cl[0]})")
    if en:
        print(f"  • Entrada:  Fecha: {en[1]} | Precio: ${en[4]:.4f} | Capital: ${en[6]:.2f}")
        print(f"  • Setup:    {en[12]}")
    print(f"  • Salida:   Fecha: {cl[1]} | Precio: ${cl[4]:.4f} | PnL: ${cl[7]:.4f} USD")
    print(f"  • Razón:    {cl[12]}")
