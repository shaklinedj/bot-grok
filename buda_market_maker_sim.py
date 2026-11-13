"""
BUDA.COM - DIGITAL DOLLAR MARKET MAKER SIMULATOR (USDT/CLP)
Simulador Cuantitativo de Casa de Cambio Pasiva (Maker) con Datos en Vivo de Buda.com.
Comisiones oficiales de BudaPro para Stablecoins (USDT/USDC):
- Tier 0 ($0 a $1,000 USD): 0.20% Maker / 0.40% Taker
- Tier 1 ($1,000 a $10,000 USD): 0.15% Maker / 0.35% Taker
- Tier 2 ($10,000 a $50,000 USD): 0.10% Maker / 0.30% Taker
- Tier 3 ($50,000 a $200,000 USD): 0.05% Maker / 0.20% Taker
- Tier 4 ($200,000+ USD / VIP MM): 0.00% Maker / 0.10% Taker (Rebates institucionales)
Abono y retiro en Pesos Chilenos por transferencia bancaria: GRATIS ($0 CLP).
"""
import os
import sys
import time
import json
import urllib.request
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from execution.stale_guard import check_spread_health
from database import SwingDatabase

# Configurar encoding UTF-8 en consola Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BUDA_API_BASE = "https://www.buda.com/api/v2"

# Configuración Inicial ($100 USD en CLP al tipo de cambio de arranque)
INITIAL_CLP_CASH = 50000.0      # $50,000 CLP para comprar USDT
INITIAL_USDT_INV = 50.0         # 50.00 USDT en inventario para vender
BASE_MAKER_FEE = 0.0020         # 0.20% Maker Tier 0 inicial


def get_buda_fee_tier(volume_usd: float) -> Tuple[float, str]:
    """Calcula la comisión Maker oficial de BudaPro para Stablecoins (USDT/USDC) según la tabla oficial."""
    if volume_usd > 24000000.0:
        return 0.0008, "Tier 13 (>US$24M: 0.08% Maker)"
    elif volume_usd >= 9500001.0:
        return 0.0009, "Tier 12 (US$9.5M-24M: 0.09% Maker)"
    elif volume_usd >= 3800001.0:
        return 0.0010, "Tier 11 (US$3.8M-9.5M: 0.10% Maker)"
    elif volume_usd >= 1500001.0:
        return 0.0011, "Tier 10 (US$1.5M-3.8M: 0.11% Maker)"
    elif volume_usd >= 600001.0:
        return 0.0012, "Tier 9 (US$600k-1.5M: 0.12% Maker)"
    elif volume_usd >= 250001.0:
        return 0.0013, "Tier 8 (US$250k-600k: 0.13% Maker)"
    elif volume_usd >= 100001.0:
        return 0.0014, "Tier 7 (US$100k-250k: 0.14% Maker)"
    elif volume_usd >= 40001.0:
        return 0.0015, "Tier 6 (US$40k-100k: 0.15% Maker)"
    elif volume_usd >= 15001.0:
        return 0.0016, "Tier 5 (US$15k-40k: 0.16% Maker)"
    elif volume_usd >= 6001.0:
        return 0.0017, "Tier 4 (US$6k-15k: 0.17% Maker)"
    elif volume_usd >= 2501.0:
        return 0.0018, "Tier 3 (US$2.5k-6k: 0.18% Maker)"
    elif volume_usd >= 1001.0:
        return 0.0019, "Tier 2 (US$1k-2.5k: 0.19% Maker)"
    else:
        return 0.0020, "Tier 1 (US$0-1k: 0.20% Maker)"


def find_liquidity_wall(orders: List[List[str]], threshold_usdt: float = 15000.0) -> Tuple[float, float, float]:
    """
    Escanea la profundidad L2 del libro de órdenes para detectar la primera muralla
    institucional relevante (orden individual >= threshold o volumen acumulado >= threshold).
    Retorna (precio_muralla, volumen_orden, volumen_acumulado).
    """
    cum = 0.0
    for price_str, amt_str in orders:
        amt = float(amt_str)
        price = float(price_str)
        cum += amt
        if amt >= threshold_usdt or cum >= threshold_usdt:
            return price, amt, cum
    if orders:
        return float(orders[0][0]), float(orders[0][1]), float(orders[0][1])
    return 0.0, 0.0, 0.0


class BudaMarketMakerSim:
    def __init__(self, market: str = "usdt-clp"):
        self.market = market.lower()
        self.clp_balance = INITIAL_CLP_CASH
        self.usdt_balance = INITIAL_USDT_INV
        self.initial_equity_clp = 0.0
        self.realized_pnl_clp = 0.0
        self.trades_completed = 0
        self.total_volume_clp = 0.0
        self.last_seen_trade_id = 0
        self.avg_cost_price = 0.0
        self.my_bid_price = 0.0
        self.my_ask_price = 0.0
        self.my_bid_amount = 0.0
        self.my_ask_amount = 0.0
        self.best_bid = 0.0
        self.best_ask = 0.0
        self.mid_price = 0.0
        self.spread_clp = 0.0
        self.spread_pct = 0.0
        self.current_equity_clp = 0.0
        self.current_equity_usd = 0.0
        
        # Métricas Adaptativas L2 & Macro-Trend
        self.strategy_mode = "INITIALIZING"
        self.bid_wall_price = 0.0
        self.ask_wall_price = 0.0
        self.bid_wall_vol = 0.0
        self.ask_wall_vol = 0.0
        self.wall_pocket_spread = 0.0
        self.wall_pocket_pct = 0.0
        self.current_tier_label = "Tier 0 (0.20% Maker)"
        self.current_maker_fee = BASE_MAKER_FEE
        self.var_24h = 0.0
        
        self.history: List[Dict[str, Any]] = []
        self._last_log_ts = 0.0
        self._last_mode = ""
        self.db = SwingDatabase()
        self.load_state()

    def fetch_api(self, endpoint: str) -> Optional[Dict[str, Any]]:
        url = f"{BUDA_API_BASE}/markets/{self.market}/{endpoint}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BudaSim/2.0)"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            return None

    def fetch_macro_trend(self) -> Dict[str, Any]:
        data = self.fetch_api("ticker")
        if data and "ticker" in data:
            t = data["ticker"]
            try:
                var_24h = float(t.get("price_variation_24h", 0.0))
            except Exception:
                var_24h = 0.0
            return {"var_24h": var_24h}
        return {"var_24h": 0.0}

    def _reconstruct_avg_cost_from_db(self) -> float:
        """Reconstruye el costo promedio real del inventario actual usando las últimas compras en SQLite."""
        try:
            with self.db._get_connection() as conn:
                rows = conn.execute(
                    "SELECT side, price, amount, total_clp, fee_clp FROM buda_trades WHERE side='BUY' ORDER BY id DESC"
                ).fetchall()
            rem = max(self.usdt_balance, 0.0)
            if rem <= 0.0 or not rows:
                return 0.0
            tot_clp = 0.0
            tot_amt = 0.0
            for r in rows:
                take = min(rem, float(r["amount"]))
                fee_mult = (1.0 + (float(r["fee_clp"]) / max(float(r["total_clp"]), 1e-6)))
                tot_clp += take * float(r["price"]) * fee_mult
                tot_amt += take
                rem -= take
                if rem <= 0.0:
                    break
            return round(tot_clp / tot_amt, 4) if tot_amt > 0 else 0.0
        except Exception:
            return 0.0

    def load_state(self):
        """Carga el estado de Buda MM directamente desde SQLite WAL."""
        d = self.db.load_buda_state()
        if d:
            self.clp_balance = float(d.get("clp_balance", INITIAL_CLP_CASH))
            self.usdt_balance = float(d.get("usdt_balance", INITIAL_USDT_INV))
            self.initial_equity_clp = float(d.get("initial_equity_clp", 0.0))
            self.realized_pnl_clp = float(d.get("realized_pnl_clp", 0.0))
            self.trades_completed = int(d.get("trades_completed", 0))
            self.total_volume_clp = float(d.get("total_volume_clp", 0.0))
            self.last_seen_trade_id = int(d.get("last_seen_trade_id", 0))
            self.avg_cost_price = float(d.get("avg_cost_price") or 0.0)
            self.history = d.get("history", [])
        if self.avg_cost_price <= 0.0 and self.usdt_balance > 0.0:
            reconstructed = self._reconstruct_avg_cost_from_db()
            if reconstructed > 0.0:
                self.avg_cost_price = reconstructed

    def save_state(self):
        """Persiste el estado de Buda MM directamente en SQLite WAL de forma atómica."""
        pnl_pct = (self.realized_pnl_clp / self.initial_equity_clp * 100.0) if self.initial_equity_clp > 0 else 0.0
        d = {
            "market": self.market.upper(),
            "strategy_mode": self.strategy_mode,
            "buda_tier": self.current_tier_label,
            "maker_fee_pct": round(self.current_maker_fee * 100.0, 3),
            "clp_balance": round(self.clp_balance, 2),
            "usdt_balance": round(self.usdt_balance, 4),
            "avg_cost_price": round(self.avg_cost_price, 4),
            "initial_equity_clp": round(self.initial_equity_clp, 2),
            "current_equity_clp": round(self.current_equity_clp, 2),
            "current_equity_usd": round(self.current_equity_usd, 2),
            "realized_pnl_clp": round(self.realized_pnl_clp, 2),
            "pnl_clp": round(self.realized_pnl_clp, 2),
            "pnl_pct": round(pnl_pct, 2),
            "trades_completed": self.trades_completed,
            "total_volume_clp": round(self.total_volume_clp, 2),
            "best_bid": round(self.best_bid, 2),
            "best_ask": round(self.best_ask, 2),
            "mid_price": round(self.mid_price, 2),
            "spread_clp": round(self.spread_clp, 2),
            "spread_pct": round(self.spread_pct, 2),
            "bid_wall_price": round(self.bid_wall_price, 2),
            "ask_wall_price": round(self.ask_wall_price, 2),
            "bid_wall_vol": round(self.bid_wall_vol, 1),
            "ask_wall_vol": round(self.ask_wall_vol, 1),
            "wall_pocket_spread": round(self.wall_pocket_spread, 2),
            "wall_pocket_pct": round(self.wall_pocket_pct, 2),
            "var_24h_pct": round(self.var_24h * 100.0, 2),
            "my_bid_price": round(self.my_bid_price, 2),
            "my_ask_price": round(self.my_ask_price, 2),
            "my_bid_amount": round(self.my_bid_amount, 4),
            "my_ask_amount": round(self.my_ask_amount, 4),
            "last_seen_trade_id": self.last_seen_trade_id,
            "history": self.history[-50:],
            "updated_at": datetime.now().isoformat()
        }
        self.db.save_buda_state(d)

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
            self.avg_cost_price = mid_price
            self.save_state()

        if self.avg_cost_price <= 0.0:
            self.avg_cost_price = mid_price

        current_equity_clp = self.clp_balance + (self.usdt_balance * mid_price)
        current_equity_usd = current_equity_clp / mid_price if mid_price > 0 else 100.0

        self.best_bid = best_bid
        self.best_ask = best_ask
        self.mid_price = mid_price
        self.spread_clp = spread_clp
        self.spread_pct = spread_pct
        self.current_equity_clp = current_equity_clp
        self.current_equity_usd = current_equity_usd

        # Filtro Grado 10: Fuga de liquidez o spread blowout (Toxic flow protection)
        spread_check = check_spread_health(best_bid, best_ask, baseline_spread_pct=0.48, max_spread_multiplier=3.5)
        if not spread_check["valid"]:
            self.my_bid_amount = 0.0
            self.my_ask_amount = 0.0
            self.strategy_mode = "HALTED_TOXIC_FLOW"
            self.save_state()
            return

        # 2. Detección Cuantitativa de Murallas Institucionales L2
        bid_wall_p, bid_wall_amt, _ = find_liquidity_wall(bids, threshold_usdt=15000.0)
        ask_wall_p, ask_wall_amt, _ = find_liquidity_wall(asks, threshold_usdt=15000.0)
        wall_pocket_spread = ask_wall_p - bid_wall_p
        wall_pocket_pct = (wall_pocket_spread / bid_wall_p) * 100.0 if bid_wall_p > 0 else 0.0

        self.bid_wall_price = bid_wall_p
        self.ask_wall_price = ask_wall_p
        self.bid_wall_vol = bid_wall_amt
        self.ask_wall_vol = ask_wall_amt
        self.wall_pocket_spread = wall_pocket_spread
        self.wall_pocket_pct = wall_pocket_pct

        # 3. Macro-Tendencia 24h & Tier de Comisiones BudaPro
        macro = self.fetch_macro_trend()
        self.var_24h = macro["var_24h"]

        vol_usd = self.total_volume_clp / mid_price if mid_price > 0 else 0.0
        self.current_maker_fee, self.current_tier_label = get_buda_fee_tier(vol_usd)
        roundtrip_fee = self.current_maker_fee * 2
        min_profitable_spread = max(0.0044, roundtrip_fee + 0.0010)  # Escalable según Tier (comisión + 0.10% neto)

        # 4. Gestión Cuantitativa de Inventario, Interés Compuesto & Cotización Asimétrica
        usdt_val_clp = self.usdt_balance * mid_price
        inv_ratio_usdt = (usdt_val_clp / current_equity_clp) if current_equity_clp > 0 else 0.50

        # Precio exacto de Break-Even (avg_cost_price ya incluye comisión de compra; solo se cubre comisión de venta)
        be_ask_price = round(self.avg_cost_price / (1.0 - self.current_maker_fee), 2)
        half_spread = mid_price * (min_profitable_spread / 2.0)

        # Caso A: Exceso de CLP / Déficit de USDT (< 42% del capital en USDT) -> Priorizar compra en punta
        if inv_ratio_usdt < 0.42:
            self.strategy_mode = "SKEW_RELOAD_USDT"
            buy_pct = 0.80 if inv_ratio_usdt < 0.28 else 0.70
            sell_pct = 0.35 if inv_ratio_usdt < 0.28 else 0.45
            target_bid = round(best_bid + 0.01, 2)
            target_ask = round(max(best_ask, be_ask_price, mid_price * (1.0 + min_profitable_spread)), 2)
            order_size_usdt_buy = round((self.clp_balance * buy_pct) / target_bid, 4) if self.clp_balance >= 3000 else 0.0
            order_size_usdt_sell = round(self.usdt_balance * sell_pct, 4) if self.usdt_balance >= 2.0 else 0.0

        # Caso B: Exceso de USDT (> 58% del capital en USDT) -> Venta en punta (si hay ganancia) o TWAP defensivo
        elif inv_ratio_usdt > 0.58:
            target_bid = round(min(best_bid, mid_price - half_spread), 2)
            buy_pct = 0.35 if inv_ratio_usdt > 0.72 else 0.45
            order_size_usdt_buy = round((self.clp_balance * buy_pct) / target_bid, 4) if self.clp_balance >= 3000 else 0.0

            # Sub-caso B1: El mercado paga por encima de nuestro costo real -> Liquidar exceso en la punta (#1 Ask)
            if best_ask >= be_ask_price:
                self.strategy_mode = "INVENTORY_SKEW_SELL" if inv_ratio_usdt <= 0.75 else "DEFENSIVE_BREAK_EVEN"
                sell_pct = 0.80 if inv_ratio_usdt > 0.72 else 0.70
                target_ask = round(max(be_ask_price, best_ask - 0.01), 2)
                order_size_usdt_sell = round(self.usdt_balance * sell_pct, 4) if self.usdt_balance >= 2.0 else 0.0

            # Sub-caso B2: Caída brusca bajo nuestro Break-Even -> Desescalada suave TWAP para no congelar capital
            else:
                self.strategy_mode = "SOFT_DEESCALATION_TWAP"
                soft_floor = round(be_ask_price * 0.9975, 2)
                target_ask = round(max(soft_floor, best_ask), 2)
                sell_pct = 0.35 if inv_ratio_usdt > 0.78 else 0.25
                order_size_usdt_sell = round(self.usdt_balance * sell_pct, 4) if self.usdt_balance >= 2.0 else 0.0

        # Caso C: Inventario equilibrado (42% - 58%) -> Spread Puro Rentable con Interés Compuesto Agresivo (70%)
        else:
            if spread_pct >= (min_profitable_spread * 100.0):
                self.strategy_mode = "WIDE_SPREAD_MAKER"
                target_bid = round(best_bid + 0.01, 2)
                target_ask = round(max(be_ask_price, best_ask - 0.01), 2)
            else:
                self.strategy_mode = "SAFE_SYMMETRIC_SPREAD"
                target_bid = round(mid_price - half_spread, 2)
                target_ask = round(max(be_ask_price, mid_price + half_spread), 2)

            # Utilización activa del 70% del saldo por lado para acelerar rotación e interés compuesto
            order_size_usdt_buy = round((self.clp_balance * 0.70) / target_bid, 4) if self.clp_balance >= 3000 else 0.0
            order_size_usdt_sell = round(self.usdt_balance * 0.70, 4) if self.usdt_balance >= 2.0 else 0.0

        self.my_bid_price = target_bid
        self.my_ask_price = target_ask
        self.my_bid_amount = order_size_usdt_buy
        self.my_ask_amount = order_size_usdt_sell

        # 5. Consultar cinta de transacciones recientes de usuarios reales en Buda
        trades_data = self.fetch_api("trades")
        new_fills = []
        if trades_data and "trades" in trades_data:
            entries = trades_data["trades"].get("entries", [])
            if self.last_seen_trade_id == 0 and entries:
                self.last_seen_trade_id = max(int(e[4]) for e in entries)
            else:
                # Ordenar cronológicamente ascendente para no saltar trades en ráfagas dentro del mismo ciclo
                for tr in sorted(entries, key=lambda x: int(x[4])):
                    tr_id = int(tr[4])
                    tr_amount = float(tr[1])
                    tr_price = float(tr[2])
                    tr_side = tr[3].lower()

                    if tr_id <= self.last_seen_trade_id:
                        continue

                    self.last_seen_trade_id = tr_id

                    # Si un usuario chileno ejecutó SELL a mercado y el precio tocó o cayó por debajo de nuestro Bid:
                    if tr_side == "sell" and tr_price <= self.my_bid_price and self.my_bid_amount > 0:
                        fill_amt = min(self.my_bid_amount, tr_amount)
                        gross_cost = fill_amt * self.my_bid_price
                        fee = gross_cost * self.current_maker_fee
                        net_cost = gross_cost + fee

                        if self.clp_balance >= net_cost:
                            tot_val_prev = self.usdt_balance * self.avg_cost_price
                            new_usdt = self.usdt_balance + fill_amt
                            self.avg_cost_price = (tot_val_prev + net_cost) / new_usdt if new_usdt > 0 else self.my_bid_price

                            self.clp_balance -= net_cost
                            self.usdt_balance = new_usdt
                            self.my_bid_amount = max(0.0, self.my_bid_amount - fill_amt)
                            self.trades_completed += 1
                            self.total_volume_clp += gross_cost
                            log_msg = f"📥 [FILL COMPRA MAKER] Compramos {fill_amt:.2f} USDT @ ${self.my_bid_price:.2f} CLP (Fee {self.current_maker_fee*100:.2f}%: ${fee:.1f} CLP)"
                            new_fills.append(log_msg)
                            self.history.append({"time": datetime.now().strftime("%H:%M:%S"), "side": "BUY", "amount": fill_amt, "price": self.my_bid_price, "fee": fee})
                            try:
                                self.db.log_buda_trade("BUY", self.my_bid_price, fill_amt, gross_cost, fee, 0.0, "Maker BUY fill")
                            except Exception:
                                pass

                    # Si un usuario chileno ejecutó BUY a mercado y el precio tocó o subió por encima de nuestro Ask:
                    elif tr_side == "buy" and tr_price >= self.my_ask_price and self.my_ask_amount > 0:
                        fill_amt = min(self.my_ask_amount, tr_amount, self.usdt_balance)
                        gross_revenue = fill_amt * self.my_ask_price
                        fee = gross_revenue * self.current_maker_fee
                        net_revenue = gross_revenue - fee

                        if fill_amt > 0 and self.usdt_balance >= fill_amt:
                            cost_of_sold = fill_amt * self.avg_cost_price
                            trade_profit = net_revenue - cost_of_sold
                            self.realized_pnl_clp += trade_profit

                            self.usdt_balance -= fill_amt
                            self.clp_balance += net_revenue
                            self.my_ask_amount = max(0.0, self.my_ask_amount - fill_amt)
                            self.trades_completed += 1
                            self.total_volume_clp += gross_revenue
                            log_msg = f"📤 [FILL VENTA MAKER] Vendimos {fill_amt:.2f} USDT @ ${self.my_ask_price:.2f} CLP | Ganancia neta: {trade_profit:+.1f} CLP (Fee {self.current_maker_fee*100:.2f}%: ${fee:.1f} CLP)"
                            new_fills.append(log_msg)
                            self.history.append({"time": datetime.now().strftime("%H:%M:%S"), "side": "SELL", "amount": fill_amt, "price": self.my_ask_price, "fee": fee, "profit": trade_profit})
                            try:
                                self.db.log_buda_trade("SELL", self.my_ask_price, fill_amt, gross_revenue, fee, trade_profit, "Maker SELL fill")
                            except Exception:
                                pass

        self.save_state()

        # 6. Renderizar Consola Interactiva (Con throttle en modo daemon para evitar logs gigantes)
        now_ts = time.time()
        should_log = sys.stdout.isatty() or bool(new_fills) or (self.strategy_mode != self._last_mode) or (now_ts - self._last_log_ts >= 300.0)
        if not should_log:
            return
        self._last_log_ts = now_ts
        self._last_mode = self.strategy_mode

        for f_msg in new_fills:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {f_msg}", flush=True)

        spread_status = "🟢 RENTABLE" if spread_pct >= (min_profitable_spread * 100) else "🟡 ESTRECHO"
        net_margin_proj = ((self.my_ask_price - self.my_bid_price) / self.my_bid_price * 100.0) - (roundtrip_fee * 100.0) if self.my_bid_price > 0 else 0.0

        if sys.stdout.isatty():
            print("\033[2J\033[H", end="")
        print("=" * 84)
        print(f"  🏛️ BUDA.COM - DIGITAL DOLLAR MARKET MAKER (SIMULADOR EN VIVO)")
        print(f"  • Estrategia: {self.strategy_mode} | Nivel: {self.current_tier_label}")
        print(f"  • Maker Fee: {self.current_maker_fee*100:.2f}% | Spread Mínimo Requerido: {min_profitable_spread*100:.2f}%")
        print(f"  📊 BUDA {datetime.now().strftime('%H:%M:%S')}: Bid ${best_bid:.2f} | Ask ${best_ask:.2f} | Spread Int.: ${spread_clp:.2f} ({spread_pct:.2f}%) {spread_status}")
        print(f"  🧱 MURALLAS L2: Bid Wall ${self.bid_wall_price:.2f} ({self.bid_wall_vol:,.0f}U) | Ask Wall ${self.ask_wall_price:.2f} ({self.ask_wall_vol:,.0f}U)")
        print(f"  👝 BOLSILLO MURALLAS: ${self.wall_pocket_spread:.2f} CLP ({self.wall_pocket_pct:.2f}%) | Margen Neto Estimado: {net_margin_proj:+.2f}%")
        print(f"  🎯 ÓRDENES MAKER: Compra {self.my_bid_amount:.2f}U @ ${self.my_bid_price:.2f} | Venta {self.my_ask_amount:.2f}U @ ${self.my_ask_price:.2f} (Costo: ${self.avg_cost_price:.2f} | BE: ${be_ask_price:.2f})")
        print(f"  💼 CAPITAL: ${self.clp_balance:,.0f} CLP + {self.usdt_balance:.2f} USDT = Total ${current_equity_clp:,.0f} CLP (~${current_equity_usd:.2f} USD)")
        print(f"  📈 PnL Realizado: {self.realized_pnl_clp:+,.2f} CLP | Trades: {self.trades_completed} | Vol: ${self.total_volume_clp:,.0f} CLP (~${vol_usd:,.0f} USD)")
        if self.history:
            print("  📜 ÚLTIMA EJECUCIÓN:")
            last = self.history[-1]
            print(f"     [{last['time']}] {last['side']} {last['amount']:.2f} USDT @ ${last['price']:.2f} CLP (Fee: ${last['fee']:.1f} CLP)")
        print("=" * 84, flush=True)


def main():
    sim = BudaMarketMakerSim("usdt-clp")
    print("Iniciando simulador de Market Making Buda con Adaptación de Murallas...", flush=True)
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
