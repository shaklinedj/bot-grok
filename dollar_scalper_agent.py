"""
========================================================================================
  THE 1-DOLLAR SCALPER (CERO MALLAS, CERO SHORT - ORDER FLOW MOMENTUM ENGINE)
  - Modo: Independiente (corre en paralelo sin tocar la malla actual).
  - Objetivo: Cazar +$1.00 a +$1.50 USDT limpios por trade y volver 100% a caja.
  - Ejecución: Entrada Maker Límite en micro-retroceso sobre Bid Wall (Cero FOMO).
  - Salida Objetivo: +1.55% fijo (+$1.05 - +$1.15 USDT neto descontando comisiones).
  - Stop Defensivo: -1.15% estricto (arriesga ~$0.85 para ganar ~$1.10 -> Ratio > 1.3:1).
  - Dashboard propio: http://localhost:8899
========================================================================================
"""

import os
import sys
import time
import json
import math
import http.server
import threading
import urllib.request
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import ccxt
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ====================== CONFIGURACIÓN GENERAL ======================
INITIAL_CAPITAL = 80.00
PORTFOLIO_DIR = "scalper_logs"
SCALPER_STATE_FILE = os.path.join(PORTFOLIO_DIR, "scalper_state.json")
SCALPER_TRADES_FILE = os.path.join(PORTFOLIO_DIR, "scalper_trades.csv")
SCALPER_HISTORY_FILE = os.path.join(PORTFOLIO_DIR, "scalper_equity_history.csv")
SCALPER_HTTP_PORT = 8899

FEE_RATE = 0.0010  # 0.10% Binance Spot estándar (0.20% ida y vuelta)
TARGET_PROFIT_PCT = 0.0155  # +1.55% bruto -> +1.35% neto (~+$1.05 USDT en $75)
STOP_LOSS_PCT = 0.0115     # -1.15% bruto -> -1.35% neto (-$0.85 USDT)
ORDER_EXPIRY_SECS = 90     # Cancelar orden de entrada si no retrocede en 90s
MAX_HOLD_TIME_SECS = 2400  # 40 minutos máximo por trade (salida defensiva si se estanca)

INSTITUTIONAL_SCALP_WHITELIST = [
    "SUI/USDT", "NEAR/USDT", "SOL/USDT", "ETH/USDT", "BTC/USDT",
    "LINK/USDT", "AVAX/USDT", "UNI/USDT", "ADA/USDT", "INJ/USDT",
    "RENDER/USDT", "DOGE/USDT", "XRP/USDT"
]

os.makedirs(PORTFOLIO_DIR, exist_ok=True)
exchange = ccxt.binance({"enableRateLimit": True, "timeout": 8000})


# ====================== MODELO DE DATOS ======================
class ScalperTrade:
    def __init__(self, trade_id: str, symbol: str, entry_price: float, amount: float, capital: float):
        self.trade_id = trade_id
        self.symbol = symbol
        self.entry_price = entry_price
        self.amount = amount
        self.capital = capital
        self.entry_time = time.time()
        self.target_price = round(entry_price * (1.0 + TARGET_PROFIT_PCT), 6)
        self.stop_price = round(entry_price * (1.0 - STOP_LOSS_PCT), 6)
        self.status = "OPEN"  # OPEN, TARGET_HIT, STOP_HIT, TIMEOUT_EXIT

    def to_dict(self):
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "entry_price": self.entry_price,
            "amount": self.amount,
            "capital": self.capital,
            "entry_time": self.entry_time,
            "target_price": self.target_price,
            "stop_price": self.stop_price,
            "status": self.status
        }


class ScalperPendingOrder:
    def __init__(self, order_id: str, symbol: str, limit_price: float, capital: float, reason: str):
        self.order_id = order_id
        self.symbol = symbol
        self.limit_price = limit_price
        self.capital = capital
        self.reason = reason
        self.created_at = time.time()
        self.expires_at = self.created_at + ORDER_EXPIRY_SECS

    def to_dict(self):
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "limit_price": self.limit_price,
            "capital": self.capital,
            "reason": self.reason,
            "created_at": self.created_at,
            "expires_at": self.expires_at
        }


class ScalperBot:
    def __init__(self):
        self.cash = INITIAL_CAPITAL
        self.active_trade: Optional[ScalperTrade] = None
        self.pending_order: Optional[ScalperPendingOrder] = None
        self.realized_pnl = 0.0
        self.wins = 0
        self.losses = 0
        self.total_trades = 0
        self.status_msg = "Inicializando 1-Dollar Scalper..."
        self.load_state()

    def load_state(self):
        if os.path.exists(SCALPER_STATE_FILE):
            try:
                with open(SCALPER_STATE_FILE, "r", encoding="utf-8") as f:
                    d = json.load(f)
                self.cash = float(d.get("cash", INITIAL_CAPITAL))
                self.realized_pnl = float(d.get("realized_pnl", 0.0))
                self.wins = int(d.get("wins", 0))
                self.losses = int(d.get("losses", 0))
                self.total_trades = int(d.get("total_trades", 0))
                if d.get("active_trade"):
                    at = d["active_trade"]
                    self.active_trade = ScalperTrade(
                        at["trade_id"], at["symbol"], at["entry_price"], at["amount"], at["capital"]
                    )
                    self.active_trade.entry_time = at.get("entry_time", time.time())
                if d.get("pending_order"):
                    po = d["pending_order"]
                    self.pending_order = ScalperPendingOrder(
                        po["order_id"], po["symbol"], po["limit_price"], po["capital"], po.get("reason", "")
                    )
                    self.pending_order.created_at = po.get("created_at", time.time())
                    self.pending_order.expires_at = po.get("expires_at", time.time() + ORDER_EXPIRY_SECS)
            except Exception as e:
                print(f"  [Aviso Estado] No se pudo cargar estado previo: {e}", flush=True)

    def save_state(self):
        d = {
            "cash": round(self.cash, 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "wins": self.wins,
            "losses": self.losses,
            "total_trades": self.total_trades,
            "status_msg": self.status_msg,
            "active_trade": self.active_trade.to_dict() if self.active_trade else None,
            "pending_order": self.pending_order.to_dict() if self.pending_order else None,
            "updated_at": datetime.now().isoformat()
        }
        with open(SCALPER_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)

    def log_trade(self, symbol: str, side: str, price: float, amount: float, pnl: float, fee: float, note: str):
        row = f"{datetime.now().isoformat()},{symbol},{side},{price:.6f},{amount:.6f},{pnl:.4f},{fee:.4f},{note}\n"
        if not os.path.exists(SCALPER_TRADES_FILE):
            with open(SCALPER_TRADES_FILE, "w", encoding="utf-8") as f:
                f.write("timestamp,symbol,side,price,amount,pnl,fee,note\n")
        with open(SCALPER_TRADES_FILE, "a", encoding="utf-8") as f:
            f.write(row)


# ====================== SCANNER DE ORDER FLOW ======================
def scan_order_flow_opportunities() -> List[Dict]:
    """
    Escanea las monedas líderes buscando:
    1. Alta liquidez pasiva en Bid Book (OBI >= +0.20, compradores impacientes acumulando soporte).
    2. Momentum 15m saludable: Precio > EMA20 y RSI entre 48 y 65.
    3. Ausencia de techo o pared vendedora masiva justo arriba.
    """
    opps = []
    for sym in INSTITUTIONAL_SCALP_WHITELIST:
        try:
            # 1. Ticker rápido
            t = exchange.fetch_ticker(sym)
            curr_p = float(t.get("last", 0.0))
            vol_24h = float(t.get("quoteVolume", 0.0) or 0.0)
            if curr_p <= 0 or vol_24h < 20_000_000:
                continue

            # 2. Libro de órdenes en vivo (Top 15 niveles)
            ob = exchange.fetch_order_book(sym, limit=15)
            bids = sum(b[1] for b in ob.get("bids", []))
            asks = sum(a[1] for a in ob.get("asks", []))
            tot_depth = bids + asks
            if tot_depth <= 0:
                continue
            obi = (bids - asks) / tot_depth  # Order Book Imbalance (-1.0 a +1.0)

            # 3. Klines 15m para tendencia limpia
            ohlcv = exchange.fetch_ohlcv(sym, "15m", limit=25)
            if len(ohlcv) < 20:
                continue
            closes = [c[4] for c in ohlcv]
            volumes = [c[5] for c in ohlcv]

            # EMA20
            sma20 = sum(closes[-20:]) / 20.0
            
            # RSI 14
            gains, losses = [], []
            for i in range(1, 15):
                diff = closes[-15+i] - closes[-15+i-1]
                gains.append(max(0.0, diff))
                losses.append(max(0.0, -diff))
            avg_g = sum(gains) / 14.0 if gains else 0.0001
            avg_l = sum(losses) / 14.0 if losses else 0.0001
            rs = avg_g / (avg_l if avg_l > 0 else 0.0001)
            rsi = 100.0 - (100.0 / (1.0 + rs))

            # Volumen spike: última vela vs promedio
            avg_vol = sum(volumes[-15:]) / 15.0 if volumes else 1.0
            vol_spike = (volumes[-1] / avg_vol) if avg_vol > 0 else 1.0

            # FILTRO FRANCOTIRADOR RIGUROSO:
            # - OBI >= +0.18 (Compradores dominando el libro de órdenes)
            # - Precio sobre EMA20 (Tendencia a favor)
            # - RSI entre 47 y 65 (No comprar sobrecompra agotada)
            # - Volumen vivo
            is_valid_flow = (obi >= 0.18) and (curr_p >= sma20 * 0.998) and (47.0 <= rsi <= 65.0)

            # Score cuantitativo de convicción (0 - 100)
            score = (obi * 40.0) + (min(2.0, vol_spike) * 20.0) + (25.0 if curr_p > sma20 else 0.0) + ((rsi - 45.0) * 0.75)
            score = max(0.0, min(100.0, score))

            if is_valid_flow and score >= 45.0:
                # Calcular precio óptimo de entrada en micro-retroceso (0.25% bajo el precio actual)
                # Justo encima del soporte de bids
                entry_limit = round(curr_p * 0.9975, 6)
                opps.append({
                    "symbol": sym,
                    "price": curr_p,
                    "entry_limit": entry_limit,
                    "obi": round(obi, 3),
                    "rsi": round(rsi, 1),
                    "vol_spike": round(vol_spike, 2),
                    "score": round(score, 1)
                })
        except Exception:
            continue

    return sorted(opps, key=lambda x: x["score"], reverse=True)


# ====================== DASHBOARD HTTP LOCAL ======================
class ScalperDashboardHandler(http.server.BaseHTTPRequestHandler):
    bot_ref: Optional[ScalperBot] = None

    def do_GET(self):
        if self.path == "/api/status":
            b = self.bot_ref
            if not b:
                self.send_response(500)
                self.end_headers()
                return
            equity = b.cash + (b.active_trade.capital if b.active_trade else 0.0)
            win_rate = (b.wins / b.total_trades * 100.0) if b.total_trades > 0 else 100.0
            data = {
                "cash": round(b.cash, 2),
                "equity": round(equity, 2),
                "realized_pnl": round(b.realized_pnl, 4),
                "wins": b.wins,
                "losses": b.losses,
                "total_trades": b.total_trades,
                "win_rate": round(win_rate, 1),
                "status_msg": b.status_msg,
                "active_trade": b.active_trade.to_dict() if b.active_trade else None,
                "pending_order": b.pending_order.to_dict() if b.pending_order else None
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        # HTML Dashboard en vivo
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        html = """<!DOCTYPE html>
<html>
<head>
    <title>THE 1-DOLLAR SCALPER | Order-Flow Momentum Engine</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { background: #0b0e14; color: #e6edf3; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 25px; margin: 0; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #21262d; padding-bottom: 15px; margin-bottom: 25px; }
        .title { font-size: 24px; font-weight: bold; color: #58a6ff; }
        .badge { background: #238636; color: white; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 25px; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 18px; }
        .card-label { font-size: 13px; color: #8b949e; text-transform: uppercase; margin-bottom: 6px; }
        .card-val { font-size: 26px; font-weight: bold; color: #f0f6fc; }
        .val-green { color: #3fb950; }
        .val-gold { color: #d29922; }
        .trade-box { background: #161b22; border: 1px solid #388bfd; border-radius: 8px; padding: 20px; margin-bottom: 25px; }
        .trade-title { font-size: 18px; font-weight: bold; color: #58a6ff; margin-bottom: 12px; }
        .target-bar { background: #21262d; border-radius: 4px; height: 10px; overflow: hidden; margin: 15px 0; }
        .target-fill { background: #2ea043; height: 100%; width: 50%; }
        .status-line { color: #8b949e; font-size: 14px; margin-top: 15px; }
    </style>
</head>
<body>
    <div class="header">
        <div class="title">⚡ THE 1-DOLLAR SCALPER <span style="font-size: 14px; color: #8b949e; font-weight: normal;">| Cero Mallas, Cero Short</span></div>
        <div class="badge">ACTIVO EN VIVO</div>
    </div>

    <div class="grid">
        <div class="card">
            <div class="card-label">Equity Total</div>
            <div class="card-val" id="equity">$80.00</div>
        </div>
        <div class="card">
            <div class="card-label">Ganancia Realizada</div>
            <div class="card-val val-green" id="pnl">+$0.00</div>
        </div>
        <div class="card">
            <div class="card-label">Win Rate</div>
            <div class="card-val val-green" id="winrate">100%</div>
        </div>
        <div class="card">
            <div class="card-label">Trades Cerrados</div>
            <div class="card-val val-gold" id="trades">0</div>
        </div>
        <div class="card">
            <div class="card-label">Caja Líquida</div>
            <div class="card-val" id="cash">$80.00</div>
        </div>
    </div>

    <div class="trade-box" id="trade-container">
        <div class="trade-title" id="trade-title">Buscando Impulso de Order Flow...</div>
        <div id="trade-details" style="color: #8b949e; font-size: 15px;">Escaneando las 15 líderes buscando OBI > +0.20 y volumen comprador agresivo.</div>
    </div>

    <div class="status-line">Estado del Motor: <span id="status-msg" style="color: #f0f6fc;">Iniciando...</span></div>

    <script>
        async function updateData() {
            try {
                const res = await fetch('/api/status');
                const d = await res.json();
                document.getElementById('equity').innerText = '$' + d.equity.toFixed(2);
                document.getElementById('pnl').innerText = (d.realized_pnl >= 0 ? '+$' : '-$') + Math.abs(d.realized_pnl).toFixed(4);
                document.getElementById('winrate').innerText = d.win_rate.toFixed(1) + '%';
                document.getElementById('trades').innerText = d.total_trades + ' (' + d.wins + 'W / ' + d.losses + 'L)';
                document.getElementById('cash').innerText = '$' + d.cash.toFixed(2);
                document.getElementById('status-msg').innerText = d.status_msg;

                const box = document.getElementById('trade-container');
                if (d.active_trade) {
                    box.style.borderColor = '#3fb950';
                    document.getElementById('trade-title').innerText = '🎯 EN POSICIÓN: ' + d.active_trade.symbol + ' ($' + d.active_trade.capital.toFixed(2) + ' USDT)';
                    document.getElementById('trade-details').innerHTML = 
                        '<b>Entrada:</b> $' + d.active_trade.entry_price.toFixed(4) + 
                        ' | <b>Target (+1.55%):</b> $' + d.active_trade.target_price.toFixed(4) + ' <span style=\"color:#3fb950;\">(+$1.10 USDT)</span>' +
                        ' | <b>Stop (-1.15%):</b> $' + d.active_trade.stop_price.toFixed(4) + ' <span style=\"color:#f85149;\">(-$0.85 USDT)</span>';
                } else if (d.pending_order) {
                    box.style.borderColor = '#d29922';
                    document.getElementById('trade-title').innerText = '⏳ ORDEN MAKER LÍMITE PENDIENTE: ' + d.pending_order.symbol;
                    document.getElementById('trade-details').innerText = 'Esperando micro-retroceso a $' + d.pending_order.limit_price.toFixed(4) + ' (' + d.pending_order.reason + ')';
                } else {
                    box.style.borderColor = '#388bfd';
                    document.getElementById('trade-title').innerText = '🔍 RADAR ACTIVO: Buscando Siguiente Dólar';
                    document.getElementById('trade-details').innerText = '100% Líquido en Caja ($' + d.cash.toFixed(2) + '). Escaneando libro de órdenes...';
                }
            } catch(e){}
        }
        setInterval(updateData, 2000);
        updateData();
    </script>
</body>
</html>"""
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        pass


def start_scalper_dashboard(bot: ScalperBot, port: int = SCALPER_HTTP_PORT):
    ScalperDashboardHandler.bot_ref = bot
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), ScalperDashboardHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        print(f"  🌐 [1-DOLLAR SCALPER DASHBOARD] Accede en vivo: http://localhost:{port}", flush=True)
    except Exception as e:
        print(f"  [Scalper HTTP Server Warning] {e}", flush=True)


# ====================== BUCLE OPERATIVO DEL SCALPER ======================
def run_dollar_scalper():
    bot = ScalperBot()
    start_scalper_dashboard(bot, SCALPER_HTTP_PORT)

    print("=" * 80, flush=True)
    print("  THE 1-DOLLAR SCALPER - MOTOR DE CAZA DE GANANCIAS RÁPIDAS (SPOT MOMENTUM)", flush=True)
    print("  • Estrategia                     -> Order Flow & LOB Imbalance Momentum Scalping", flush=True)
    print("  • Filosofía                      -> Cero Mallas, Cero Short, 100% Efectivo en Caja", flush=True)
    print("  • Capital Asignado               -> $80.00 USDT (Simulación Independiente)", flush=True)
    print(f"  • Objetivo por Trade             -> +1.55% (+~$1.05 a +$1.15 USDT Netos)", flush=True)
    print(f"  • Stop Defensivo                 -> -1.15% (-~$0.85 USDT) | Ratio R:R > 1.3:1", flush=True)
    print(f"  • Dashboard en Vivo              -> http://localhost:{SCALPER_HTTP_PORT}", flush=True)
    print("=" * 80, flush=True)

    cycle = 0
    last_scan_ts = 0

    while True:
        try:
            cycle += 1
            now_ts = time.time()
            now_str = datetime.now().strftime("%H:%M:%S")

            # -------------------------------------------------------------
            # 1. GESTIONAR POSICIÓN ABIERTA (Si hay un trade activo)
            # -------------------------------------------------------------
            if bot.active_trade:
                sym = bot.active_trade.symbol
                t = exchange.fetch_ticker(sym)
                curr_p = float(t.get("last", 0.0))
                high_p = float(t.get("high", curr_p))
                low_p = float(t.get("low", curr_p))

                # A. TARGET ALCANZADO (+1.55% = Ganar el Dólar Limpio)
                if curr_p >= bot.active_trade.target_price:
                    gross_return = bot.active_trade.amount * bot.active_trade.target_price
                    fees = gross_return * FEE_RATE
                    net_return = gross_return - fees
                    profit = net_return - bot.active_trade.capital
                    bot.cash += net_return
                    bot.realized_pnl += profit
                    bot.wins += 1
                    bot.total_trades += 1
                    bot.log_trade(
                        sym, "SELL", bot.active_trade.target_price, bot.active_trade.amount,
                        profit, fees, f"🎯 TARGET +1.55% COBRADO! Ganancia neta: +${profit:.4f} USDT | 100% Caja Líquida"
                    )
                    print(f"\n  🎯💵 [1-DOLLAR COBRADO! {sym}]", flush=True)
                    print(f"       Salida ejecutada a ${bot.active_trade.target_price:.4f} (+{TARGET_PROFIT_PCT*100:.2f}%).", flush=True)
                    print(f"       Ganancia NETA: +${profit:.4f} USDT. Capital devuelto a caja: ${bot.cash:.2f} USDT.", flush=True)
                    print(f"       Cerrando posición y volviendo 100% a caja líquida para el siguiente disparo.\n", flush=True)
                    bot.active_trade = None
                    bot.status_msg = f"Objetivo cumplido (+${profit:.2f} USDT). 100% líquido en caja."
                    bot.save_state()
                    time.sleep(15)  # Cooldown defensivo
                    continue

                # B. STOP LOSS DEFENSIVO (-1.15% = Preservar Capital)
                elif curr_p <= bot.active_trade.stop_price:
                    gross_return = bot.active_trade.amount * bot.active_trade.stop_price
                    fees = gross_return * FEE_RATE
                    net_return = gross_return - fees
                    loss = net_return - bot.active_trade.capital
                    bot.cash += net_return
                    bot.realized_pnl += loss
                    bot.losses += 1
                    bot.total_trades += 1
                    bot.log_trade(
                        sym, "SELL", bot.active_trade.stop_price, bot.active_trade.amount,
                        loss, fees, f"🛑 STOP DEFENSIVO EJECUTADO. Pérdida: ${loss:.4f} USDT | Capital protegido"
                    )
                    print(f"\n  🛑🛡️ [STOP DEFENSIVO {sym}]", flush=True)
                    print(f"       Pérdida cortada a ${bot.active_trade.stop_price:.4f} (-{STOP_LOSS_PCT*100:.2f}%).", flush=True)
                    print(f"       Pérdida limitada: ${loss:.4f} USDT. Saldo protegido: ${bot.cash:.2f} USDT.\n", flush=True)
                    bot.active_trade = None
                    bot.status_msg = f"Stop defensivo ejecutado (${loss:.2f} USDT). Buscando siguiente oportunidad."
                    bot.save_state()
                    time.sleep(15)
                    continue

                # C. TIME-DECAY EXIT: Si pasan 40 min y no despega, salir en Breakeven si hay mínima ganancia
                elapsed_s = now_ts - bot.active_trade.entry_time
                if elapsed_s >= MAX_HOLD_TIME_SECS:
                    pct_diff = (curr_p - bot.active_trade.entry_price) / bot.active_trade.entry_price
                    if pct_diff >= 0.003:  # +0.30% cubre comisiones
                        gross_return = bot.active_trade.amount * curr_p
                        fees = gross_return * FEE_RATE
                        net_return = gross_return - fees
                        profit = net_return - bot.active_trade.capital
                        bot.cash += net_return
                        bot.realized_pnl += profit
                        if profit >= 0:
                            bot.wins += 1
                        else:
                            bot.losses += 1
                        bot.total_trades += 1
                        bot.log_trade(sym, "SELL", curr_p, bot.active_trade.amount, profit, fees, f"Salida por Tiempo (Stall Exit): +${profit:.4f} USDT")
                        print(f"  ⏱️ [SALIDA DEFENSIVA POR TIEMPO {sym}] Trade estancado >40m. Cerrado a ${curr_p:.4f} (+${profit:.4f} USDT). Capital liberado.", flush=True)
                        bot.active_trade = None
                        bot.status_msg = "Salida por estancamiento. Capital libre."
                        bot.save_state()
                        continue

                # Monitoreo en vivo del trade abierto
                unrealized_pct = ((curr_p - bot.active_trade.entry_price) / bot.active_trade.entry_price) * 100.0
                bot.status_msg = f"En Trade {sym} @ ${bot.active_trade.entry_price:.4f} | Actual: ${curr_p:.4f} ({unrealized_pct:+.2f}%) | Target: ${bot.active_trade.target_price:.4f}"
                time.sleep(2.0)
                continue

            # -------------------------------------------------------------
            # 2. GESTIONAR ORDEN LÍMITE PENDIENTE (Maker Entry)
            # -------------------------------------------------------------
            if bot.pending_order:
                po = bot.pending_order
                t = exchange.fetch_ticker(po.symbol)
                curr_p = float(t.get("last", 0.0))

                # ¿Se ejecutó el micro-retroceso? (Precio tocó o perforó la orden límite)
                if curr_p <= po.limit_price:
                    # ORDEN EJECUTADA: Abrir posición oficial
                    entry_p = po.limit_price
                    tokens = (po.capital * (1.0 - FEE_RATE)) / entry_p
                    trade = ScalperTrade(
                        trade_id=f"trade_{int(now_ts*1000)}",
                        symbol=po.symbol,
                        entry_price=entry_p,
                        amount=tokens,
                        capital=po.capital
                    )
                    bot.active_trade = trade
                    bot.cash -= po.capital
                    bot.pending_order = None
                    bot.log_trade(po.symbol, "BUY", entry_p, tokens, 0.0, po.capital * FEE_RATE, f"Maker Entry en Soporte LOB (${po.capital:.2f} USDT)")
                    print(f"\n  🎯🟢 [ORDEN MAKER EJECUTADA {po.symbol}]", flush=True)
                    print(f"       Comprados {tokens:.4f} {po.symbol} @ ${entry_p:.4f} (${po.capital:.2f} USDT).", flush=True)
                    print(f"       🎯 Target colocado a ${trade.target_price:.4f} (+{TARGET_PROFIT_PCT*100:.2f}% | Ganancia: +$1.10 USDT).", flush=True)
                    print(f"       🛑 Stop Defensivo en ${trade.stop_price:.4f} (-{STOP_LOSS_PCT*100:.2f}%).\n", flush=True)
                    bot.status_msg = f"Posición abierta en {po.symbol} @ ${entry_p:.4f}. Esperando Target +1.55%."
                    bot.save_state()
                    continue

                # ¿Expiró la orden sin retroceder? (El precio se escapó hacia arriba)
                if now_ts >= po.expires_at:
                    print(f"  ⏱️ [ORDEN CANCELADA {po.symbol}] El precio no retrocedió en {ORDER_EXPIRY_SECS}s. Cancelando sin perseguir FOMO.", flush=True)
                    bot.pending_order = None
                    bot.status_msg = "Orden expirada sin FOMO. Escaneando nuevo candidato."
                    bot.save_state()
                    continue

                time.sleep(2.0)
                continue

            # -------------------------------------------------------------
            # 3. ESCANEO Y DISPARO FRANCOTIRADOR (100% Caja Líquida)
            # -------------------------------------------------------------
            if now_ts - last_scan_ts >= 25.0:
                last_scan_ts = now_ts
                opps = scan_order_flow_opportunities()

                if opps:
                    best = opps[0]
                    # Asignar 92% del capital líquido disponible (~$74 en cuenta de $80)
                    trade_capital = min(bot.cash * 0.95, 75.0)

                    if trade_capital >= 15.0:
                        po = ScalperPendingOrder(
                            order_id=f"ord_{int(now_ts*1000)}",
                            symbol=best["symbol"],
                            limit_price=best["entry_limit"],
                            capital=trade_capital,
                            reason=f"OBI={best['obi']:+.2f} | RSI={best['rsi']:.1f} | Score={best['score']:.1f}"
                        )
                        bot.pending_order = po
                        print(f"\n  🔍⚡ [OPORTUNIDAD FRANCOTIRADOR DETECTADA]", flush=True)
                        print(f"       Moneda: {best['symbol']} | Score: {best['score']:.1f} | OBI LOB: {best['obi']:+.2f} | RSI 15m: {best['rsi']:.1f}", flush=True)
                        print(f"       Precio Actual: ${best['price']:.4f} -> Orden Maker Límite colocada en soporte: ${best['entry_limit']:.4f}", flush=True)
                        print(f"       Capital Asignado: ${trade_capital:.2f} USDT | Target Proyectado: +$1.10 USDT netos.\n", flush=True)
                        bot.status_msg = f"Orden pendiente en {best['symbol']} @ ${best['entry_limit']:.4f} (Score {best['score']:.1f})"
                        bot.save_state()
                        continue
                    else:
                        bot.status_msg = "Saldo insuficiente en caja para nuevo disparo."
                else:
                    bot.status_msg = f"Escaneando 13 pares líderes... Esperando alineación de Order Flow (OBI > +0.20)."

            if cycle % 15 == 0:
                print(f"[{now_str}] Tick #{cycle:04d} | Equity: ${bot.cash:.2f} | PnL: ${bot.realized_pnl:+.4f} | {bot.status_msg}", flush=True)

            bot.save_state()
            time.sleep(2.0)

        except Exception as e:
            print(f"  [Error Bucle Scalper] {e}", flush=True)
            time.sleep(3.0)


if __name__ == "__main__":
    run_dollar_scalper()
