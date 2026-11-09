"""Búsqueda de ventaja con validación fuera de muestra (21 días de velas 1m, 11 pares).
Entrenamiento = primeros 2/3 del tiempo, prueba = último 1/3. Se elige SOLO con entrenamiento y se reporta la prueba.
Entrada taker (cruza, slip 0.02%) o maker (límite al cierre; se llena solo si la vela siguiente perfora 0.02% más abajo).
Salida: target maker, stop a mercado con slip 0.10%, tiempo a mercado. Comisión 0.05%/lado."""
import itertools, os, pickle, time
import ccxt
import numpy as np

SYMS = ["SOL","SUI","NEAR","INJ","AVAX","LINK","UNI","DOGE","ADA","DOT","XRP"]
DAYS = 21
CACHE = os.path.join(os.environ.get("TEMP", "."), f"bt21_cache.pkl")
FEE, TSLIP, SSLIP = 0.0005, 0.0002, 0.0010


def load():
    if os.path.exists(CACHE):
        return pickle.load(open(CACHE, "rb"))
    ex = ccxt.binance({"enableRateLimit": True})
    end = int(time.time() * 1000)
    start = end - DAYS * 86400000
    data = {}
    for s in SYMS:
        rows, t = [], start
        while t < end:
            b = ex.fetch_ohlcv(f"{s}/USDT", "1m", since=t, limit=1000)
            if not b:
                break
            rows += b
            t = b[-1][0] + 60000
        a = np.array(rows, dtype=float)
        n = (len(a) // 1) * 1
        data[s] = a[:n]
        print(s, len(a), flush=True)
    pickle.dump(data, open(CACHE, "wb"))
    return data


def feats(a):
    c, o, v = a[:, 4], a[:, 1], a[:, 5]
    n = len(a)
    def ret(k):
        r = np.full(n, np.nan); r[k:] = c[k:] / c[:-k] - 1; return r
    vm = np.convolve(v, np.ones(30) / 30, mode="full")[:n]
    vs = np.where(vm > 0, v / np.maximum(vm, 1e-12), 1.0); vs[:30] = np.nan
    return {"r5": ret(5), "r15": ret(15), "r60": ret(60), "vs": vs, "green": (c > o).astype(float),
            "rng": (a[:, 2] - a[:, 3]) / c}


def build_signals():
    sigs = {}
    for x in (0.005, 0.008, 0.012, 0.02):
        for vs in (0.0, 2.0):
            for g in (0, 1):
                sigs[f"caida15<=-{x*100:.1f}% vol>={vs:.0f} verde={g}"] = (
                    lambda f, x=x, vs=vs, g=g: (f["r15"] <= -x) & (f["vs"] >= vs) & ((f["green"] == 1) | (g == 0)))
    for x in (0.01, 0.02):
        sigs[f"caida60<=-{x*100:.0f}% verde"] = lambda f, x=x: (f["r60"] <= -x) & (f["green"] == 1)
    sigs["momentum r5>=0.3% vol>=2"] = lambda f: (f["r5"] >= 0.003) & (f["vs"] >= 2.0)
    return sigs


def trade(a, i, mode, tgt, stp, hold):
    n = len(a)
    if mode == "maker":
        if i + 1 >= n or a[i + 1, 3] > a[i, 4] * (1 - 0.0002):
            return None
        entry, j0 = a[i, 4], i + 1
    else:
        entry, j0 = a[i, 4] * (1 + TSLIP), i + 1
    end = min(n - 1, j0 + hold)
    if j0 > end:
        return None
    lo, hi = a[j0:end + 1, 3], a[j0:end + 1, 2]
    sl, tp = entry * (1 - stp), entry * (1 + tgt)
    s = np.flatnonzero(lo <= sl); t = np.flatnonzero(hi >= tp)
    si = s[0] if len(s) else 10 ** 9; ti = t[0] if len(t) else 10 ** 9
    if si == 10 ** 9 and ti == 10 ** 9:
        return a[end, 4] * (1 - SSLIP / 2) / entry - 1 - 2 * FEE
    if si <= ti:
        return sl * (1 - SSLIP) / entry - 1 - 2 * FEE
    return tgt - 2 * FEE


def collect(data, sigs):
    out = {}
    for name, fn in sigs.items():
        per = []
        for sym, a in data.items():
            f = feats(a)
            with np.errstate(invalid="ignore"):
                m = fn(f)
            idx = np.flatnonzero(m)
            last = -10 ** 9
            for i in idx:
                if i - last >= 15 and i > 70:
                    per.append((a[i, 0], sym, i)); last = i
        out[name] = per
    return out


def main():
    data = load()
    t_min = min(a[0, 0] for a in data.values()); t_max = max(a[-1, 0] for a in data.values())
    cut = t_min + (t_max - t_min) * 2 / 3
    sigs = build_signals()
    ev = collect(data, sigs)
    exits = list(itertools.product((0.004, 0.006, 0.009, 0.013), (0.007, 0.01, 0.015, 0.025), (15, 45, 120)))
    rows = []
    for name, evs in ev.items():
        for mode in ("taker", "maker"):
            for tgt, stp, hold in exits:
                tr, te = [], []
                for ts, sym, i in evs:
                    r = trade(data[sym], i, mode, tgt, stp, hold)
                    if r is not None:
                        (tr if ts < cut else te).append(r)
                if len(tr) >= 150:
                    rows.append((np.mean(tr) * 100, len(tr), np.mean(te) * 100 if te else float("nan"), len(te),
                                 np.mean(np.array(te) > 0) * 100 if te else 0, name, mode, tgt, stp, hold))
    rows.sort(key=lambda r: -r[0])
    print(f"configs evaluadas: {len(rows)} | corte entrenamiento/prueba en {time.strftime('%m-%d %H:%M', time.localtime(cut/1000))}")
    print("\nTOP 15 por ENTRENAMIENTO (y su resultado en PRUEBA, no vista):")
    for r in rows[:15]:
        print(f" train {r[0]:+.3f}% (n={r[1]}) -> TEST {r[2]:+.3f}% (n={r[3]}, win {r[4]:.0f}%) | {r[5]} | {r[6]} tgt {r[7]*100:.1f} stop {r[8]*100:.1f} hold {r[9]}")
    top = rows[:50]
    te = np.array([r[2] for r in top if r[3] >= 50])
    print(f"\nPromedio TEST de las 50 mejores en train: {np.nanmean(te):+.3f}%  | positivas en test: {(te > 0).mean()*100:.0f}%")
    pos = [r for r in rows if r[0] > 0 and r[2] > 0 and r[3] >= 100]
    print(f"Configs positivas en train Y test (n_test>=100): {len(pos)} de {len(rows)}")
    for r in sorted(pos, key=lambda r: -(min(r[0], r[2])))[:8]:
        print(f" train {r[0]:+.3f}% test {r[2]:+.3f}% (n={r[3]}) | {r[5]} | {r[6]} tgt {r[7]*100:.1f} stop {r[8]*100:.1f} hold {r[9]}")


if __name__ == "__main__":
    main()
