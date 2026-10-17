"""
========================================================================================
  THE 1-DOLLAR SCALPER (CERO MALLAS, CERO SHORT - ORDER FLOW MOMENTUM ENGINE)
  - Modo: PIONEX CUENTA REAL SPOT (Live Execution via pionex-trade-cli)
  - Saldo Inicial Real: ~$70.35 USDT (Liberados tras liquidación de XLM)
  - Objetivo: Cazar +$1.00 USDT limpios por trade y volver 100% a caja líquida.
  - Ejecución: Entrada Maker Límite en micro-retroceso sobre Bid Wall (Cero FOMO).
  - Salida Objetivo: +1.70% fijo (+$1.00 netos descontando comisión Pionex 0.05%).
  - Stop Defensivo: -1.20% estricto (arriesga ~$0.75 para ganar ~$1.00 -> Ratio R:R > 1.3:1).
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
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import csv
import ccxt

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ====================== CONFIGURACIÓN GENERAL ======================
PIONEX_LIVE_MODE = True  # EJECUCIÓN REAL EN VIVO EN PIONEX
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_DIR = os.path.join(BASE_DIR, "scalper_logs")
SCALPER_STATE_FILE = os.path.join(PORTFOLIO_DIR, "scalper_live_state.json")
SCALPER_TRADES_FILE = os.path.join(PORTFOLIO_DIR, "scalper_live_trades.csv")
SCALPER_HTTP_PORT = 8899

PIONEX_FEE_RATE = 0.0005    # 0.05% Pionex Spot Maker/Taker estándar
TARGET_PROFIT_PCT = 0.0170  # +1.70% bruto -> +1.60% neto (~+$1.00 USDT en $60.00)
STOP_LOSS_PCT = 0.0120      # -1.20% bruto -> -1.30% neto (-$0.78 USDT en $60.00)
ORDER_EXPIRY_SECS = 90      # Cancelar orden de entrada si no retrocede en 90s
MAX_HOLD_TIME_SECS = 2400   # 40 minutos máximo por trade (salida defensiva si se estanca)

# Whitelist de 13 monedas de altísima liquidez verificadas en Pionex Spot
INSTITUTIONAL_SCALP_WHITELIST = [
    "SUI/USDT", "NEAR/USDT", "SOL/USDT", "ETH/USDT", "BTC/USDT",
    "LINK/USDT", "AVAX/USDT", "UNI/USDT", "ADA/USDT", "INJ/USDT",
    "DOT/USDT", "DOGE/USDT", "XRP/USDT"
]

os.makedirs(PORTFOLIO_DIR, exist_ok=True)
exchange = ccxt.binance({"enableRateLimit": True, "timeout": 8000})


# ====================== EJECUTOR REAL PIONEX (CLI) ======================
class PionexLiveExecutor:
    """Ejecutor de órdenes spot en vivo para Pionex usando pionex-trade-cli."""

    _symbol_rules_cache = {}
    _last_rules_update = 0

    @staticmethod
    def run_cmd(args: List[str]) -> Dict:
        cmd = ["pionex-trade-cli"] + args
        try:
            res = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
            if res.returncode != 0:
                return {"result": False, "error": res.stderr.strip() or res.stdout.strip()}
            return json.loads(res.stdout)
        except Exception as e:
            return {"result": False, "error": str(e)}

    @classmethod
    def get_usdt_balance(cls) -> float:
        """Obtiene el saldo disponible libre en USDT de Pionex."""
        res = cls.run_cmd(["account", "balance"])
        if not res.get("result"):
            return 0.0
        for b in res.get("data", {}).get("balances", []):
            if b.get("coin") == "USDT":
                try:
                    return float(b.get("free", 0.0))
                except Exception:
                    return 0.0
        return 0.0

    @classmethod
    def get_symbol_rules(cls) -> Dict:
        """Cachea y retorna reglas de precisión de Pionex."""
        now = time.time()
        if cls._symbol_rules_cache and (now - cls._last_rules_update < 1800):
            return cls._symbol_rules_cache

        res = cls.run_cmd(["market", "symbols"])
        if res.get("result"):
            rules = {}
            for s in res.get("data", {}).get("symbols", []):
                sym = s.get("symbol")
                rules[sym] = {
                    "basePrecision": int(s.get("basePrecision", 2)),
                    "quotePrecision": int(s.get("quotePrecision", 4)),
                    "minAmount": float(s.get("minAmount", 10.0)),
                    "minTradeSize": float(s.get("minTradeSize", 0.01))
                }
            cls._symbol_rules_cache = rules
            cls._last_rules_update = now
        return cls._symbol_rules_cache

    @classmethod
    def place_limit_buy(cls, pio_symbol: str, price: float, size: float) -> Optional[str]:
        """Coloca una orden Maker Límite de compra en Pionex."""
        rules = cls.get_symbol_rules().get(pio_symbol, {"basePrecision": 2, "quotePrecision": 4})
        b_prec = rules["basePrecision"]
        q_prec = rules["quotePrecision"]

        price_str = f"{price:.{q_prec}f}"
        size_str = f"{size:.{b_prec}f}"

        res = cls.run_cmd([
            "orders", "new",
            "--symbol", pio_symbol,
            "--side", "BUY",
            "--type", "LIMIT",
            "--price", price_str,
            "--size", size_str
        ])
        if res.get("result") and res.get("data", {}).get("orderId"):
            return str(res["data"]["orderId"])
        print(f"  [Pionex Buy Error] {res}", flush=True)
        return None

    @classmethod
    def place_limit_sell(cls, pio_symbol: str, price: float, size: float) -> Optional[str]:
        """Coloca orden Límite de venta en Target (+1.70%) en Pionex."""
        rules = cls.get_symbol_rules().get(pio_symbol, {"basePrecision": 2, "quotePrecision": 4})
        b_prec = rules["basePrecision"]
        q_prec = rules["quotePrecision"]

        price_str = f"{price:.{q_prec}f}"
        size_str = f"{size:.{b_prec}f}"

        res = cls.run_cmd([
            "orders", "new",
            "--symbol", pio_symbol,
            "--side", "SELL",
            "--type", "LIMIT",
            "--price", price_str,
            "--size", size_str
        ])
        if res.get("result") and res.get("data", {}).get("orderId"):
            return str(res["data"]["orderId"])
        print(f"  [Pionex Sell Target Error] {res}", flush=True)
        return None

    @classmethod
    def place_market_sell(cls, pio_symbol: str, size: float) -> Optional[Dict]:
        """Ejecuta una venta a mercado inmediata (Stop Loss Defensivo)."""
        rules = cls.get_symbol_rules().get(pio_symbol, {"basePrecision": 2, "quotePrecision": 4})
        b_prec = rules["basePrecision"]
        size_str = f"{size:.{b_prec}f}"

        res = cls.run_cmd([
            "orders", "new",
            "--symbol", pio_symbol,
            "--side", "SELL",
            "--type", "MARKET",
            "--size", size_str
        ])
        if res.get("result"):
            return res.get("data", {})
        print(f"  [Pionex Stop Market Sell Error] {res}", flush=True)
        return None

    @classmethod
    def cancel_order(cls, pio_symbol: str, order_id: str) -> bool:
        """Cancela una orden activa en Pionex."""
        res = cls.run_cmd([
            "orders", "cancel",
            "--symbol", pio_symbol,
            "--order-id", str(order_id)
        ])
        return bool(res.get("result"))

    @classmethod
    def get_order_status(cls, pio_symbol: str, order_id: str) -> Optional[Dict]:
        """Consulta el estado en vivo de una orden en Pionex."""
        res = cls.run_cmd([
            "orders", "get",
            "--symbol", pio_symbol,
            "--order-id", str(order_id)
        ])
        if res.get("result"):
            return res.get("data", {})
        return None


# ====================== MODELO DE DATOS ======================
class ScalperTrade:
    def __init__(self, trade_id: str, symbol: str, entry_price: float, amount: float, capital: float, target_order_id: str = ""):
        self.trade_id = trade_id
        self.symbol = symbol  # Ej: NEAR_USDT
        self.entry_price = entry_price
        self.amount = amount
        self.capital = capital
        self.target_order_id = target_order_id
        self.entry_time = time.time()
        self.target_price = round(entry_price * (1.0 + TARGET_PROFIT_PCT), 6)
        self.stop_price = round(entry_price * (1.0 - STOP_LOSS_PCT), 6)
        self.status = "OPEN"

    def to_dict(self):
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "entry_price": self.entry_price,
            "amount": self.amount,
            "capital": self.capital,
            "target_order_id": self.target_order_id,
            "entry_time": self.entry_time,
            "target_price": self.target_price,
            "stop_price": self.stop_price,
            "status": self.status
        }


class ScalperPendingOrder:
    def __init__(self, order_id: str, symbol: str, limit_price: float, size: float, capital: float, reason: str):
        self.order_id = order_id
        self.symbol = symbol
        self.limit_price = limit_price
        self.size = size
        self.capital = capital
        self.reason = reason
        self.created_at = time.time()
        self.expires_at = self.created_at + ORDER_EXPIRY_SECS

    def to_dict(self):
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "limit_price": self.limit_price,
            "size": self.size,
            "capital": self.capital,
            "reason": self.reason,
            "created_at": self.created_at,
            "expires_at": self.expires_at
        }


class ScalperBot:
    def __init__(self):
        self.cash = 0.0
        self.active_trade: Optional[ScalperTrade] = None
        self.pending_order: Optional[ScalperPendingOrder] = None
        self.realized_pnl = 0.0
        self.wins = 0
        self.losses = 0
        self.total_trades = 0
        self.status_msg = "Sincronizando con Pionex Real..."
        self.sync_balance()
        self.load_state()

    def sync_balance(self):
        """Sincroniza el saldo real con Pionex."""
        real_usdt = PionexLiveExecutor.get_usdt_balance()
        if real_usdt > 0:
            self.cash = real_usdt

    def load_state(self):
        if os.path.exists(SCALPER_STATE_FILE):
            try:
                with open(SCALPER_STATE_FILE, "r", encoding="utf-8") as f:
                    d = json.load(f)
                self.realized_pnl = float(d.get("realized_pnl", 0.0))
                self.wins = int(d.get("wins", 0))
                self.losses = int(d.get("losses", 0))
                self.total_trades = int(d.get("total_trades", 0))
                if d.get("active_trade"):
                    at = d["active_trade"]
                    self.active_trade = ScalperTrade(
                        at["trade_id"], at["symbol"], at["entry_price"], at["amount"], at["capital"], at.get("target_order_id", "")
                    )
                    self.active_trade.entry_time = at.get("entry_time", time.time())
                    self.active_trade.target_price = at.get("target_price", self.active_trade.target_price)
                    self.active_trade.stop_price = at.get("stop_price", self.active_trade.stop_price)
                if d.get("pending_order"):
                    po = d["pending_order"]
                    self.pending_order = ScalperPendingOrder(
                        po["order_id"], po["symbol"], po["limit_price"], po.get("size", 0.0), po["capital"], po.get("reason", "")
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
            "updated_at": datetime.now().isoformat(),
            "mode": "PIONEX_LIVE_SPOT"
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
    Escanea las 13 líderes buscando:
    1. Alta liquidez pasiva en Bid Book (OBI >= +0.18).
    2. Momentum 15m saludable: Precio >= EMA20 * 0.998 y RSI entre 47 y 65.
    3. Score cuantitativo de convicción >= 45.0.
    """
    rules = PionexLiveExecutor.get_symbol_rules()
    opps = []

    for ccxt_sym in INSTITUTIONAL_SCALP_WHITELIST:
        pio_sym = ccxt_sym.replace("/", "_")
        if pio_sym not in rules:
            continue

        try:
            t = exchange.fetch_ticker(ccxt_sym)
            curr_p = float(t.get("last", 0.0))
            vol_24h = float(t.get("quoteVolume", 0.0) or 0.0)
            if curr_p <= 0 or vol_24h < 15_000_000:
                continue

            ob = exchange.fetch_order_book(ccxt_sym, limit=15)
            bids = sum(b[1] for b in ob.get("bids", []))
            asks = sum(a[1] for a in ob.get("asks", []))
            tot_depth = bids + asks
            if tot_depth <= 0:
                continue
            obi = (bids - asks) / tot_depth

            ohlcv = exchange.fetch_ohlcv(ccxt_sym, "15m", limit=25)
            if len(ohlcv) < 20:
                continue
            closes = [c[4] for c in ohlcv]
            volumes = [c[5] for c in ohlcv]

            sma20 = sum(closes[-20:]) / 20.0

            gains, losses = [], []
            for i in range(1, 15):
                diff = closes[-15+i] - closes[-15+i-1]
                gains.append(max(0.0, diff))
                losses.append(max(0.0, -diff))
            avg_g = sum(gains) / 14.0 if gains else 0.0001
            avg_l = sum(losses) / 14.0 if losses else 0.0001
            rs = avg_g / (avg_l if avg_l > 0 else 0.0001)
            rsi = 100.0 - (100.0 / (1.0 + rs))

            avg_vol = sum(volumes[-15:]) / 15.0 if volumes else 1.0
            vol_spike = (volumes[-1] / avg_vol) if avg_vol > 0 else 1.0

            is_valid_flow = (obi >= 0.18) and (curr_p >= sma20 * 0.998) and (47.0 <= rsi <= 65.0)

            score = (obi * 40.0) + (min(2.0, vol_spike) * 20.0) + (25.0 if curr_p > sma20 else 0.0) + ((rsi - 45.0) * 0.75)
            score = max(0.0, min(100.0, score))

            if is_valid_flow and score >= 45.0:
                q_prec = rules[pio_sym]["quotePrecision"]
                entry_limit = round(curr_p * 0.9975, q_prec)
                opps.append({
                    "ccxt_symbol": ccxt_sym,
                    "pio_symbol": pio_sym,
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
                "mode": "PIONEX LIVE SPOT",
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
            trades_list = []
            if os.path.exists(SCALPER_TRADES_FILE):
                try:
                    with open(SCALPER_TRADES_FILE, "r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        rows = list(reader)
                        for r in rows[-30:]:
                            trades_list.append(r)
                        trades_list.reverse()
                except Exception:
                    pass
            data["trades"] = trades_list
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
    <title>THE 1-DOLLAR SCALPER | Pionex Live Spot Engine</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { background: #0b0e14; color: #e6edf3; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 25px; margin: 0; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #21262d; padding-bottom: 15px; margin-bottom: 25px; }
        .title { font-size: 24px; font-weight: bold; color: #58a6ff; }
        .badge { background: #238636; color: white; padding: 6px 12px; border-radius: 12px; font-size: 13px; font-weight: bold; animation: pulse 2s infinite; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.7; } 100% { opacity: 1; } }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 25px; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 18px; }
        .card-label { font-size: 13px; color: #8b949e; text-transform: uppercase; margin-bottom: 6px; }
        .card-val { font-size: 26px; font-weight: bold; color: #f0f6fc; }
        .val-green { color: #3fb950; }
        .val-gold { color: #d29922; }
        .trade-box { background: #161b22; border: 2px solid #388bfd; border-radius: 8px; padding: 20px; margin-bottom: 25px; }
        .trade-title { font-size: 18px; font-weight: bold; color: #58a6ff; margin-bottom: 12px; }
        .table-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin-top: 25px; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; font-family: monospace; }
        th { text-align: left; padding: 10px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 11px; text-transform: uppercase; }
        td { padding: 10px; border-bottom: 1px solid #21262d; }
        .tag-buy { background: rgba(46,160,67,0.15); color: #3fb950; border: 1px solid rgba(46,160,67,0.3); padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; }
        .tag-sell { background: rgba(163,113,247,0.15); color: #bc8cff; border: 1px solid rgba(163,113,247,0.3); padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; }
        .status-line { color: #8b949e; font-size: 14px; margin-top: 15px; }
        .banner { background: rgba(56, 139, 253, 0.1); border: 1px solid #388bfd; padding: 12px 18px; border-radius: 6px; font-size: 13px; margin-bottom: 20px; color: #58a6ff; }
    </style>
</head>
<body>
    <div class="header">
        <div class="title">⚡ THE 1-DOLLAR SCALPER <span style="font-size: 14px; color: #8b949e; font-weight: normal;">| Conectado a Pionex Spot</span></div>
        <div class="badge">🟢 PIONEX CUENTA REAL VIVA</div>
    </div>

    <div class="banner">
        🛡️ <b>MODO DE CAZA REAL SPOT:</b> Disparos únicos de ~$60.00 USDT en micro-retroceso Maker. Salida automática en <b>+$1.00 USD limpios (+1.70%)</b>. Stop Loss estricto en <b>-1.20%</b>. Cero mallas atrapadas. El capital vuelve 100% a caja tras cada trade.
    </div>

    <div class="grid">
        <div class="card">
            <div class="card-label">Saldo Pionex USDT</div>
            <div class="card-val" id="cash">$70.35</div>
        </div>
        <div class="card">
            <div class="card-label">Equity Total Vivo</div>
            <div class="card-val" id="equity">$70.35</div>
        </div>
        <div class="card">
            <div class="card-label">Ganancia Realizada (Live)</div>
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
    </div>

    <div class="trade-box" id="trade-container">
        <div class="trade-title" id="trade-title">Buscando Impulso de Order Flow...</div>
        <div id="trade-details" style="color: #8b949e; font-size: 15px;">Escaneando las 13 líderes buscando OBI > +0.18 y pared de compra en soporte.</div>
    </div>

    <div class="status-line">Estado del Motor: <span id="status-msg" style="color: #f0f6fc;">Iniciando...</span></div>

    <!-- Tabla de Operaciones Ejecutadas -->
    <div class="table-card">
        <div style="font-size: 16px; font-weight: bold; color: #58a6ff; margin-bottom: 12px; display:flex; justify-content:space-between; align-items:center;">
            <span>📋 Auditoría de Órdenes Reales en Pionex</span>
            <span style="font-size:12px; color:#8b949e; font-weight:normal;">Historial transparente con Fees Pionex (0.05%) y PnL Neto</span>
        </div>
        <div style="overflow-x: auto;">
            <table>
                <thead>
                    <tr>
                        <th>Hora</th>
                        <th>Par</th>
                        <th>Acción</th>
                        <th>Precio</th>
                        <th>Cantidad</th>
                        <th>PnL Neto</th>
                        <th>Fee Pionex</th>
                        <th>Detalle / Motivo</th>
                    </tr>
                </thead>
                <tbody id="trades-body">
                    <tr><td colspan="8" style="text-align:center; color:#8b949e; padding:15px;">Esperando primera operación en Pionex...</td></tr>
                </tbody>
            </table>
        </div>
    </div>

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
                    document.getElementById('trade-title').innerText = '🎯 EN POSICIÓN REAL: ' + d.active_trade.symbol + ' ($' + d.active_trade.capital.toFixed(2) + ' USDT)';
                    document.getElementById('trade-details').innerHTML = 
                        '<b>Entrada:</b> $' + d.active_trade.entry_price.toFixed(4) + 
                        ' | <b>Target (+1.70%):</b> $' + d.active_trade.target_price.toFixed(4) + ' <span style=\"color:#3fb950;\">(+$1.00 USDT Neto)</span>' +
                        ' | <b>Stop (-1.20%):</b> $' + d.active_trade.stop_price.toFixed(4) + ' <span style=\"color:#f85149;\">(-$0.75 USDT)</span>' +
                        (d.active_trade.target_order_id ? ' | <b>Orden Venta Pionex:</b> #' + d.active_trade.target_order_id : '');
                } else if (d.pending_order) {
                    box.style.borderColor = '#d29922';
                    document.getElementById('trade-title').innerText = '⏳ ORDEN MAKER LÍMITE PIONEX #' + d.pending_order.order_id + ' (' + d.pending_order.symbol + ')';
                    document.getElementById('trade-details').innerText = 'Colocada a $' + d.pending_order.limit_price.toFixed(4) + ' por $' + d.pending_order.capital.toFixed(2) + ' USDT (' + d.pending_order.reason + ')';
                } else {
                    box.style.borderColor = '#388bfd';
                    document.getElementById('trade-title').innerText = '🔍 RADAR ACTIVO: Buscando Siguiente Dólar';
                    document.getElementById('trade-details').innerText = '100% Líquido en Caja Pionex ($' + d.cash.toFixed(2) + ' USDT). Escaneando libros de órdenes...';
                }

                // Render Trades Table
                const tbody = document.getElementById('trades-body');
                if (d.trades && d.trades.length > 0) {
                    let rowsHtml = '';
                    for (const t of d.trades) {
                        const isBuy = t.side === 'BUY';
                        const badge = isBuy ? '<span class=\"tag-buy\">🟢 COMPRA</span>' : '<span class=\"tag-sell\">🔴 VENTA</span>';
                        const pnlVal = parseFloat(t.pnl || 0);
                        const pnlColor = pnlVal > 0 ? '#3fb950' : (pnlVal < 0 ? '#f85149' : '#8b949e');
                        const pnlStr = !isBuy ? ('<span style=\"color:' + pnlColor + '; font-weight:bold;\">' + (pnlVal >= 0 ? '+' : '') + '$' + pnlVal.toFixed(4) + '</span>') : '<span style=\"color:#8b949e;\">-</span>';
                        const tTime = t.timestamp ? (t.timestamp.includes('T') ? t.timestamp.split('T')[1].split('.')[0] : t.timestamp) : '--:--';
                        const feeStr = '$' + parseFloat(t.fee || 0).toFixed(4);
                        rowsHtml += '<tr>' +
                            '<td style=\"color:#8b949e;\">' + tTime + '</td>' +
                            '<td style=\"font-weight:bold; color:#f0f6fc;\">' + t.symbol + '</td>' +
                            '<td>' + badge + '</td>' +
                            '<td style=\"color:#f0f6fc;\">$' + parseFloat(t.price || 0).toFixed(4) + '</td>' +
                            '<td style=\"color:#8b949e;\">' + parseFloat(t.amount || 0).toFixed(2) + '</td>' +
                            '<td>' + pnlStr + '</td>' +
                            '<td style=\"color:#8b949e;\">' + feeStr + '</td>' +
                            '<td style=\"color:#e6edf3; font-family:sans-serif; font-size:12px;\">' + (t.note || '') + '</td>' +
                        '</tr>';
                    }
                    tbody.innerHTML = rowsHtml;
                } else {
                    tbody.innerHTML = '<tr><td colspan=\"8\" style=\"text-align:center; color:#8b949e; padding:15px;\">Esperando primera operación en Pionex...</td></tr>';
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

    # Reglas de símbolos Pionex
    rules = PionexLiveExecutor.get_symbol_rules()
    print("=" * 80, flush=True)
    print("  THE 1-DOLLAR SCALPER - PIONEX LIVE SPOT EXECUTION ENGINE", flush=True)
    print("  • Modo                           -> PIONEX CUENTA REAL SPOT VIVA", flush=True)
    print("  • Saldo Pionex Detectado         -> $" + f"{bot.cash:.2f} USDT", flush=True)
    print(f"  • Objetivo por Disparo           -> +1.70% (+$1.00 USDT netos)", flush=True)
    print(f"  • Stop Defensivo                 -> -1.20% (-$0.75 USDT) | R:R > 1.3:1", flush=True)
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
            # 1. GESTIONAR POSICIÓN ABIERTA (Si hay un trade activo en Pionex)
            # -------------------------------------------------------------
            if bot.active_trade:
                trade = bot.active_trade
                pio_sym = trade.symbol
                ccxt_sym = pio_sym.replace("_", "/")

                # Obtener precio de mercado actual
                try:
                    t = exchange.fetch_ticker(ccxt_sym)
                    curr_p = float(t.get("last", 0.0))
                except Exception:
                    time.sleep(2.0)
                    continue

                # Consultar estado de la orden de venta Target en Pionex
                order_status = None
                if trade.target_order_id:
                    order_status = PionexLiveExecutor.get_order_status(pio_sym, trade.target_order_id)

                # A. TARGET ALCANZADO (Orden de venta Pionex cerrada/ejecutada o precio sobre target)
                is_target_filled = (order_status and order_status.get("status") == "CLOSED") or (curr_p >= trade.target_price)
                if is_target_filled:
                    # Si no estaba cerrada la orden pero el precio lo tocó, verificar o cancelar y vender
                    if order_status and order_status.get("status") != "CLOSED":
                        PionexLiveExecutor.cancel_order(pio_sym, trade.target_order_id)
                        PionexLiveExecutor.place_market_sell(pio_sym, trade.amount)

                    # Esperar 2s y sincronizar saldo real desde Pionex
                    time.sleep(2.0)
                    bot.sync_balance()

                    profit = (trade.amount * trade.target_price * (1.0 - PIONEX_FEE_RATE)) - trade.capital
                    fees = (trade.amount * trade.target_price) * PIONEX_FEE_RATE
                    bot.realized_pnl += profit
                    bot.wins += 1
                    bot.total_trades += 1
                    bot.log_trade(
                        pio_sym, "SELL", trade.target_price, trade.amount,
                        profit, fees, f"🎯 TARGET +1.70% EN PIONEX COBRADO! Ganancia neta: +${profit:.4f} USDT | 100% Caja Líquida"
                    )
                    print(f"\n  🎯💵 [1-DOLLAR COBRADO EN PIONEX! {pio_sym}]", flush=True)
                    print(f"       Salida ejecutada a ${trade.target_price:.4f} (+{TARGET_PROFIT_PCT*100:.2f}%).", flush=True)
                    print(f"       Ganancia NETA: +${profit:.4f} USDT. Saldo en Pionex: ${bot.cash:.2f} USDT.", flush=True)
                    print(f"       Cerrando posición y volviendo 100% a caja líquida para el siguiente disparo.\n", flush=True)
                    bot.active_trade = None
                    bot.status_msg = f"Objetivo cumplido (+${profit:.2f} USDT). 100% líquido en caja Pionex (${bot.cash:.2f} USDT)."
                    bot.save_state()
                    time.sleep(15)  # Cooldown
                    continue

                # B. STOP LOSS DEFENSIVO (-1.20% = Preservar Capital Inmediato)
                elif curr_p <= trade.stop_price:
                    print(f"\n  🛑🛡️ [ACTIVANDO STOP DEFENSIVO EN PIONEX {pio_sym}]", flush=True)
                    if trade.target_order_id:
                        PionexLiveExecutor.cancel_order(pio_sym, trade.target_order_id)
                    time.sleep(0.5)
                    sell_res = PionexLiveExecutor.place_market_sell(pio_sym, trade.amount)

                    time.sleep(2.0)
                    bot.sync_balance()

                    loss = (trade.amount * curr_p * (1.0 - PIONEX_FEE_RATE)) - trade.capital
                    fees = (trade.amount * curr_p) * PIONEX_FEE_RATE
                    bot.realized_pnl += loss
                    bot.losses += 1
                    bot.total_trades += 1
                    bot.log_trade(
                        pio_sym, "SELL", curr_p, trade.amount,
                        loss, fees, f"🛑 STOP DEFENSIVO EN PIONEX EJECUTADO. Pérdida: ${loss:.4f} USDT | Capital protegido"
                    )
                    print(f"       Pérdida cortada a ${curr_p:.4f} (-{STOP_LOSS_PCT*100:.2f}%).", flush=True)
                    print(f"       Pérdida limitada: ${loss:.4f} USDT. Saldo Pionex protegido: ${bot.cash:.2f} USDT.\n", flush=True)
                    bot.active_trade = None
                    bot.status_msg = f"Stop defensivo ejecutado (${loss:.2f} USDT). Saldo en Pionex: ${bot.cash:.2f} USDT."
                    bot.save_state()
                    time.sleep(15)
                    continue

                # C. TIME-DECAY EXIT: Si pasan 40 min y no despega, salir en Breakeven si hay mínima ganancia
                elapsed_s = now_ts - trade.entry_time
                if elapsed_s >= MAX_HOLD_TIME_SECS:
                    pct_diff = (curr_p - trade.entry_price) / trade.entry_price
                    if pct_diff >= 0.002:  # +0.20% cubre comisiones Pionex
                        if trade.target_order_id:
                            PionexLiveExecutor.cancel_order(pio_sym, trade.target_order_id)
                        time.sleep(0.5)
                        PionexLiveExecutor.place_market_sell(pio_sym, trade.amount)
                        time.sleep(2.0)
                        bot.sync_balance()
                        profit = (trade.amount * curr_p * (1.0 - PIONEX_FEE_RATE)) - trade.capital
                        fees = (trade.amount * curr_p) * PIONEX_FEE_RATE
                        bot.realized_pnl += profit
                        if profit >= 0:
                            bot.wins += 1
                        else:
                            bot.losses += 1
                        bot.total_trades += 1
                        bot.log_trade(pio_sym, "SELL", curr_p, trade.amount, profit, fees, f"Salida por Tiempo (Stall Exit): +${profit:.4f} USDT")
                        print(f"  ⏱️ [SALIDA DEFENSIVA POR TIEMPO {pio_sym}] Trade estancado >40m. Cerrado a ${curr_p:.4f} (+${profit:.4f} USDT). Capital liberado.", flush=True)
                        bot.active_trade = None
                        bot.status_msg = f"Salida por estancamiento. Saldo en Pionex: ${bot.cash:.2f} USDT."
                        bot.save_state()
                        continue

                # Monitoreo en vivo del trade abierto
                unrealized_pct = ((curr_p - trade.entry_price) / trade.entry_price) * 100.0
                bot.status_msg = f"En Trade {pio_sym} @ ${trade.entry_price:.4f} | Actual: ${curr_p:.4f} ({unrealized_pct:+.2f}%) | Target: ${trade.target_price:.4f}"
                time.sleep(2.0)
                continue

            # -------------------------------------------------------------
            # 2. GESTIONAR ORDEN LÍMITE PENDIENTE EN PIONEX (Maker Entry)
            # -------------------------------------------------------------
            if bot.pending_order:
                po = bot.pending_order
                status_res = PionexLiveExecutor.get_order_status(po.symbol, po.order_id)

                # ¿Se ejecutó la orden de compra en Pionex?
                if status_res and status_res.get("status") == "CLOSED":
                    filled_size = float(status_res.get("filledSize", po.size) or po.size)
                    filled_amount = float(status_res.get("filledAmount", po.capital) or po.capital)
                    entry_p = filled_amount / filled_size if filled_size > 0 else po.limit_price

                    print(f"\n  🎯🟢 [ORDEN MAKER PIONEX #{po.order_id} EJECUTADA {po.symbol}]", flush=True)
                    print(f"       Comprados {filled_size:.4f} {po.symbol} @ ${entry_p:.4f} (${filled_amount:.2f} USDT).", flush=True)

                    # Colocar inmediatamente la orden Límite de venta en Target (+1.70%) en Pionex
                    target_p = round(entry_p * (1.0 + TARGET_PROFIT_PCT), rules.get(po.symbol, {}).get("quotePrecision", 4))
                    target_order_id = PionexLiveExecutor.place_limit_sell(po.symbol, target_p, filled_size)
                    print(f"       🎯 Orden Venta Target colocada en Pionex #{target_order_id} a ${target_p:.4f} (+1.70%).", flush=True)

                    trade = ScalperTrade(
                        trade_id=f"pio_{po.order_id}",
                        symbol=po.symbol,
                        entry_price=entry_p,
                        amount=filled_size,
                        capital=filled_amount,
                        target_order_id=target_order_id or ""
                    )
                    trade.target_price = target_p
                    trade.stop_price = round(entry_p * (1.0 - STOP_LOSS_PCT), rules.get(po.symbol, {}).get("quotePrecision", 4))
                    print(f"       🛑 Stop Defensivo vigilado en ${trade.stop_price:.4f} (-1.20%).\n", flush=True)

                    bot.active_trade = trade
                    bot.pending_order = None
                    bot.sync_balance()
                    bot.log_trade(po.symbol, "BUY", entry_p, filled_size, 0.0, filled_amount * PIONEX_FEE_RATE, f"Maker Entry en Pionex #{po.order_id} (${filled_amount:.2f} USDT)")
                    bot.status_msg = f"Posición abierta en {po.symbol} @ ${entry_p:.4f}. Esperando Target +1.70% (Venta #{target_order_id})."
                    bot.save_state()
                    continue

                # ¿Expiró la orden de compra sin ejecutarse? (90s sin retroceso)
                if now_ts >= po.expires_at:
                    print(f"  ⏱️ [ORDEN PIONEX CANCELADA #{po.order_id} {po.symbol}] No retrocedió en {ORDER_EXPIRY_SECS}s. Cancelando sin FOMO.", flush=True)
                    PionexLiveExecutor.cancel_order(po.symbol, po.order_id)
                    bot.pending_order = None
                    bot.sync_balance()
                    bot.status_msg = "Orden expirada sin FOMO. Escaneando nuevo candidato."
                    bot.save_state()
                    continue

                time.sleep(2.0)
                continue

            # -------------------------------------------------------------
            # 3. ESCANEO Y DISPARO FRANCOTIRADOR (100% Caja Líquida en Pionex)
            # -------------------------------------------------------------
            if now_ts - last_scan_ts >= 25.0:
                last_scan_ts = now_ts
                bot.sync_balance()

                opps = scan_order_flow_opportunities()
                if opps:
                    best = opps[0]
                    pio_sym = best["pio_symbol"]
                    sym_rules = rules.get(pio_sym, {"basePrecision": 2, "quotePrecision": 4, "minAmount": 10.0})

                    # Tamaño de disparo: usar 86% del saldo libre de Pionex (máximo $60.00 USDT)
                    # Deja ~$10.00 USDT de buffer seguro en la cuenta
                    trade_capital = min(bot.cash * 0.86, 60.00)

                    if trade_capital >= sym_rules["minAmount"]:
                        entry_limit = best["entry_limit"]
                        raw_size = trade_capital / entry_limit
                        b_prec = sym_rules["basePrecision"]
                        size = round(raw_size, b_prec)

                        if size >= sym_rules["minTradeSize"]:
                            print(f"\n  🔍⚡ [OPORTUNIDAD FRANCOTIRADOR DETECTADA]", flush=True)
                            print(f"       Moneda: {pio_sym} | Score: {best['score']:.1f} | OBI LOB: {best['obi']:+.2f} | RSI 15m: {best['rsi']:.1f}", flush=True)
                            print(f"       Precio Actual: ${best['price']:.4f} -> Colocando Orden Maker Límite en Pionex a ${entry_limit:.4f}...", flush=True)

                            order_id = PionexLiveExecutor.place_limit_buy(pio_sym, entry_limit, size)
                            if order_id:
                                po = ScalperPendingOrder(
                                    order_id=order_id,
                                    symbol=pio_sym,
                                    limit_price=entry_limit,
                                    size=size,
                                    capital=trade_capital,
                                    reason=f"OBI={best['obi']:+.2f} | RSI={best['rsi']:.1f} | Score={best['score']:.1f}"
                                )
                                bot.pending_order = po
                                print(f"       ✅ Orden de Compra Colocada en Pionex #{order_id} ({size} {pio_sym} por ${trade_capital:.2f} USDT). Target proyectado: +$1.00 USDT.\n", flush=True)
                                bot.status_msg = f"Orden Maker #{order_id} colocada en {pio_sym} @ ${entry_limit:.4f} (Score {best['score']:.1f})"
                                bot.save_state()
                                continue
                            else:
                                print(f"  [Aviso Pionex] Falló colocación de orden en {pio_sym}", flush=True)
                    else:
                        bot.status_msg = f"Saldo libre en Pionex (${bot.cash:.2f} USDT) por debajo del mínimo ($10.00 USDT)."
                else:
                    bot.status_msg = f"Escaneando 13 pares líderes en Pionex... Esperando OBI > +0.18 y soporte LOB."

            if cycle % 15 == 0:
                print(f"[{now_str}] Tick #{cycle:04d} | Pionex USDT: ${bot.cash:.2f} | PnL: ${bot.realized_pnl:+.4f} | {bot.status_msg}", flush=True)

            bot.save_state()
            time.sleep(2.0)

        except Exception as e:
            print(f"  [Error Bucle Scalper] {e}", flush=True)
            time.sleep(3.0)


if __name__ == "__main__":
    run_dollar_scalper()
