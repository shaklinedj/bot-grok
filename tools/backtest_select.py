"""Selección de moneda: universo amplio, ranking por volatilidad/volumen de la última hora (sin mirar el futuro).
Entrena 14d / prueba 7d. Entrada taker tras vela verde; target 0.5-1.0%, stop, tiempo."""
import itertools, os, pickle, time
import ccxt, numpy as np

U = ["SOL","SUI","NEAR","INJ","AVAX","LINK","UNI","DOGE","ADA","DOT","XRP","SHIB","PEPE","WIF","FET","RUNE","APT","ARB","OP","TIA","SEI","AAVE","LTC","ATOM","TRX","FIL","RENDER","TAO","ENA","WLD","JUP","ORDI","BONK","FLOKI","NEO"]
CACHE = os.path.join(os.environ.get("TEMP", "."), "bt_wide.pkl")
FEE, TSLIP, SSLIP = 0.0005, 0.0002, 0.0010
DAYS = 21

def load():
    if os.path.exists(CACHE):
        return pickle.load(open(CACHE, "rb"))
    ex = ccxt.binance({"enableRateLimit": True}); end = int(time.time()*1000); start = end - DAYS*86400000
    d = {}
    for s in U:
        try:
            rows, t = [], start
            while t < end:
                b = ex.fetch_ohlcv(f"{s}/USDT", "1m", since=t, limit=1000)
                if not b: break
                rows += b; t = b[-1][0] + 60000
            if len(rows) > 25000: d[s] = np.array(rows, float)
        except Exception as e:
            print("skip", s, e)
    pickle.dump(d, open(CACHE, "wb")); return d

def roll(x, k):
    c = np.cumsum(np.insert(x, 0, 0.0)); out = np.full(len(x), np.nan); out[k-1:] = (c[k:] - c[:-k]) / k; return out

def trade(a, i, tgt, stp, hold):
    n = len(a); entry = a[i, 4] * (1 + TSLIP); j0 = i + 1; end = min(n-1, j0+hold)
    if j0 > end: return None
    lo, hi = a[j0:end+1, 3], a[j0:end+1, 2]; sl, tp = entry*(1-stp), entry*(1+tgt)
    s = np.flatnonzero(lo <= sl); t = np.flatnonzero(hi >= tp)
    si = s[0] if len(s) else 10**9; ti = t[0] if len(t) else 10**9
    if si == ti == 10**9: return a[end, 4]*(1 - SSLIP/2)/entry - 1 - 2*FEE
    return (sl*(1-SSLIP)/entry - 1 - 2*FEE) if si <= ti else tgt - 2*FEE

def main():
    d = load(); syms = list(d); print("monedas:", len(syms))
    L = min(len(a) for a in d.values()); T = {s: d[s][-L:] for s in syms}
    ts = T[syms[0]][:, 0]; cut = ts[0] + (ts[-1]-ts[0])*2/3
    vol = {s: roll((T[s][:,2]-T[s][:,3])/T[s][:,4], 60) for s in syms}           # volatilidad 1h
    qv = {s: roll(T[s][:,5]*T[s][:,4], 60) for s in syms}                         # volumen USDT 1h
    V = np.vstack([vol[s] for s in syms]); Q = np.vstack([qv[s] for s in syms])
    rankV = (-np.nan_to_num(V, nan=-1)).argsort(0).argsort(0); rankQ = (-np.nan_to_num(Q, nan=-1)).argsort(0).argsort(0)
    sels = {"todas(azar)": lambda k: np.ones(len(syms), bool),
            "top5 volatilidad 1h": lambda k: rankV[:, k] < 5,
            "top5 volumen 1h": lambda k: rankQ[:, k] < 5,
            "top5 vol Y top15 volumen": lambda k: (rankV[:, k] < 5) & (rankQ[:, k] < 15)}
    exits = list(itertools.product((0.005, 0.007, 0.01), (0.007, 0.012, 0.02), (30, 90)))
    for name, fn in sels.items():
        ev = []
        last = {s: -999 for s in range(len(syms))}
        for k in range(80, L-130, 3):
            m = fn(k)
            for si in np.flatnonzero(m):
                a = T[syms[si]]
                if a[k, 4] > a[k, 1] and k - last[si] >= 20:
                    ev.append((ts[k], si, k)); last[si] = k
        res = []
        for tgt, stp, hold in exits:
            tr, te = [], []
            for t0, si, k in ev:
                r = trade(T[syms[si]], k, tgt, stp, hold)
                if r is not None: (tr if t0 < cut else te).append(r)
            res.append((np.mean(tr)*100, len(tr), np.mean(te)*100, len(te), np.mean(np.array(te) > 0)*100, tgt, stp, hold))
        res.sort(reverse=True); b = res[0]
        print(f"{name:28s} mejor train {b[0]:+.3f}% (n={b[1]}) -> TEST {b[2]:+.3f}% (n={b[3]}, win {b[4]:.0f}%) tgt {b[5]*100:.1f} stop {b[6]*100:.1f} hold {b[7]} | test medio de todas {np.mean([r[2] for r in res]):+.3f}%", flush=True)

main()
