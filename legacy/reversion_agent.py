"""Reversion Agent (PAPER ONLY): busca caidas moderadas y giro confirmado en monedas liquidas.
No intenta anticipar el minimo ni envia ordenes reales.
Uso: python reversion_agent.py [--reset] [--once]   (dashboard en http://127.0.0.1:8877)"""
import json, os, sys, threading, time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import ccxt
import numpy as np
from reversion_strategy import evaluate_rebound_signal

SYMS = ("ETH SOL XRP ADA AVAX LINK DOT NEAR SUI INJ UNI LTC BCH APT ARB OP FIL AAVE "
        "TRX TON HBAR ICP ETC SEI STX ALGO XLM").split()
CAPITAL0 = 70.0
STAKE = 35.0
MAX_POS = 2
TP, STOP, HOLD_H = 0.03, 0.05, 48
FEE, TSLIP, SSLIP = 0.0005, 0.0005, 0.0010
PORT = 8877
DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reversion_logs")
STATE = os.path.join(DIR, "state.json")
TRADES = os.path.join(DIR, "trades.jsonl")
ex = ccxt.binance({"enableRateLimit": True})
LOCK = threading.Lock()
state = {"cash": CAPITAL0, "positions": [], "closed": 0, "wins": 0, "pnl": 0.0, "last_scan": "", "last_candidates": []}


def save():
    os.makedirs(DIR, exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, STATE)


def load():
    if os.path.exists(STATE):
        state.update(json.load(open(STATE, encoding="utf-8")))


def candles(sym, n=800):
    b = ex.fetch_ohlcv(f"{sym}/USDT", "1h", limit=n)
    return np.array(b[:-1], dtype=float)  # descarta la vela en curso


def scan():
    """Busca retrocesos moderados con confirmacion alcista y volumen."""
    btc = candles("BTC")
    out = []
    for s in SYMS:
        try:
            a = candles(s)
            if len(a) < 25 or a[-1, 0] != btc[-1, 0]:
                continue
            signal = evaluate_rebound_signal(a, btc)
            if signal:
                out.append({
                    "sym": s,
                    "r24": round(signal["r24"] * 100, 2),
                    "btc_r24": round(signal["btc_r24"] * 100, 2),
                    "idio": round(signal["idio"] * 100, 2),
                    "volume_ratio": round(signal["volume_ratio"], 2),
                    "quote_volume_24h": round(signal["quote_volume_24h"]),
                    "rebound_pct": round(signal["rebound_pct"] * 100, 2),
                })
        except Exception as e:
            print(f"[scan] {s}: {e}", flush=True)
    out.sort(key=lambda d: (d["rebound_pct"], d["volume_ratio"]), reverse=True)
    return out


def log_trade(rec):
    with open(TRADES, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def open_pos(c):
    sym = c["sym"]
    t = ex.fetch_ticker(f"{sym}/USDT")
    px = float(t["last"]) * (1 + TSLIP)
    qty = STAKE / px * (1 - FEE)
    state["cash"] -= STAKE
    pos = {"sym": sym, "entry": px, "qty": qty, "stake": STAKE, "tp": px * (1 + TP), "stop": px * (1 - STOP),
           "t": time.time(), "r24": c["r24"], "idio": c["idio"],
           "volume_ratio": c["volume_ratio"], "last_check": int(time.time() * 1000)}
    state["positions"].append(pos)
    print(f"[ENTRADA] {sym} @ {px:.6g} caida24h={c['r24']}% idio={c['idio']}% "
          f"vol={c['volume_ratio']}x tp={pos['tp']:.6g} stop={pos['stop']:.6g}", flush=True)
    save()


def close_pos(p, px, reason):
    net = p["qty"] * px * (1 - FEE)
    pnl = net - p["stake"]
    state["cash"] += net
    state["pnl"] += pnl
    state["closed"] += 1
    state["wins"] += pnl > 0
    state["positions"].remove(p)
    rec = {"t": datetime.now().isoformat(timespec="seconds"), "sym": p["sym"], "entry": p["entry"], "exit": px,
           "pnl": round(pnl, 4), "reason": reason, "hours": round((time.time() - p["t"]) / 3600, 1),
           "r24": p.get("r24"), "idio": p.get("idio"), "volume_ratio": p.get("volume_ratio")}
    log_trade(rec)
    print(f"[SALIDA {reason}] {p['sym']} @ {px:.6g} PnL {pnl:+.3f} USDT", flush=True)
    save()


def manage():
    for p in list(state["positions"]):
        try:
            m = ex.fetch_ohlcv(f"{p['sym']}/USDT", "1m", since=p["last_check"], limit=100)
            last = float(ex.fetch_ticker(f"{p['sym']}/USDT")["last"])
        except Exception as e:
            print(f"[manage] {p['sym']}: {e}", flush=True)
            continue
        p["last_check"] = int(time.time() * 1000) - 60000
        lo = min([r[3] for r in m] + [last]) if m else last
        hi = max([r[2] for r in m] + [last]) if m else last
        if lo <= p["stop"]:  # conservador: si toca ambos, gana el stop
            close_pos(p, p["stop"] * (1 - SSLIP), "STOP")
        elif hi >= p["tp"] * 1.0003:
            close_pos(p, p["tp"], "TARGET")
        elif time.time() - p["t"] >= HOLD_H * 3600:
            close_pos(p, last * (1 - SSLIP / 2), "TIEMPO")


def equity():
    eq = state["cash"]
    for p in state["positions"]:
        try:
            eq += p["qty"] * float(ex.fetch_ticker(f"{p['sym']}/USDT")["last"])
        except Exception:
            eq += p["stake"]
    return eq


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        with LOCK:
            d = dict(state)
            d["trades"] = [json.loads(l) for l in open(TRADES, encoding="utf-8")][-30:] if os.path.exists(TRADES) else []
        if self.path.startswith("/api"):
            body, ct = json.dumps(d).encode(), "application/json"
        else:
            rows = "".join(f"<tr><td>{t['t']}</td><td>{t['sym']}</td><td>{t['reason']}</td><td>{t['pnl']:+.3f}</td></tr>" for t in reversed(d["trades"]))
            pos = "".join(f"<li>{p['sym']} entrada {p['entry']:.6g} tp {p['tp']:.6g} stop {p['stop']:.6g}</li>" for p in d["positions"])
            body = (f"<meta http-equiv=refresh content=30><body style='font-family:sans-serif;background:#111;color:#eee'>"
                    f"<h2>Reversion Agent (PAPER)</h2><p>Caja {d['cash']:.2f} | PnL {d['pnl']:+.3f} | trades {d['closed']} (ganados {d['wins']}) | ultimo scan {d['last_scan']}</p>"
                    f"<h3>Posiciones</h3><ul>{pos or '<li>ninguna</li>'}</ul><h3>Candidatos ultimo scan</h3><pre>{d['last_candidates']}</pre>"
                    f"<h3>Cerradas</h3><table border=1 cellpadding=4>{rows}</table></body>").encode()
            ct = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.end_headers()
        self.wfile.write(body)


def main():
    if "--reset" in sys.argv and os.path.exists(STATE):
        os.remove(STATE)
        if os.path.exists(TRADES):
            os.remove(TRADES)
    load()
    if "--once" in sys.argv:
        print(json.dumps(scan(), indent=1))
        return
    threading.Thread(target=lambda: HTTPServer(("127.0.0.1", PORT), H).serve_forever(), daemon=True).start()
    print(f"Reversion Agent PAPER en http://127.0.0.1:{PORT}", flush=True)
    last_hour = None
    while True:
        try:
            with LOCK:
                manage()
            hour = int(time.time() // 3600)
            if hour != last_hour and time.time() % 3600 > 20:
                cands = scan()
                with LOCK:
                    state["last_scan"] = datetime.now().isoformat(timespec="seconds")
                    state["last_candidates"] = cands
                    held = {p["sym"] for p in state["positions"]}
                    for c in cands:
                        if len(state["positions"]) >= MAX_POS or state["cash"] < STAKE:
                            break
                        if c["sym"] not in held:
                            open_pos(c)
                            held.add(c["sym"])
                    save()
                print(f"[{state['last_scan']}] scan: {len(cands)} candidatos | pos {len(state['positions'])} | caja {state['cash']:.2f} | pnl {state['pnl']:+.3f}", flush=True)
                last_hour = hour
        except Exception as e:
            print(f"[loop] {e}", flush=True)
        time.sleep(60)


if __name__ == "__main__":
    main()
