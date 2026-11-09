"""Reversion tras retrocesos moderados con giro confirmado (velas 1h, 180 dias).
La senal compartida con reversion_agent.py exige caida de 3-8%, debilidad relativa
moderada, BTC sin desplome, minimo creciente, cierre sobre el maximo previo y volumen creciente.
Entrada: apertura de la vela siguiente (taker, slip 0.05%). Salida: target (maker), stop (slip 0.10%), o tiempo (cierre).
Si stop y target caen en la misma vela, se asume stop. Comision 0.05%/lado. Sin solapar posiciones en la misma moneda."""
import itertools, os, pickle, sys, time
import ccxt
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from reversion_strategy import evaluate_rebound_signal

SYMS = ("BTC ETH SOL XRP ADA AVAX LINK DOT NEAR SUI INJ UNI LTC BCH APT ARB OP FIL AAVE "
        "TRX TON HBAR ICP ETC SEI STX ALGO XLM").split()
DAYS = 180
FEE, TSLIP, SSLIP = 0.0005, 0.0005, 0.0010
TP, STOP, HOLD_H = 0.03, 0.05, 48
CACHE = os.path.join(os.environ.get("TEMP", "."), "rev1h_cache.pkl")


def load():
    if os.path.exists(CACHE):
        return pickle.load(open(CACHE, "rb"))
    ex = ccxt.binance({"enableRateLimit": True})
    end = int(time.time() * 1000)
    start = end - DAYS * 86400000
    data = {}
    for s in SYMS:
        try:
            rows, t = [], start
            while t < end:
                b = ex.fetch_ohlcv(f"{s}/USDT", "1h", since=t, limit=1000)
                if not b:
                    break
                rows += b
                t = b[-1][0] + 3600000
            if len(rows) > 24 * 60:
                data[s] = np.array(rows, dtype=float)
        except Exception as e:
            print("skip", s, e)
    pickle.dump(data, open(CACHE, "wb"))
    return data


def signals(data):
    """Lista (ts_idx_global, sym, i) generada por las reglas del agente."""
    btc = data["BTC"]
    bmap = {int(t): j for j, t in enumerate(btc[:, 0])}
    out = []
    for s, a in data.items():
        if s not in SYMS or s == "BTC":
            continue
        for i in range(24, len(a) - 2):
            j = bmap.get(int(a[i, 0]))
            if j is None:
                continue
            signal = evaluate_rebound_signal(a, btc, i, j)
            if signal:
                out.append((int(a[i, 0]), s, i))
    out.sort()
    return out


def simulate(data, sigs, tp, stop, hold):
    busy = {}
    res = []
    for ts, s, i in sigs:
        if busy.get(s, -1) >= i:
            continue
        a = data[s]
        e = a[i + 1, 1] * (1 + TSLIP)
        end = min(i + 1 + hold, len(a) - 1)
        exit_p, k_end = None, end
        for j in range(i + 1, end + 1):
            lo, hi, op = a[j, 3], a[j, 2], a[j, 1]
            if stop and lo <= e * (1 - stop):
                exit_p = min(op, e * (1 - stop)) * (1 - SSLIP); k_end = j; break
            if hi >= e * (1 + tp) * 1.0003:
                exit_p = e * (1 + tp); k_end = j; break
        if exit_p is None:
            exit_p = a[end, 4] * (1 - SSLIP / 2)
        # compra: la comision se cobra en la moneda base, equivale a ~FEE sobre el nocional
        r = exit_p * (1 - FEE) / (e * (1 + 0.0)) - 1 - FEE
        busy[s] = k_end
        res.append((ts, r))
    return res


def stats(res):
    if not res:
        return None
    r = np.array([x[1] for x in res])
    days = len({int(x[0] // 86400000) for x in res})
    return len(r), r.mean() * 100, (r > 0).mean() * 100, r.sum() * 100, days


def main():
    data = load()
    print("monedas:", len(data), "velas BTC:", len(data["BTC"]))
    t0 = data["BTC"][0, 0]
    t1 = data["BTC"][-1, 0]
    cut = t0 + (t1 - t0) * 2 / 3
    rows = []
    sg = signals(data)
    tr = [q for q in sg if q[0] < cut]
    te = [q for q in sg if q[0] >= cut]
    for tp, stop, hold in itertools.product(
        (0.02, 0.03, 0.05, 0.08), (0.0, 0.04, 0.05, 0.08), (24, 48, 96)
    ):
        a, b = stats(simulate(data, tr, tp, stop, hold)), stats(simulate(data, te, tp, stop, hold))
        if a and b and a[0] >= 20:
            rows.append((tp, stop, hold, a, b))
    rows.sort(key=lambda r: -r[3][1])
    print(f"\nconfigs evaluadas: {len(rows)}")
    print("tp   stop hold | TRAIN n  media%  win%  dias | TEST n  media%  win%  suma%  dias")
    for tp, stop, hold, a, b in rows[:20]:
        print(f"{tp*100:3.0f}% {stop*100:3.0f}% {hold:3d} | {a[0]:5d} {a[1]:+6.2f} {a[2]:5.1f} {a[4]:4d} | {b[0]:4d} {b[1]:+6.2f} {b[2]:5.1f} {b[3]:+7.1f} {b[4]:4d}")
    pos = [r for r in rows if r[3][1] > 0 and r[4][1] > 0]
    print(f"\npositivas en train Y test: {len(pos)} de {len(rows)}")
    print(f"senales: train={len(tr)}, test={len(te)}")
    print(f"media del test de TODAS: {np.mean([r[4][1] for r in rows]):+.3f}% por trade ; de las top-20 por train: {np.mean([r[4][1] for r in rows[:20]]):+.3f}%")
    baseline = next((r for r in rows if r[:3] == (TP, STOP, HOLD_H)), None)
    if baseline:
        print(f"config del agente (tp={TP:.0%}, stop={STOP:.0%}, hold={HOLD_H}h): "
              f"train {baseline[3][1]:+.2f}% ({baseline[3][0]} trades), "
              f"test {baseline[4][1]:+.2f}% ({baseline[4][0]} trades)")
    if pos:
        pos.sort(key=lambda r: -(min(r[3][1], r[4][1])))
        print("\nMejores por min(train,test):")
        for tp, stop, hold, a, b in pos[:10]:
            print(f"tp={tp*100:.0f}% stop={stop*100:.0f}% hold={hold}h | train {a[0]}tr {a[1]:+.2f}% | test {b[0]}tr {b[1]:+.2f}% win {b[2]:.0f}% en {b[4]} dias")


if __name__ == "__main__":
    main()
