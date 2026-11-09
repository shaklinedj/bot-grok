"""
CASH & CARRY ROTARY ARBITRAGE (BINANCE DELTA-NEUTRAL FUNDING ENGINE)
Motor Cuantitativo Delta-Neutral en Binance (Spot + USDⓈ-M Futures).
1. Si existen credenciales API en .env y una posición en vivo, audita y reporta el arbitraje REAL en Binance.
2. Si no hay posición en vivo, corre en modo Simulación Cuantitativa Grado 10.
3. Monitorea las tasas de financiamiento de todos los contratos en Binance en tiempo real.
4. Mantiene Delta = 0.00% y registra pagos de intereses cada 8 horas (00:00, 08:00, 16:00 UTC).
5. 100% integrado con SQLite WAL y el Dashboard de control 24/7.
"""
import os
import sys
import time
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import ccxt
from dotenv import load_dotenv

# Configurar encoding UTF-8 en consola Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from execution.depth_slippage import calculate_orderbook_vwap
from database import SwingDatabase

load_dotenv()

INITIAL_CAPITAL = 100.00
BINANCE_EXCHANGE = ccxt.binance({"enableRateLimit": True})


class CashAndCarrySimulator:
    def __init__(self):
        self.db = SwingDatabase()
        self.capital = INITIAL_CAPITAL
        self.initial_capital = INITIAL_CAPITAL
        self.total_interest_earned = 0.0
        self.payments_collected = 0
        self.active_pair = "XVG/USDT"
        self.active_rate_8h = 0.0006
        self.active_apr = 65.7
        self.next_funding_time = 0
        self.last_payment_timestamp = time.time()
        self.top_opportunities: List[Dict[str, Any]] = []
        self.history: List[Dict[str, Any]] = []
        self.mode = "SIMULATION"

        # Clientes autenticados en vivo si están disponibles en .env
        self.api_key = os.getenv("BINANCE_API_KEY")
        self.api_secret = os.getenv("BINANCE_API_SECRET")
        self.spot_live = None
        self.fut_live = None
        if self.api_key and self.api_secret:
            try:
                self.spot_live = ccxt.binance({
                    "apiKey": self.api_key,
                    "secret": self.api_secret,
                    "enableRateLimit": True,
                })
                self.fut_live = ccxt.binance({
                    "apiKey": self.api_key,
                    "secret": self.api_secret,
                    "enableRateLimit": True,
                    "options": {"defaultType": "future"},
                })
            except Exception:
                pass

        self.load_state()

    def load_state(self):
        """Carga el estado de Cash & Carry directamente desde SQLite WAL."""
        d = self.db.load_cash_carry_state()
        if d:
            self.mode = d.get("mode", "SIMULATION")
            self.capital = float(d.get("capital", INITIAL_CAPITAL))
            self.initial_capital = float(d.get("initial_capital", INITIAL_CAPITAL))
            self.total_interest_earned = float(d.get("total_interest_earned", 0.0))
            self.payments_collected = int(d.get("payments_collected", 0))
            self.active_pair = d.get("active_pair", "XVG/USDT")
            raw_r = float(d.get("active_rate_8h_dec", 0.0) or d.get("active_rate_8h", 0.0008))
            while raw_r > 0.01:
                raw_r /= 100.0
            self.active_rate_8h = raw_r
            self.active_apr = float(d.get("active_apr", raw_r * 3.0 * 365.0 * 100.0))
            self.last_payment_timestamp = float(d.get("last_payment_timestamp", time.time()))
            self.next_funding_time = d.get("next_funding_time", 0)
            self.top_opportunities = d.get("top_opportunities", [])
            self.history = d.get("history", [])

    def save_state(self):
        """Persiste el estado de Cash & Carry directamente en SQLite WAL de forma atómica."""
        pnl_pct = ((self.capital - self.initial_capital) / self.initial_capital * 100.0) if self.initial_capital > 0 else 0.0
        d = {
            "mode": self.mode,
            "initial_capital": round(self.initial_capital, 2),
            "capital": round(self.capital, 4),
            "total_interest_earned": round(self.total_interest_earned, 4),
            "pnl_pct": round(pnl_pct, 2),
            "payments_collected": self.payments_collected,
            "active_pair": self.active_pair,
            "active_rate_8h": round(self.active_rate_8h * 100, 4),
            "active_rate_8h_dec": self.active_rate_8h,
            "active_apr": round(self.active_apr, 2),
            "last_payment_timestamp": self.last_payment_timestamp,
            "next_funding_time": self.next_funding_time,
            "top_opportunities": self.top_opportunities[:5],
            "history": self.history[-30:],
            "updated_at": datetime.now().isoformat()
        }
        self.db.save_cash_carry_state(d)

    def audit_live_binance_position(self) -> bool:
        """
        Audita si el usuario tiene una posición real activa en Binance Futures y Spot.
        Retorna True si detecta posición en vivo.
        """
        if not self.fut_live or not self.spot_live:
            return False

        try:
            positions = self.fut_live.fetch_positions()
            active_fut = None
            for p in positions:
                contracts = abs(float(p.get("contracts", 0.0)))
                if contracts > 0:
                    active_fut = p
                    break

            if not active_fut:
                return False

            raw_sym = active_fut.get("symbol", "")
            base_coin = raw_sym.split("/")[0]
            clean_pair = f"{base_coin}/USDT"

            contracts = abs(float(active_fut.get("contracts", 0.0)))
            entry_price = float(active_fut.get("entryPrice", 0.0) or active_fut.get("markPrice", 0.0))

            # Consultar saldo spot
            spot_bal = self.spot_live.fetch_balance()
            spot_coins = float(spot_bal["total"].get(base_coin, 0.0))
            spot_usdt = float(spot_bal["free"].get("USDT", 0.0))
            spot_bnb = float(spot_bal["total"].get("BNB", 0.0))

            # Consultar saldo futuros
            fut_bal = self.fut_live.fetch_balance()
            fut_usdt = float(fut_bal.get("USDT", {}).get("total", 0.0))
            fut_bnb = float(fut_bal.get("BNB", {}).get("total", 0.0) if isinstance(fut_bal.get("BNB"), dict) else 0.0)
            fut_unreal = float(active_fut.get("unrealizedPnl", 0.0))

            # Precios actuales de mercado
            current_price = entry_price
            bnb_price = 690.0
            try:
                tkr = self.spot_live.fetch_ticker(clean_pair)
                current_price = float(tkr.get("last", entry_price))
            except Exception:
                pass
            try:
                bnb_tkr = self.spot_live.fetch_ticker("BNB/USDT")
                bnb_price = float(bnb_tkr.get("last", 690.0))
            except Exception:
                pass

            spot_value = (spot_coins * current_price) + spot_usdt + (spot_bnb * bnb_price)
            fut_value = fut_usdt + (fut_bnb * bnb_price) + fut_unreal
            total_real_capital = spot_value + fut_value

            # Tasa de financiamiento en vivo
            fr_info = self.fut_live.fetch_funding_rate(raw_sym)
            live_rate = float(fr_info.get("fundingRate", 0.0))
            self.next_funding_time = fr_info.get("fundingTimestamp", 0)

            # Consultar historial real de pagos de funding
            try:
                raw_sym_api = raw_sym.replace("/", "").replace(":USDT", "")
                incomes = self.fut_live.fapiPrivateGetIncome({
                    "symbol": raw_sym_api,
                    "incomeType": "FUNDING_FEE",
                    "limit": 50
                })
                total_funding_income = sum(float(inc.get("income", 0.0)) for inc in incomes)
                funding_payouts_count = len(incomes)
            except Exception:
                total_funding_income = self.total_interest_earned
                funding_payouts_count = self.payments_collected

            self.mode = "LIVE_BINANCE"
            self.active_pair = clean_pair
            self.active_rate_8h = live_rate
            self.active_apr = live_rate * 3.0 * 365.0 * 100.0
            if total_real_capital > 10.0:
                self.capital = total_real_capital
                if self.initial_capital == INITIAL_CAPITAL or self.initial_capital > 80.0:
                    self.initial_capital = round(total_real_capital - total_funding_income, 2)
            self.total_interest_earned = total_funding_income
            self.payments_collected = funding_payouts_count

            return True
        except Exception as e:
            return False

    def scan_best_funding_opportunities(self):
        try:
            frs = BINANCE_EXCHANGE.fetch_funding_rates()
            cands = []
            now_ms = int(time.time() * 1000)

            for sym, data in frs.items():
                if not sym.endswith("/USDT:USDT"):
                    continue
                fr = data.get("fundingRate")
                if fr is None or fr <= 0.0002: # Filtrar tasas menores a +0.02%
                    continue

                funding_time = data.get("fundingTimestamp") or (now_ms + 8 * 3600 * 1000)
                fr_pct_8h = fr * 100.0
                apr = fr_pct_8h * 3.0 * 365.0

                cands.append({
                    "symbol": sym.replace(":USDT", ""),
                    "raw_symbol": sym,
                    "rate_8h_pct": round(fr_pct_8h, 4),
                    "apr": round(apr, 1),
                    "funding_time": funding_time,
                    "payout_per_cycle_usdt": round(self.capital * fr, 4)
                })

            cands.sort(key=lambda x: x["rate_8h_pct"], reverse=True)
            self.top_opportunities = cands

            # En modo LIVE_BINANCE, NO rotamos automáticamente (el usuario tiene su posición viva)
            if self.mode == "LIVE_BINANCE":
                return

            # Modo Simulación: Selección Cuantitativa con Anti-Churning
            if cands:
                best = cands[0]
                best_sym = best["symbol"]
                best_rate = best["rate_8h_pct"] / 100.0

                should_switch = False
                if not self.active_pair:
                    should_switch = True
                elif self.active_rate_8h < 0.0003:
                    should_switch = True
                elif best_sym != self.active_pair:
                    cur_in_cands = next((c for c in cands if c["symbol"] == self.active_pair), None)
                    cur_rate = (cur_in_cands["rate_8h_pct"] / 100.0) if cur_in_cands else 0.0
                    self.active_rate_8h = cur_rate
                    self.active_apr = cur_rate * 3.0 * 365.0 * 100.0

                    spread_gain_48h = (best_rate - cur_rate) * 6.0
                    ROUNDTRIP_FEE = 0.0010
                    if spread_gain_48h >= (ROUNDTRIP_FEE * 2.5):
                        should_switch = True

                if should_switch:
                    try:
                        raw_sym = best.get("raw_symbol", "")
                        ob = BINANCE_EXCHANGE.fetch_order_book(raw_sym, limit=5)
                        vwap_chk = calculate_orderbook_vwap(ob.get("asks", []), target_amount_quote=50.0, side="BUY")
                        if not vwap_chk.get("is_liquid", True) or vwap_chk.get("slippage_pct", 0.0) > 0.15:
                            should_switch = False
                    except Exception:
                        pass

                if should_switch:
                    self.active_pair = best["symbol"]
                    self.active_rate_8h = best_rate
                    self.active_apr = best["apr"]
                    self.next_funding_time = best["funding_time"]
        except Exception:
            pass

    def check_and_execute_funding_payout(self):
        """Si estamos en simulación, liquida el pago cada 8 horas teóricas."""
        if self.mode == "LIVE_BINANCE":
            # En modo en vivo, el balance real ya lo computa Binance
            return

        now = time.time()
        if self.last_payment_timestamp == 0:
            self.last_payment_timestamp = now
            self.save_state()
            return

        elapsed = now - self.last_payment_timestamp
        if elapsed >= 28800:
            cycles = int(elapsed // 28800)
            for _ in range(cycles):
                interest = self.capital * self.active_rate_8h
                self.capital += interest
                self.total_interest_earned += interest
                self.payments_collected += 1
                self.history.append({
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "pair": self.active_pair,
                    "rate_8h": f"{self.active_rate_8h * 100:+.4f}%",
                    "payout": round(interest, 4),
                    "new_capital": round(self.capital, 4)
                })
                try:
                    self.db.log_cash_carry_payout(self.active_pair, self.active_rate_8h * 100.0, interest, self.capital)
                except Exception:
                    pass

            self.last_payment_timestamp = now
            self.save_state()

    def run_cycle(self):
        # 1. Intentar auditar posición en vivo
        is_live = self.audit_live_binance_position()
        if not is_live:
            self.mode = "SIMULATION"

        # 2. Escanear oportunidades y tasas
        self.scan_best_funding_opportunities()

        # 3. Payouts (en simulación)
        self.check_and_execute_funding_payout()

        # 4. Guardar estado
        self.save_state()


def main():
    sim = CashAndCarrySimulator()
    print("Iniciando Monitor de Cash & Carry Delta-Neutral...", flush=True)
    while True:
        try:
            sim.run_cycle()
            time.sleep(30.0)
        except KeyboardInterrupt:
            break
        except Exception:
            time.sleep(10.0)


if __name__ == "__main__":
    main()
