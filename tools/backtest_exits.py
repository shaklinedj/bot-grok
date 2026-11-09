"""Backtest de stop/target/tiempo del scalper con velas 1m de Binance (7 días, 11 pares).
Sin libro histórico: valida la salida (stop/target), no la señal de entrada. Supuestos conservadores:
comisión 0.05%/lado, slippage de entrada 0.02%, stop con slippage extra 0.10%, si stop y target caen
en la misma vela se asume stop."""
import itertools, os, pickle, sys, time
import ccxt
import numpy as np

SYMS = ["SOL","SUI","NEAR","INJ","AVAX","LINK","UNI","DOGE","ADA","DOT","XRP"]
DAYS = 7
CACHE = os.path.join(os.environ.get("TEMP", "."), "bt_cache.pkl")
FEE, ENTRY_SLIP, STOP_SLIP = 0.0005, 0.0002, 0.0010


def load():
    if os.path.exists(CACHE):
        return pickle.load(open(CACHE, "rb"))
    ex = ccxt.binance({"enableRateLimit": True})
    since = int((time.time() - DAYS * 86400) * 1000)
    data = {}
    for s in SYMS:
        rows, t = [], since
        while True:
            b = ex.fetch_ohlcv(f"{s}/USDT", "1m", since=t, limit=1000)
            if not b:
                break
            rows += b
            t = b[-1][0] + 60000
            if len(b) < 1000:
                break
        data[s] = np.array(rows, dtype=float)
        print(s, len(rows), flush=True)
    pickle.dump(data, open(CACHE, "wb"))
    return data


def simulate(a, i, tgt, stp, hold):
    """a: [t,o,h,l,c,v]; entra al cierre de la vela i. Devuelve retorno neto."""
    entry = a[i, 4] * (1 + ENTRY_SLIP)
    tp, sl = entry * (1 + tgt), entry * (1 - stp)
    end = min(len(a) - 1, i + hold)
    for j in range(i + 1, end + 1):
        if a[j, 3] <= sl:
            return (sl * (1 - STOP_SLIP)) / entry - 1 - 2 * FEE, "S"
        if a[j, 2] >= tp:
            return tgt - 2 * FEE, "T"
    return a[end, 4] / entry - 1 - 2 * FEE, "H"


SIGNALS = {
    "baseline(cada 10m)": lambda a, i: i % 10 == 0,
    "momentum(+0.2% en 5m)": lambda a, i: a[i, 4] / a[i - 5, 4] - 1 >= 0.002 and i % 3 == 0,
    "rebote(-0.5% en 15m, vela verde)": lambda a, i: a[i, 4] / a[i - 15, 4] - 1 <= -0.005 and a[i, 4] > a[i, 1] and i % 3 == 0,
}


def main():
    data = load()
    grid = list(itertools.product([0.003, 0.004, 0.005, 0.0075, 0.0095], [0.0035, 0.005, 0.007, 0.01, 0.015], [8, 15, 30, 60]))
    for name, sig in SIGNALS.items():
        res = []
        for tgt, stp, hold in grid:
            rets, kinds = [], {"T": 0, "S": 0, "H": 0}
            for a in data.values():
                for i in range(20, len(a) - 1):
                    if sig(a, i):
                        r, k = simulate(a, i, tgt, stp, hold)
                        rets.append(r); kinds[k] += 1
            if rets:
                r = np.array(rets)
                res.append((r.mean() * 100, tgt, stp, hold, len(r), (r > 0).mean() * 100, kinds))
        res.sort(reverse=True)
        print(f"\n=== {name} ===  (expectancy neta %/trade)")
        for e in res[:5]:
            print(f"  exp {e[0]:+.3f}% | tgt {e[1]*100:.2f}% stop {e[2]*100:.2f}% hold {e[3]}m | n={e[4]} win {e[5]:.0f}% {e[6]}")
        cur = [e for e in res if (e[1], e[2], e[3]) == (0.005, 0.0035, 8)]
        old = [e for e in res if (e[1], e[2], e[3]) == (0.0095, 0.007, 30)]
        for lab, c in (("perfil RÁPIDO actual", cur), ("perfil clásico", old)):
            if c:
                e = c[0]; print(f"  [{lab}] exp {e[0]:+.3f}% n={e[4]} win {e[5]:.0f}% {e[6]}")
        print(f"  peor: exp {res[-1][0]:+.3f}% tgt {res[-1][1]*100:.2f} stop {res[-1][2]*100:.2f} hold {res[-1][3]}")


if __name__ == "__main__":
    main()
