"""
BUDA.COM - DIGITAL DOLLAR MARKET MAKER SIMULATOR (USDT/CLP)
Simulador Cuantitativo de Casa de Cambio Pasiva (Maker) con Datos en Vivo de Buda.com.
Calcula spreads reales, comisiones oficiales de Buda (0.40% Maker) y valida fills
directamente contra la cinta de transacciones ejecutadas por usuarios en Chile.
"""
import os
import sys
import time
import json
import urllib.request
from datetime import datetime
from typing import Dict, Any, List, Optional

# Configurar encoding UTF-8 en consola Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BUDA_API_BASE = "https://www.buda.com/api/v2"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "buda_sim_state.json")

# Configuración Inicial ($100 USD en CLP al tipo de cambio de arranque)
INITIAL_CLP_CASH = 50000.0   # $50,000 CLP para comprar USDT
INITIAL_USDT_INV = 50.0      # 50.00 USDT en inventario para vender
BUDA_MAKER_FEE = 0.0040      # 0.40% comisión Maker oficial de Buda (Tier 0)
MIN_PROFITABLE_SPREAD = 0.0085  # 0.85% spread mínimo para asegurar ganancia tras comisiones (0.80%)


class BudaMarketMakerSim:
    def __init__(self, market: str = "usdt-clp"):
        self.market = market.lower()
        self.clp_balance = INITIAL_CLP_CASH
        self.usdt_balance = INITIAL_USDT_INV
        self.initial_equity_clp = 0.0
        self.trades_completed = 0
        self.total_volume_clp = 0.0
        self.last_seen_trade_id = 0
        self.my_bid_price = 0.0
        self.my_ask_price = 0.0
        self.my_bid_amount = 0.0
        self.my_ask_amount = 0.0
        self.history: List[Dict[str, Any]] = []
        self.load_state()

    def fetch_api(self, endpoint: str) -> Optional[Dict[str, Any]]:
        url = f"{BUDA_API_BASE}/markets/{self.market}/{endpoint}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BudaSim/1.0)"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            return None

    def load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    self.clp_balance = float(d.get("clp_balance", INITIAL_CLP_CASH))
                    self.usdt_balance = float(d.get("usdt_balance", INITIAL_USDT_INV))
                    self.initial_equity_clp = float(d.get("initial_equity_clp", 0.0))
                    self.trades_completed = int(d.get("trades_completed", 0))
                    self.total_volume_clp = float(d.get("total_volume_clp", 0.0))
                    self.last_seen_trade_id = int(d.get("last_seen_trade_id", 0))
                    self.history = d.get("history", [])
            except Exception:
                pass

    def save_state(self):
        d = {
            "clp_balance": self.clp_balance,
            "usdt_balance": self.usdt_balance,
            "initial_equity_clp": self.initial_equity_clp,
            "trades_completed": self.trades_completed,
            "total_volume_clp": self.total_volume_clp,
            "last_seen_trade_id": self.last_seen_trade_id,
            "history": self.history[-50:],
            "updated_at": datetime.now().isoformat()
        }
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=2)
        except Exception:
            pass

    def run_cycle(self):
        # 1. Obtener libro de órdenes en vivo
        ob_data = self.fetch_api("order_book")
        if not ob_data or "order_book" not in ob_data:
            return

        ob = ob_data["order_book"]
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])
        if not bids or not asks:
            return

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        mid_price = (best_bid + best_ask) / 2.0
        spread_clp = best_ask - best_bid
        spread_pct = (spread_clp / best_bid) * 100.0

        # Inicializar patrimonio base si es primera vez
        if self.initial_equity_clp <= 0.0:
            self.initial_equity_clp = self.clp_balance + (self.usdt_balance * mid_price)
            self.save_state()

        current_equity_clp = self.clp_balance + (self.usdt_balance * mid_price)
        current_equity_usd = current_equity_clp / mid_price if mid_price > 0 else 100.0
        pnl_clp = current_equity_clp - self.initial_equity_clp
        pnl_pct = (pnl_clp / self.initial_equity_clp * 100.0) if self.initial_equity_clp > 0 else 0.0

        # 2. Posicionamiento Óptimo de Nuestras Órdenes (Penny Jumping con Umbral de Ganancia)
        # Para ganar dinero neto, nuestras órdenes deben estar separadas al menos por 0.85% (comisión maker 0.80% roundtrip)
        min_half_spread = (mid_price * (MIN_PROFITABLE_SPREAD / 2.0))

        # Precio de compra: lo más alto posible pero al menos a medio spread rentable
        target_bid = round(min(best_bid + 0.01, mid_price - min_half_spread), 2)
        # Precio de venta: lo más bajo posible pero al menos a medio spread rentable
        target_ask = round(max(best_ask - 0.01, mid_price + min_half_spread), 2)

        # Tamaño de la orden: 25% del capital disponible en cada punta (máximo 4 vueltas concurrentes)
        order_size_usdt_buy = round(min(25.0, (self.clp_balance * 0.40) / target_bid), 4) if self.clp_balance >= 5000 else 0.0
        order_size_usdt_sell = round(min(25.0, self.usdt_balance * 0.40), 4) if self.usdt_balance >= 5.0 else 0.0

        self.my_bid_price = target_bid
        self.my_ask_price = target_ask
        self.my_bid_amount = order_size_usdt_buy
        self.my_ask_amount = order_size_usdt_sell

        # 3. Consultar cinta de transacciones recientes de usuarios reales en Buda
        trades_data = self.fetch_api("trades")
        new_fills = []
        if trades_data and "trades" in trades_data:
            entries = trades_data["trades"].get("entries", [])
            # entries format: [timestamp, amount, price, side, trade_id]
            for tr in entries:
                tr_id = int(tr[4])
                tr_amount = float(tr[1])
                tr_price = float(tr[2])
                tr_side = tr[3].lower()  # 'buy' or 'sell' del usuario que apretó mercado

                if self.last_seen_trade_id == 0:
                    self.last_seen_trade_id = tr_id
                    break

                if tr_id <= self.last_seen_trade_id:
                    continue

                # Actualizar el ID más alto visto
                self.last_seen_trade_id = max(self.last_seen_trade_id, tr_id)

                # FIL TRO DE EJECUCIÓN PASIVA REALISTA:
                # Si un usuario chileno ejecutó SELL a mercado y el precio tocó o cayó por debajo de nuestro Bid:
                if tr_side == "sell" and tr_price <= self.my_bid_price and self.my_bid_amount > 0:
                    fill_amt = min(self.my_bid_amount, tr_amount)
                    gross_cost = fill_amt * self.my_bid_price
                    fee = gross_cost * BUDA_MAKER_FEE
                    net_cost = gross_cost + fee

                    if self.clp_balance >= net_cost:
                        self.clp_balance -= net_cost
                        self.usdt_balance += fill_amt
                        self.trades_completed += 1
                        self.total_volume_clp += gross_cost
                        log_msg = f"📥 [FILL COMPRA MAKER] Compramos {fill_amt:.2f} USDT @ ${self.my_bid_price:.2f} CLP (Comisión: ${fee:.1f} CLP)"
                        new_fills.append(log_msg)
                        self.history.append({"time": datetime.now().strftime("%H:%M:%S"), "side": "BUY", "amount": fill_amt, "price": self.my_bid_price, "fee": fee})

                # Si un usuario chileno ejecutó BUY a mercado y el precio tocó o subió por encima de nuestro Ask:
                elif tr_side == "buy" and tr_price >= self.my_ask_price and self.my_ask_amount > 0:
                    fill_amt = min(self.my_ask_amount, tr_amount)
                    gross_revenue = fill_amt * self.my_ask_price
                    fee = gross_revenue * BUDA_MAKER_FEE
                    net_revenue = gross_revenue - fee

                    if self.usdt_balance >= fill_amt:
                        self.usdt_balance -= fill_amt
                        self.clp_balance += net_revenue
                        self.trades_completed += 1
                        self.total_volume_clp += gross_revenue
                        log_msg = f"📤 [FILL VENTA MAKER] Vendimos {fill_amt:.2f} USDT @ ${self.my_ask_price:.2f} CLP (Comisión: ${fee:.1f} CLP)"
                        new_fills.append(log_msg)
                        self.history.append({"time": datetime.now().strftime("%H:%M:%S"), "side": "SELL", "amount": fill_amt, "price": self.my_ask_price, "fee": fee})

            if new_fills:
                self.save_state()

        # 4. Renderizar Consola Interactiva
        spread_status = "🟢 RENTABLE (>0.85%)" if spread_pct >= (MIN_PROFITABLE_SPREAD * 100) else "🟡 ESTRECHO"
        if sys.stdout.isatty():
            print("\033[2J\033[H", end="")  # Limpiar terminal solo si es interactivo
        print("=" * 82)
        print(f"  🏛️ BUDA.COM - DIGITAL DOLLAR MARKET MAKER (SIMULADOR EN VIVO)")
        print(f"  • Par: {self.market.upper()} | Comisión Maker: {BUDA_MAKER_FEE*100:.2f}% | Spread Mínimo: {MIN_PROFITABLE_SPREAD*100:.2f}%")
        print(f"  📊 BUDA {datetime.now().strftime('%H:%M:%S')}: Bid ${best_bid:.2f} | Ask ${best_ask:.2f} | Spread: ${spread_clp:.2f} ({spread_pct:.2f}%) {spread_status}")
        print(f"  🎯 ÓRDENES MAKER: Compra {self.my_bid_amount:.2f}U @ ${self.my_bid_price:.2f} | Venta {self.my_ask_amount:.2f}U @ ${self.my_ask_price:.2f}")
        print(f"  💼 CAPITAL: ${self.clp_balance:,.0f} CLP + {self.usdt_balance:.2f} USDT = Total ${current_equity_clp:,.0f} CLP (~${current_equity_usd:.2f} USD)")
        print(f"  📈 PnL: {pnl_clp:+,.2f} CLP ({pnl_pct:+.2f}%) | Trades: {self.trades_completed} | Vol: ${self.total_volume_clp:,.0f} CLP")
        if self.history:
            print("  📜 ÚLTIMA EJECUCIÓN:")
            last = self.history[-1]
            print(f"     [{last['time']}] {last['side']} {last['amount']:.2f} USDT @ ${last['price']:.2f} CLP (Fee: ${last['fee']:.1f} CLP)")
        print("=" * 82, flush=True)


def main():
    sim = BudaMarketMakerSim("usdt-clp")
    print("Iniciando simulador de Market Making Buda...", flush=True)
    while True:
        try:
            sim.run_cycle()
            time.sleep(3.0)
        except KeyboardInterrupt:
            print("\nSimulador detenido por el usuario.")
            break
        except Exception as e:
            print(f"Error en ciclo: {e}", flush=True)
            time.sleep(5.0)


if __name__ == "__main__":
    main()
