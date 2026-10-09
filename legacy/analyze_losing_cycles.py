import csv
import json

with open('paper_logs/trades.csv', 'r', encoding='utf-8', errors='ignore') as f:
    rows = list(csv.reader(f))

positions = {}
for r in rows[1:]:
    if len(r) < 11: continue
    pid = r[10]
    if pid not in positions:
        positions[pid] = []
    positions[pid].append(r)

losing_cycles = []
for pid, events in positions.items():
    pnl_sum = sum(float(e[6]) for e in events)
    sym = events[0][1]
    if pnl_sum < 0:
        start_ts = events[0][0]
        end_ts = events[-1][0]
        exit_reason = events[-1][9] if len(events[-1]) > 9 else ''
        entry_p = float(events[0][4])
        exit_p = float(events[-1][4])
        losing_cycles.append({
            'pid': pid, 'symbol': sym, 'pnl': pnl_sum,
            'start': start_ts, 'end': end_ts,
            'entry_price': entry_p, 'exit_price': exit_p,
            'reason': exit_reason
        })

print(f"Total Losing Cycles: {len(losing_cycles)}")
print("Worst 15 losing cycles:")
for lc in sorted(losing_cycles, key=lambda x: x['pnl'])[:15]:
    print(f"  {lc['symbol']:12s} | PnL: {lc['pnl']:+.4f} | {lc['start']} -> {lc['end']} | In: {lc['entry_price']:.5f} Out: {lc['exit_price']:.5f} | {lc['reason']}")

with open('losing_cycles.json', 'w', encoding='utf-8') as f:
    json.dump(losing_cycles, f, indent=2)
