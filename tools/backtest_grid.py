"""Backtest de malla (grid) de una sola moneda sobre velas 1m (90 dias), con validacion fuera de muestra.
Modelo: compras limite bajo el precio cada `step`; al llenarse se coloca venta a +step y se re-coloca la compra al ser vendida.
Conservador: relleno solo si la vela perfora 0.03% mas alla, la venta recien creada no se llena en la misma vela,
comision 0.05%/lado (Pionex, cobrada en moneda base en compras), stop a mercado con slippage 0.10%.
Uso: python tools/backtest_grid.py NEAR [DAYS]"""
import itertools, os, pickle, sys, time
import ccxt
import numpy as np

FEE, PEN, SSLIP = 0.0005, 0.0003, 0.0010
BUDGET = 70.0


def load(sym, days):
    path = os.path.join(os.environ.get("TEMP", "."), f"grid_{sym}_{days}.pkl")
    if os.path.exists(path):
        return pickle.load(open(path, "rb"))
    ex = ccxt.binance({"enableRateLimit": True})
    end = int(time.time() * 1000)
    t = end - days * 86400000
    rows = []
    while t < end:
        b = ex.fetch_ohlcv(f"{sym}/USDT", "1m", since=t, limit=1000)
        if not b:
            break
        rows += b
        t = b[-1][0] + 60000
    a = np.array(rows, dtype=float)
    pickle.dump(a, open(path, "wb"))
    return a


def run(a, step, n, stop, gap, budget=BUDGET):
    """a: [ts,o,h,l,c,v]. Devuelve dict con metricas."""
    lows, highs, closes = a[:, 3], a[:, 2], a[:, 4]
    per = budget / n
    cash = budget
    buys = []      # [price, usdt]
    sells = []     # [price, qty, cost, born_idx]
    inv_cost = 0.0
    inv_qty = 0.0
    wins = 0
    stops = 0
    pnl_cycles = 0.0
    anchor = None
    eq_samples = []

    def lay(p, i):
        nonlocal cash
        buys.clear()
        # devolver efectivo reservado
        for k in range(1, n + 1):
            bp = p * (1 - step * k)
            if cash >= per * 0.999:
                buys.append([bp, per])
                cash -= per
        return p

    # efectivo reservado en buys se descuenta de cash
    anchor = lay(closes[0], 0)
    for i in range(1, len(a)):
        lo, hi, c = lows[i], highs[i], closes[i]
        # ventas (solo las nacidas antes de esta vela)
        if sells:
            keep = []
            for s in sells:
                if s[3] < i and hi >= s[0] * (1 + PEN):
                    gross = s[1] * s[0]
                    net = gross * (1 - FEE)
                    cash += net
                    pnl_cycles += net - s[2]
                    inv_cost -= s[2]
                    inv_qty -= s[1]
                    wins += 1
                    # recolocar la compra un escalon bajo la venta
                    bp = s[0] / (1 + step)
                    if cash >= per * 0.999 and bp < c:
                        buys.append([bp, per])
                        cash -= per
                else:
                    keep.append(s)
            sells[:] = keep
        # compras
        if buys:
            keep = []
            for b in buys:
                if lo <= b[0] * (1 - PEN):
                    qty = b[1] / b[0] * (1 - FEE)
                    sells.append([b[0] * (1 + step), qty, b[1], i])
                    inv_cost += b[1]
                    inv_qty += qty
                else:
                    keep.append(b)
            buys[:] = keep
        # stop de la malla: precio por debajo del escalon mas bajo en `stop`
        if stop and sells:
            worst = min(s[0] / (1 + step) for s in sells)
            if c <= worst * (1 - stop):
                px = c * (1 - SSLIP)
                net = inv_qty * px * (1 - FEE)
                pnl_cycles += net - inv_cost
                cash += net + sum(b[1] for b in buys)
                buys.clear(); sells.clear()
                inv_cost = inv_qty = 0.0
                stops += 1
                anchor = lay(c, i)
                continue
        # re-anclaje al alza: si el precio se aleja de las compras, reposicionar
        if gap and buys:
            top = max(b[0] for b in buys)
            if c > top * (1 + gap):
                cash += sum(b[1] for b in buys)
                anchor = lay(c, i)
        elif not buys and cash >= per * 0.999:
            anchor = lay(c, i)
        if i % 60 == 0:
            eq_samples.append(cash + sum(b[1] for b in buys) + inv_qty * c)
    final = cash + sum(b[1] for b in buys) + inv_qty * closes[-1]
    eq = np.array(eq_samples)
    dd = float(np.max(np.maximum.accumulate(eq) - eq) / budget * 100) if len(eq) else 0.0
    days = len(a) / 1440
    return {"ret_pct": (final / budget - 1) * 100, "cycles": wins, "stops": stops, "dd": dd,
            "per_day": (final - budget) / days, "cycle_pnl": pnl_cycles, "open_inv": inv_qty * closes[-1],
            "avg_cycle": pnl_cycles / wins if wins else 0.0}


def main():
    sym = sys.argv[1] if len(sys.argv) > 1 else "NEAR"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 90
    a = load(sym, days)
    cut = int(len(a) * 2 / 3)
    tr, te = a[:cut], a[cut:]
    bh = lambda x: (x[-1, 4] / x[0, 4] - 1) * 100
    print(f"{sym}: {len(a)} velas  buy&hold  total {bh(a):+.1f}%  train {bh(tr):+.1f}%  test {bh(te):+.1f}%")
    res = []
    for step, n, stop, gap in itertools.product((0.004, 0.006, 0.008, 0.012, 0.016, 0.025),
                                                 (1, 2, 3, 5, 8), (0, 0.03, 0.06), (0, 0.01, 0.02)):
        r1 = run(tr, step, n, stop, gap)
        r2 = run(te, step, n, stop, gap)
        res.append((step, n, stop, gap, r1, r2))
    res.sort(key=lambda x: -x[4]["ret_pct"])
    print("\nTOP 15 por ENTRENAMIENTO (con su resultado en PRUEBA):")
    print("step  n  stop  gap |  train ret  dd  ciclos | test ret   dd  ciclos  $/dia  $/ciclo  stops")
    for step, n, stop, gap, r1, r2 in res[:15]:
        print(f"{step*100:4.1f} {n:2d} {stop*100:4.0f} {gap*100:4.0f} | {r1['ret_pct']:+7.2f} {r1['dd']:5.1f} {r1['cycles']:5d} | "
              f"{r2['ret_pct']:+7.2f} {r2['dd']:5.1f} {r2['cycles']:5d} {r2['per_day']:+6.3f} {r2['avg_cycle']:6.3f} {r2['stops']:3d}")
    pos = [x for x in res if x[4]["ret_pct"] > 0 and x[5]["ret_pct"] > 0]
    print(f"\nconfigs positivas en train Y test: {len(pos)} de {len(res)}")
    print(f"media test de todas: {np.mean([x[5]['ret_pct'] for x in res]):+.2f}%   mediana: {np.median([x[5]['ret_pct'] for x in res]):+.2f}%")


def multi(syms, days):
    cfgs = [(0.008, 3, 0.06, 0.01), (0.012, 3, 0.0, 0.02), (0.012, 3, 0.06, 0.02), (0.016, 2, 0.06, 0.02),
            (0.006, 5, 0.06, 0.01), (0.012, 1, 0.05, 0.02), (0.012, 1, 0.03, 0.02)]
    print("moneda  periodo  B&H   | " + " | ".join(f"s{c[0]*100:.1f} n{c[1]} st{c[2]*100:.0f} g{c[3]*100:.0f}" for c in cfgs))
    for sym in syms:
        a = load(sym, days)
        for name, x in (("1er tercio", a[:len(a)//3]), ("2do tercio", a[len(a)//3:2*len(a)//3]), ("3er tercio", a[2*len(a)//3:])):
            row = [f"{(x[-1,4]/x[0,4]-1)*100:+6.1f}"]
            for c in cfgs:
                r = run(x, *c)
                row.append(f"{r['ret_pct']:+5.1f}/dd{r['dd']:4.0f}/{r['cycles']:3d}c")
            print(f"{sym:5s} {name} " + row[0] + " | " + " | ".join(row[1:]))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "multi":
        multi(sys.argv[3].split(","), int(sys.argv[2]))
    else:
        main()
