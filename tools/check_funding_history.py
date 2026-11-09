import os, ccxt
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()

ex = ccxt.binance({
    'apiKey': os.environ.get('BINANCE_API_KEY'),
    'secret': os.environ.get('BINANCE_API_SECRET'),
    'options': {'defaultType': 'future'}
})

try:
    income = ex.fapiPrivateGetIncome({'incomeType': 'FUNDING_FEE', 'limit': 30})
    print(f'Total income records: {len(income)}')
    tot = 0.0
    for r in income:
        val = float(r.get('income', 0))
        tot += val
        ts = int(r.get('time', 0)) / 1000.0
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        print(f"Fecha: {dt} | Simbolo: {r.get('symbol')} | Pago: {val:+.6f} {r.get('asset')}")
    print(f'Total real funding cobrado: {tot:+.6f} USDT')
except Exception as e:
    print('Error:', e)
