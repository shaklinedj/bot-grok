with open("server/templates.py", "r", encoding="utf-8") as f:
    text = f.read()

lines = text.splitlines()
for idx, l in enumerate(lines):
    if any(k in l for k in ["buda-trades", "buda-pnl", "buda-equity", "trades_completed", "Fills"]):
        print(f"{idx+1}: {l.strip()}")
