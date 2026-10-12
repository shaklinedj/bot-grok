"""
Paper Trading Agent - Quantitative Spot Neutral Grid v12
============================================================================================
Novedades Arquitecturales v12:
1. Mallas Neutrales Cuantitativas Adaptativas (Estilo Pionex):
   - Mallas centradas con 6 a 7 líneas dinámicas calculadas por ATR 1h.
   - Monto mínimo por orden: $10.00 USDT (MIN_ORDER_USDT = 10.0).
   - Simetría aritmética rigurosa: paso fijo `step_size` por nivel con reinversión de utilidades.
   - Cruce realista de rango de precios por tick [tick_low, tick_high] y ejecución secuencial.
2. Interés Compuesto Real y Reciclaje de Liquidez:
   - Toda ganancia generada por compras/ventas se reintegra a la caja disponible.
   - Cierre por Victoria Total libera el 100% del capital para rotación inmediata.
3. Dashboard Reactivo en Tiempo Real:
   - Servidor HTTP integrado (puerto 8888) con streaming continuo.
   - Historial de equity completo muestreado y visualización interactiva.
4. Resiliencia y Concurrencia Robusta:
   - Bloqueo CSV_LOGS_LOCK para escrituras y lecturas seguras de métricas.
   - Respaldo automático de archivos de estado corruptos (.corrupt.bak).
   - Memoria cerebral persistente (pnl y blacklists) con decaimiento temporal.
"""

import sys
import io
import os
import time
import csv
import json
import random
import math
import shutil
import threading
import http.server
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field, asdict
import urllib.request
from dotenv import load_dotenv

load_dotenv()

_random_seed_env = os.environ.get("RANDOM_SEED")
if _random_seed_env is not None and _random_seed_env.strip() != "":
    try:
        random.seed(int(_random_seed_env))
    except ValueError:
        pass

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import ccxt
import pandas as pd
import numpy as np
import dashboard_spa
from self_eval import TradeAuditor
from meta_labeling import MetaLabelingGatekeeper, compute_kaufman_efficiency_ratio
from macro_radar import MacroRegimeEngine, evaluate_multi_factor_arsenal, fetch_order_book_microstructure
from ai_auditor import ai_auditor
from agent_committee import agent_committee
from db_vault import vault
from ou_estimator import estimate_ornstein_uhlenbeck


# ====================== CONFIGURACIÓN GENERAL ======================
INITIAL_CAPITAL = 80.0
MIN_EQUITY_RATIO = 0.60                 # Umbral de supervivencia: 60% ($48.00 USDT)
MAX_RISK_SLOTS = 15                     # Múltiples mallas concurrentes simultáneas
MAX_TOTAL_POSITIONS = 15                # Mallas ilimitadas según capital disponible en caja
TOP_N_SCAN = 12                         # Considerar y mostrar las 12 mejores oportunidades del mercado
COMPOUND_ALLOCATION_PCT = 0.20          # Asignación prudente por oportunidad
MIN_ORDER_USDT = 10.0                   # Mínimo $10.00 USDT (estricto estándar Binance Spot)

CHECK_INTERVAL_SECONDS = 1.5            # Ticks reactivos de alta velocidad cada 1.5 segundos
FAST_SCAN_INTERVAL_SECONDS = 20         # Escaneo micro 15m / PID cada 20 segundos
MACRO_SCAN_INTERVAL_SECONDS = 60        # Auditoría macro 4h / 1d cada 60 segundos
FEE_RATE = 0.001                        # 0.10% Binance Maker/Taker
HTTP_PORT = 8888                        # Puerto para el dashboard dinámico en vivo

# Parámetros Institucionales Recalibrados (Post-Mortem de 88 trades)
EARLY_BREAK_EVEN_TRIGGER_PCT = 2.50     # Blindar solo tras despegue REAL al +2.50% (el 1.80% anterior causaba falsas activaciones)
EARLY_BREAK_EVEN_LOCK_PCT = 0.50        # Precio asegurado: +0.50% (cubre comisiones con margen)
DEFAULT_TP1_GAIN_PCT = 2.20             # TP1 alcanzable al +2.20% (el 2.80% anterior solo se alcanzaba 27% del tiempo)
RUNNER_TRAILING_TRIGGER_PCT = 3.20      # Activar trailing del runner al +3.20%
RUNNER_ATR_MULT = 2.00                  # Trailing holgado (2.0x ATR): deja respirar al runner


# Directorios de Logs y Estados Persistentes
LOG_DIR = "paper_logs"
EQUITY_LOG = os.path.join(LOG_DIR, "equity_history.csv")
TRADES_LOG = os.path.join(LOG_DIR, "trades.csv")
BRAIN_STATE_FILE = os.path.join(LOG_DIR, "brain_state.json")
PORTFOLIO_STATE_FILE = os.path.join(LOG_DIR, "portfolio_state.json")
DASHBOARD_HTML_LOCAL = os.path.join(LOG_DIR, "dashboard.html")
LIVE_STATE_FILE_LOCAL = os.path.join(LOG_DIR, "live_state.json")

CSV_LOGS_LOCK = threading.Lock()

ARTIFACT_DIR = os.environ.get("ARTIFACT_DIR", r"C:\Users\Dell\.gemini\antigravity\brain\b5df651c-3f00-4891-beb9-ba32792ed811")
DASHBOARD_HTML_ARTIFACT = os.path.join(ARTIFACT_DIR, "dashboard.html") if (ARTIFACT_DIR and os.path.exists(ARTIFACT_DIR)) else ""
LIVE_STATE_FILE_ARTIFACT = os.path.join(ARTIFACT_DIR, "live_state.json") if (ARTIFACT_DIR and os.path.exists(ARTIFACT_DIR)) else ""

STABLE_BASES = {
    "USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "EUR", "GBP", "USD1",
    "USDE", "PYUSD", "AEUR", "EURI", "USTC", "WBTC", "BTCST", "RLUSD", "USDS"
}

LAST_AGENT_PCT: float = 0.0  # Último % decidido por los agentes IA (para el dashboard)

# ====================== EXCHANGE ======================
exchange = ccxt.binance({
    "enableRateLimit": True,
    "options": {"defaultType": "spot"},
    "timeout": 30000
})

LATEST_LIVE_STATE: Dict = {}
COMMAND_QUEUE: List[Dict] = []
COMMAND_QUEUE_LOCK = threading.Lock()


def _atomic_json_dump(path: str, data, **kwargs):
    """Escritura atómica (tmp + os.replace) para no corromper el estado si el proceso muere a mitad de escritura."""
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, **kwargs)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def get_tick_price_range(trades: list, previous_price: float, current_price: float) -> Tuple[float, float]:
    trade_prices = []
    for trade in trades:
        try:
            trade_price = float(trade.get("price", 0.0))
            if trade_price > 0:
                trade_prices.append(trade_price)
        except (AttributeError, TypeError, ValueError):
            continue
    observed_prices = trade_prices + [previous_price, current_price]
    return min(observed_prices), max(observed_prices)


def get_position_volume_24h(position) -> float:
    features = getattr(position, "features_at_entry", None)
    if not isinstance(features, dict):
        return 20_000_000.0
    volume_24h = features.get("volume_24h")
    if volume_24h is None and features.get("volume_m") is not None:
        try:
            volume_24h = float(features["volume_m"]) * 1_000_000
        except (TypeError, ValueError):
            volume_24h = None
    try:
        return max(0.0, float(volume_24h)) if volume_24h is not None else 20_000_000.0
    except (TypeError, ValueError):
        return 20_000_000.0


def active_grid_orders(lines: list, side: str) -> list:
    return [line for line in lines if line.get("active") and line.get("side") == side]


def compress_grid_spacing(grid: "GridPosition", current_price: float) -> Optional[float]:
    if grid.step_pct <= 0.0042:
        return None
    old_step = grid.step_pct
    grid.step_pct = max(0.0040, grid.step_pct * 0.88)
    grid.step_size = current_price * grid.step_pct
    return old_step


def evaluate_anomaly_trailing_down(
    grid: "GridPosition",
    symbol: str,
    current_price: float,
    dev_floor_pct: float,
    latest_opportunities: list,
    btc_macro_state: str
) -> tuple[bool, str, float]:
    """
    Evalúa institucionalmente si una malla en anomalía (bajo el piso) califica para
    desplazar su rango hacia abajo (Trailing Down / Escalón de descuento) o si debe
    ir a modo defensivo en Breakeven sin promediar a la baja.
    """
    opp = next((o for o in (latest_opportunities or []) if o.get("symbol") == symbol), None)
    score = float(opp.get("score", 0.0)) if opp else 0.0
    shifts = getattr(grid, "trailing_down_shifts", 0)

    if shifts >= 1:
        return False, f"Límite de Trailing Down alcanzado ({shifts}/1). Protegiendo capital.", score
    if dev_floor_pct <= -3.0:
        return False, f"Caída profunda ({dev_floor_pct:+.2f}%). Alto riesgo de capitulación.", score
    if btc_macro_state in ("PANIC_DUMP", "EXTREME_BEAR"):
        return False, f"Macro BTC hostil ({btc_macro_state}). Prohibido desplazar compras.", score
    if score < 65.0:
        return False, f"Score insuficiente ({score:.1f} < 65.0). Pureza no confirmada.", score

    return True, f"Re-evaluación positiva: Score {score:.1f} >= 65 en soporte institucional.", score


def apply_trailing_down_shift(grid: "GridPosition", current_price: float) -> tuple[float, float]:
    """
    Desplaza el rango de la malla hacia abajo para capturar el rebote en el siguiente
    escalón de liquidez institucional.
    """
    shift_amount = (grid.grid_upper - grid.grid_lower) * 0.40
    grid.grid_lower = max(0.000001, grid.grid_lower - shift_amount)
    grid.grid_upper = max(current_price * 1.005, grid.grid_upper - shift_amount)
    grid.trailing_down_shifts = getattr(grid, "trailing_down_shifts", 0) + 1
    grid.anomaly_start_ts = 0.0  # Reiniciar reloj de anomalía al re-anclar en nuevo piso
    if grid.grid_lines > 1:
        grid.step_size = (grid.grid_upper - grid.grid_lower) / (grid.grid_lines - 1)
        grid.step_pct = max(0.0042, grid.step_size / grid.grid_lower)
    grid.freeze_buys = False
    return grid.grid_lower, grid.grid_upper


def apply_trailing_up_shift(grid: "GridPosition", bot: "PaperBot", current_price: float) -> tuple[float, float, float]:
    """
    Desplaza el rango de la malla hacia arriba (Trailing Up):
    - Cancela compras bajas ociosas recuperando su USDT líquido.
    - Desplaza el piso y techo hacia arriba siguiendo la inercia alcista.
    - Coloca compras en el nuevo soporte y ventas en los nuevos techos.
    """
    shift_amount = (grid.grid_upper - grid.grid_lower) * 0.35
    grid.grid_lower += shift_amount
    grid.grid_upper = max(current_price * 1.015, grid.grid_upper + shift_amount)
    grid.trailing_up_shifts = getattr(grid, "trailing_up_shifts", 0) + 1

    if grid.grid_lines > 1:
        grid.step_size = (grid.grid_upper - grid.grid_lower) / (grid.grid_lines - 1)
        grid.step_pct = max(0.0042, grid.step_size / grid.grid_lower)

    # Cancelar compras que quedaron demasiado abajo (lejos del precio vivo)
    recovered_cash = 0.0
    for l in grid.lines:
        if l.get("active") and l.get("side") == "buy" and l["price"] < (grid.grid_lower * 0.995):
            recovered_cash += (l["price"] * l["amount"])
            l["active"] = False

    bot.cash += recovered_cash
    grid.freeze_buys = False
    grid.out_of_range_ticks = 0
    grid.status_msg = f"Trailing Up #{grid.trailing_up_shifts}: Rango subido a ${grid.grid_lower:.4f}-${grid.grid_upper:.4f}"

    return grid.grid_lower, grid.grid_upper, recovered_cash


# ====================== CEREBRO DE APRENDIZAJE POR REFUERZO ======================
class ReinforcementBrain:
    def __init__(self):
        self.generation = 1
        self.learning_rate = 0.08
        
        self.weights = {
            "w_adx": 1.40,
            "w_pullback": 2.50,
            "w_rsi": 1.50,
            "w_volatility": 1.80,
            "w_volume": 1.80
        }
        
        self.tp1_gain_pct = DEFAULT_TP1_GAIN_PCT
        self.sl_atr_mult = 2.80                  # Stop Loss AMPLIO fuera del ruido (2.80x ATR) — el 2.20x anterior disparaba 32 SL falsos
        self.min_score_required = 65.0           # Umbral institucional alto (Cero entradas por entrar)
        
        self.coin_pnl_memory: Dict[str, List[float]] = {}
        self.coin_blacklist_until: Dict[str, float] = {}
        self.evolution_history: List[Dict] = []
        self.mfe_samples: List[float] = []
        
        self.load_state()

    def save_state(self):
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            now_ts = time.time()
            pruned_pnl_mem = {k: v[-30:] for k, v in self.coin_pnl_memory.items()}
            active_blacklist = {k: v for k, v in self.coin_blacklist_until.items() if v > now_ts}
            data = {
                "generation": self.generation,
                "weights": self.weights,
                "tp1_gain_pct": round(self.tp1_gain_pct, 3),
                "sl_atr_mult": round(self.sl_atr_mult, 3),
                "min_score_required": round(self.min_score_required, 2),
                "evolution_history": self.evolution_history[-10:],
                "mfe_samples": self.mfe_samples[-30:],
                "coin_pnl_memory": pruned_pnl_mem,
                "coin_blacklist_until": active_blacklist
            }
            _atomic_json_dump(BRAIN_STATE_FILE, data, indent=2)
        except Exception as e:
            print(f"  ⚠️ [Error al guardar cerebro]: {e}", flush=True)

    def load_state(self):
        if os.path.exists(BRAIN_STATE_FILE):
            try:
                with open(BRAIN_STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.generation = data.get("generation", 1)
                    self.weights = data.get("weights", self.weights)
                    self.tp1_gain_pct = float(data.get("tp1_gain_pct", DEFAULT_TP1_GAIN_PCT))
                    self.sl_atr_mult = float(data.get("sl_atr_mult", 2.80))
                    self.min_score_required = float(data.get("min_score_required", 65.0))
                    self.evolution_history = data.get("evolution_history", [])
                    self.mfe_samples = data.get("mfe_samples", [])
                    self.coin_pnl_memory = {k: list(v)[-30:] for k, v in data.get("coin_pnl_memory", {}).items()}
                    now_ts = time.time()
                    self.coin_blacklist_until = {k: float(v) for k, v in data.get("coin_blacklist_until", {}).items() if float(v) > now_ts}
            except (json.JSONDecodeError, Exception) as e:
                bak_file = f"{BRAIN_STATE_FILE}.corrupt.{int(time.time())}.bak"
                try:
                    shutil.copy2(BRAIN_STATE_FILE, bak_file)
                    print(f"  🚨 [ALERTA CEREBRO CORRUPTO] Archivo dañado respaldado en {bak_file}. Error: {e}", flush=True)
                except Exception as bak_err:
                    print(f"  🚨 [ALERTA CEREBRO CORRUPTO] Error respaldando cerebro: {bak_err}", flush=True)

    def time_decay(self):
        """Decaimiento temporal suave hacia 65.0 para evitar bloqueo indefinido de entradas"""
        if self.min_score_required > 65.0:
            self.min_score_required = max(65.0, round(self.min_score_required - 0.05, 3))
        # Limpieza periódica de monedas expiradas de blacklist
        now_ts = time.time()
        expired = [k for k, v in self.coin_blacklist_until.items() if v <= now_ts]
        for k in expired:
            del self.coin_blacklist_until[k]

    def evaluate_signature_score(self, adx: float, dist_ema20: float, rsi: float, atr_pct: float, volume_m: float) -> float:
        adx_norm = min(10.0, max(0.0, (adx - 18.0) / 2.5))
        pullback_norm = max(0.0, 10.0 - abs(dist_ema20) * 3.5)
        rsi_norm = max(0.0, 10.0 - max(0.0, (rsi - 48.0) / 2.0))
        volat_norm = min(10.0, max(0.0, atr_pct * 1.8))
        vol_norm = min(10.0, max(0.0, math.log10(max(1.0, volume_m)) * 4.0))

        score = (
            (adx_norm * self.weights["w_adx"]) +
            (pullback_norm * self.weights["w_pullback"]) +
            (rsi_norm * self.weights["w_rsi"]) +
            (volat_norm * self.weights["w_volatility"]) +
            (vol_norm * self.weights["w_volume"])
        ) * 1.3
        return round(score, 1)

    def learn_from_trade(self, symbol: str, strategy: str, entry_p: float, exit_p: float,
                          pnl: float, exit_reason: str, max_gain_pct: float, features: Dict):
        """
        Aprendizaje dinámico genuino:
        - Si el trade pierde: NO ceñir el SL (eso causa más pérdidas). En su lugar,
          AUMENTAR la exigencia de entrada (min_score_required) y vetar la moneda si tropieza dos veces.
        - Si el trade gana: premiar la paciencia y normalizar gradualmente el filtro.
        """
        self.generation += 1
        self.mfe_samples.append(max_gain_pct)
        if len(self.mfe_samples) > 30:
            self.mfe_samples.pop(0)

        if symbol not in self.coin_pnl_memory:
            self.coin_pnl_memory[symbol] = []
        self.coin_pnl_memory[symbol].append(pnl)

        # Blacklist automática de 12 horas si una moneda genera 2 pérdidas seguidas
        if len(self.coin_pnl_memory[symbol]) >= 2 and all(x < 0 for x in self.coin_pnl_memory[symbol][-2:]):
            self.coin_blacklist_until[symbol] = time.time() + (12 * 3600)
            print(f"  🧠 [Cerebro Cuántico] VETO ESTRICTO para {symbol} por 12h tras 2 pérdidas consecutivas.", flush=True)

        change_summary = []
        if pnl > 0:
            self.weights["w_pullback"] = min(3.5, self.weights["w_pullback"] + self.learning_rate * 0.4)
            self.weights["w_volume"] = min(3.0, self.weights["w_volume"] + self.learning_rate * 0.5)
            # Recompensar éxito relajando suavemente hacia la base
            self.min_score_required = max(65.0, self.min_score_required - 1.0)
            change_summary.append("Trade Ganador: Filtro normalizado y pesos reforzados en Volumen")
        else:
            # Disciplina defensiva: aumentar exigencia de entrada ante pérdidas
            self.min_score_required = min(85.0, self.min_score_required + 2.5)
            self.weights["w_pullback"] = min(4.0, self.weights["w_pullback"] + self.learning_rate * 0.8)
            # Mantener Stop Loss en zona segura fuera del ruido (mínimo 2.50x ATR)
            self.sl_atr_mult = max(2.50, self.sl_atr_mult)
            change_summary.append(f"Trade Perdedor: Score mínimo elevado a {self.min_score_required:.1f} pts (Mayor Selectividad)")

        record = {
            "gen": self.generation,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "symbol": symbol,
            "pnl": round(pnl, 4),
            "max_gain": round(max_gain_pct, 2),
            "exit_reason": exit_reason,
            "adaptation": " | ".join(change_summary)
        }
        self.evolution_history.append(record)
        if len(self.evolution_history) > 10:
            self.evolution_history.pop(0)

        self.save_state()
        print(f"  🧠 [EVOLUCIÓN CEREBRO GEN #{self.generation}] {symbol} -> {record['adaptation']}", flush=True)

    def is_blacklisted(self, symbol: str) -> bool:
        if symbol in self.coin_blacklist_until:
            if time.time() < self.coin_blacklist_until[symbol]:
                return True
            else:
                del self.coin_blacklist_until[symbol]
        return False


brain = ReinforcementBrain()
auditor = TradeAuditor(LOG_DIR)
meta_gate = MetaLabelingGatekeeper(LOG_DIR)
macro_engine = MacroRegimeEngine(exchange)


def on_ai_auditor_parameter_tuning(adjustment: Dict, audit_record: Dict):
    """
    Función activa que permite al Auditor Forense (NVIDIA NIM) modificar
    parámetros operativos de ReinforcementBrain en tiempo real.
    """
    param = str(adjustment.get("parametro", "")).lower().strip()
    new_val = adjustment.get("nuevo_valor")
    reason = adjustment.get("justificacion", "Ajuste preventivo post-auditoría.")
    sym = audit_record.get("symbol", "")

    if not new_val:
        return

    old_val = None
    applied = False
    log_msg = ""

    if "sl" in param or "atr" in param:
        try:
            val_float = max(1.80, min(3.00, float(new_val)))
            old_val = brain.sl_atr_mult
            brain.sl_atr_mult = round(val_float, 2)
            applied = True
            log_msg = f"Stop Loss ATR ajustado de {old_val}x -> {brain.sl_atr_mult}x"
        except Exception:
            pass

    elif "score" in param:
        try:
            val_float = max(55.0, min(85.0, float(new_val)))
            old_val = brain.min_score_required
            brain.min_score_required = round(val_float, 1)
            applied = True
            log_msg = f"Score Mínimo Requerido ajustado de {old_val} -> {brain.min_score_required} pts"
        except Exception:
            pass

    elif "tp" in param:
        try:
            val_float = max(1.20, min(4.50, float(new_val)))
            old_val = brain.tp1_gain_pct
            brain.tp1_gain_pct = round(val_float, 2)
            applied = True
            log_msg = f"Objetivo TP1 ajustado de +{old_val}% -> +{brain.tp1_gain_pct}%"
        except Exception:
            pass

    elif "cooldown" in param and sym:
        brain.coin_blacklist_until[sym] = time.time() + (12 * 3600)
        applied = True
        log_msg = f"Veto temporal activado para {sym} por 12h"

    if applied:
        brain.save_state()
        print(f"\n  ⚙️ [AUDITOR ACTIVO NVIDIA] PARÁMETRO AJUSTADO EN TIEMPO REAL: {log_msg} | Razón: {reason}\n", flush=True)
        if "tuning_history" not in ai_auditor.system_memory:
            ai_auditor.system_memory["tuning_history"] = []
        ai_auditor.system_memory["tuning_history"].append({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "parameter": param,
            "old_value": old_val,
            "new_value": new_val,
            "symbol": sym,
            "reason": reason
        })
        ai_auditor.system_memory["tuning_history"] = ai_auditor.system_memory["tuning_history"][-20:]
        ai_auditor.save_memory()


ai_auditor.register_tuning_handler(on_ai_auditor_parameter_tuning)


# ====================== ANCLA ESTRUCTURAL: BOLLINGER BANDS & RSI (1h) ======================
_regime_1h_cache: Dict[str, Tuple[float, dict]] = {}

def get_symbol_1h_regime(symbol: str) -> dict:
    """
    Consulta Binance 1h klines (30 velas) para calcular Bollinger Bands y RSI 14 (1h).
    Cacheado por 60 segundos por símbolo para evitar rate limits.
    """
    now = time.time()
    if symbol in _regime_1h_cache:
        ts, cached = _regime_1h_cache[symbol]
        if now - ts < 60.0:
            return cached

    clean_sym = symbol.replace("/", "").replace("-", "").upper()
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={clean_sym}&interval=1h&limit=30"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())

        closes = [float(k[4]) for k in data]
        if len(closes) >= 20:
            sma20 = sum(closes[-20:]) / 20.0
            std20 = (sum((c - sma20)**2 for c in closes[-20:]) / 20.0) ** 0.5
            upper_bb = sma20 + 2.0 * std20
            lower_bb = sma20 - 2.0 * std20

            # RSI 14
            gains, losses = [], []
            for i in range(1, min(15, len(closes))):
                diff = closes[-15+i] - closes[-15+i-1]
                if diff >= 0:
                    gains.append(diff)
                    losses.append(0.0)
                else:
                    gains.append(0.0)
                    losses.append(abs(diff))
            avg_gain = sum(gains) / 14.0 if gains else 0.0001
            avg_loss = sum(losses) / 14.0 if losses else 0.0001
            rs = avg_gain / (avg_loss if avg_loss != 0 else 0.0001)
            rsi = 100.0 - (100.0 / (1.0 + rs))

            result = {
                "rsi_1h": round(rsi, 2),
                "lower_bb": round(lower_bb, 6),
                "sma20": round(sma20, 6),
                "upper_bb": round(upper_bb, 6),
                "last_close": closes[-1]
            }
            _regime_1h_cache[symbol] = (now, result)
            return result
    except Exception:
        pass

    default_res = {"rsi_1h": 50.0, "lower_bb": 0.0, "sma20": 0.0, "upper_bb": 999999.0, "last_close": 0.0}
    _regime_1h_cache[symbol] = (now, default_res)
    return default_res


# ====================== ESTRUCTURAS DE DATOS ======================

@dataclass
class GridLine:
    price: float
    side: str  # "buy" or "sell"
    amount: float
    active: bool = True
    buy_price: float = 0.0  # Costo real de compra inmutable para cálculo riguroso de PnL

@dataclass
class GridPosition:
    grid_id: str
    symbol: str
    grid_upper: float
    grid_lower: float
    grid_lines: int
    step_pct: float
    capital_total: float
    capital_per_line: float
    lines: list
    realized_pnl: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    active: bool = True
    status_msg: str = "Grid Activa"
    out_of_range_ticks: int = 0
    ticks_without_fill: int = 0
    last_fill_ts: float = field(default_factory=time.time)
    dynamic_adjustments_count: int = 0
    fills_count: int = 0
    buy_fills_count: int = 0
    sell_fills_count: int = 0
    freeze_buys: bool = False
    step_size: float = 0.0
    anomaly_start_ts: float = 0.0
    trailing_down_shifts: int = 0
    trailing_up_shifts: int = 0
    reval_diagnosis: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.step_size <= 0.0 and self.grid_lines > 1 and self.grid_upper > self.grid_lower:
            self.step_size = (self.grid_upper - self.grid_lower) / (self.grid_lines - 1)

    def to_dict(self):
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict):
        clean_d = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**clean_d)

@dataclass
class PendingLimitOrder:
    order_id: str
    symbol: str
    limit_price: float
    capital: float
    atr_val: float
    atr_pct: float
    analysis: Dict
    volume_24h: float
    side: str = "long"  # "long" o "short"
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    status: str = "PENDING"  # PENDING, FILLED, EXPIRED, CANCELED

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d: dict):
        return PendingLimitOrder(**d)


@dataclass
class LongPosition:
    position_id: str
    symbol: str
    initial_amount: float
    amount: float
    entry_price: float
    stop_loss: float
    initial_sl: float
    trailing_stop: float
    features_at_entry: Dict = field(default_factory=dict)
    tp1_hit: bool = False
    break_even_activated: bool = False
    trailing_activated: bool = False
    highest_price: float = 0.0
    lowest_price: float = 99999999.0
    capital_allocated: float = 0.0
    realized_pnl: float = 0.0
    atr_at_entry: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    active: bool = True
    strategy: str = "long"
    side: str = "long"  # "long" o "short"
    total_checks: int = 0
    max_gain_pct: float = 0.0
    status_msg: str = "BUSCANDO TP1 🎯"
    entry_time: float = 0.0

    def __post_init__(self):
        if self.side == "short" and self.strategy == "long":
            self.strategy = "short"
        if not self.entry_time:
            try:
                if self.created_at:
                    dt = datetime.fromisoformat(self.created_at)
                    self.entry_time = dt.timestamp()
                else:
                    self.entry_time = time.time()
            except Exception:
                self.entry_time = time.time()

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d: dict):
        clean_d = d.copy()
        if "side" not in clean_d:
            clean_d["side"] = "short" if "short" in clean_d.get("strategy", "").lower() else "long"
        if "lowest_price" not in clean_d:
            clean_d["lowest_price"] = clean_d.get("entry_price", 99999999.0)
        if "entry_time" not in clean_d or not clean_d["entry_time"]:
            try:
                c_at = clean_d.get("created_at", "")
                if c_at:
                    clean_d["entry_time"] = datetime.fromisoformat(c_at).timestamp()
                else:
                    clean_d["entry_time"] = time.time()
            except Exception:
                clean_d["entry_time"] = time.time()
        return LongPosition(**clean_d)


class PaperBot:
    def __init__(self):
        self.cash = INITIAL_CAPITAL
        self.holdings: Dict[str, float] = {}
        self.longs: Dict[str, LongPosition] = {}
        self.grids: Dict[str, GridPosition] = {}
        self.pending_orders: Dict[str, PendingLimitOrder] = {}
        self.is_alive = True
        self.death_reason: Optional[str] = None
        self.start_time = datetime.now()
        self.total_fees_paid = 0.0
        self.total_slippage_cost = 0.0
        self.total_realized_pnl_acc = 0.0

        self.wins = 0
        self.losses = 0
        self.total_trades = 0
        self.trades_since_eval = 0
        self.latest_self_eval: Dict = {}
        self.latest_pnl_audit: List[Dict] = []
        self.peak_equity = INITIAL_CAPITAL
        self.max_drawdown = 0.0
        self.drawdown_ticks = 0
        self.btc_risk_off = False
        self.btc_change_6h = 0.0


        os.makedirs(LOG_DIR, exist_ok=True)
        self._init_logs()
        self.load_portfolio_state()

    def _init_logs(self):
        vault.migrate_from_csv(TRADES_LOG, EQUITY_LOG)
        with CSV_LOGS_LOCK:
            if not os.path.exists(EQUITY_LOG):
                with open(EQUITY_LOG, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        "timestamp", "equity", "cash", "holdings_value",
                        "open_longs", "realized_pnl_total", "fees_paid",
                        "slippage_cost", "max_drawdown"
                    ])
            if not os.path.exists(TRADES_LOG):
                with open(TRADES_LOG, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        "timestamp", "symbol", "strategy", "side", "price", "amount",
                        "pnl", "fee", "slippage", "extra_info", "position_id", "status"
                    ])

    def save_portfolio_state(self):
        try:
            data = {
                "cash": round(self.cash, 4),
                "holdings": {k: round(v, 8) for k, v in self.holdings.items() if v > 1e-8},
                "longs": {k: v.to_dict() for k, v in self.longs.items() if v.active},
                "grids": {k: v.to_dict() for k, v in self.grids.items() if v.active},
                "total_fees_paid": round(self.total_fees_paid, 4),
                "total_slippage_cost": round(self.total_slippage_cost, 4),
                "total_realized_pnl_acc": round(self.total_realized_pnl_acc, 4),
                "wins": self.wins,
                "losses": self.losses,
                "total_trades": self.total_trades,
                "updated_at": datetime.now().isoformat()
            }
            _atomic_json_dump(PORTFOLIO_STATE_FILE, data, indent=2)
        except Exception as e:
            print(f"  [Error Guardar Estado Portafolio] {e}", flush=True)

    def load_portfolio_state(self):
        if os.path.exists(PORTFOLIO_STATE_FILE):
            try:
                with open(PORTFOLIO_STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if not isinstance(data, dict):
                        raise ValueError("El estado del portafolio debe ser un objeto JSON")
                    loaded_cash = float(data.get("cash", INITIAL_CAPITAL))
                    loaded_holdings = data.get("holdings", {})
                    if not isinstance(loaded_holdings, dict):
                        raise ValueError("Las tenencias del portafolio no son válidas")
                    longs_data = data.get("longs", {})
                    grids_data = data.get("grids", {})
                    if not isinstance(longs_data, dict) or not isinstance(grids_data, dict):
                        raise ValueError("Las posiciones del portafolio no son válidas")
                    loaded_longs = {
                        sym: LongPosition.from_dict(pos_dict)
                        for sym, pos_dict in longs_data.items()
                    }
                    loaded_grids = {
                        sym: GridPosition.from_dict(grid_dict)
                        for sym, grid_dict in grids_data.items()
                    }
                    loaded_fees = float(data.get("total_fees_paid", 0.0))
                    loaded_slippage = float(data.get("total_slippage_cost", 0.0))
                    loaded_realized_pnl = float(data.get("total_realized_pnl_acc", 0.0))
                    loaded_wins = int(data.get("wins", 0))
                    loaded_losses = int(data.get("losses", 0))
                    loaded_trades = int(data.get("total_trades", 0))

                    self.cash = loaded_cash
                    self.holdings = loaded_holdings
                    self.longs = loaded_longs
                    self.grids = loaded_grids
                    self.total_fees_paid = loaded_fees
                    self.total_slippage_cost = loaded_slippage
                    self.total_realized_pnl_acc = loaded_realized_pnl
                    self.wins = loaded_wins
                    self.losses = loaded_losses
                    self.total_trades = loaded_trades
                print(f"  📂 [PORTAFOLIO CARGADO] Efectivo: ${self.cash:.2f} USDT | Mallas Activas: {len(self.grids)} | Posiciones: {len(self.longs)}", flush=True)
            except Exception as e:
                bak_file = f"{PORTFOLIO_STATE_FILE}.corrupt.{time.time_ns()}.bak"
                try:
                    shutil.copy2(PORTFOLIO_STATE_FILE, bak_file)
                    print(f"  🚨 [ALERTA ESTADO CORRUPTO] Archivo de portafolio dañado respaldado en {bak_file}. Error: {e}", flush=True)
                except Exception as bak_err:
                    print(f"  🚨 [ALERTA ESTADO CORRUPTO] Error respaldando portafolio dañado: {bak_err}", flush=True)

    def get_holdings_value(self, prices: Dict[str, float]) -> float:
        val = 0.0
        # Posiciones Spot / Long tradicionales
        for symbol, amount in self.holdings.items():
            p = prices.get(symbol)
            if p is None or p <= 0:
                if symbol in self.longs and self.longs[symbol].entry_price > 0:
                    p = self.longs[symbol].entry_price
                else:
                    p = 0.0
            val += amount * p
        return val

    def get_equity(self, prices: Dict[str, float]) -> float:
        # Equity = Efectivo libre + valor de longs + PnL flotante de shorts + Valor de las Mallas
        equity = self.cash + self.get_holdings_value(prices)
        for sym, pos in self.longs.items():
            if pos.active and getattr(pos, "side", "long") == "short":
                curr_p = prices.get(sym, pos.entry_price)
                if curr_p and curr_p > 0:
                    short_flot_pnl = (pos.entry_price - curr_p) * pos.amount
                    equity += (pos.capital_allocated + short_flot_pnl)
                    
        # Calcular valor bloqueado y flotante en mallas activas
        for sym, grid in self.grids.items():
            if not grid.active:
                continue
            curr_p = prices.get(sym) or ((grid.grid_upper + grid.grid_lower) / 2.0)
            for line in grid.lines:
                if not line["active"]:
                    continue
                if line["side"] == "buy":
                    # Dinero retenido en orden de compra
                    equity += (line["price"] * line["amount"])
                elif line["side"] == "sell":
                    # Valor actual de la moneda que estamos holdeando para vender
                    equity += (line["amount"] * curr_p)
                    
        return equity

    def total_realized_pnl(self) -> float:
        pos_pnl = sum(l.realized_pnl for l in self.longs.values())
        return self.total_realized_pnl_acc + pos_pnl

    def active_risk_positions_count(self) -> int:
        """Cuenta posiciones que aún no han cobrado TP1 + órdenes límite pendientes."""
        risk_active = len([l for l in self.longs.values() if l.active and not l.tp1_hit])
        pending = len(self.pending_orders)
        return risk_active + pending

    def open_positions_count(self) -> int:
        return len([l for l in self.longs.values() if l.active]) + len(self.pending_orders)

    def run_self_evaluation(self):
        """Auto-evaluación algorítmica periódica (cada 5-10 trades) con ajuste adaptativo."""
        try:
            report = auditor.evaluate_last_n_trades(10)
            recs = auditor.generate_adaptations()
            audit_list = auditor.get_pnl_audit()
            self.latest_self_eval = {
                "report": report,
                "recommendations": recs,
                "evaluated_at": datetime.now().isoformat()
            }
            self.latest_pnl_audit = audit_list[:30]

            # Aplicar adaptaciones automáticas
            if "coin_blacklist" in recs:
                for item in recs["coin_blacklist"]:
                    coin = item.split(" ")[0]
                    brain.coin_blacklist_until[coin] = time.time() + (12 * 3600)
                    print(f"  🧠 [AUTO-ADAPTACIÓN] {coin} bloqueado por 12h tras racha negativa.", flush=True)

            if "low_winrate" in recs:
                brain.min_score_required = min(85.0, max(65.0, brain.min_score_required + 2.0))
                print(f"  🧠 [AUTO-ADAPTACIÓN] Win rate bajo -> Score mínimo endurecido a {brain.min_score_required:.1f} pts (Filtro Estricto)", flush=True)

            if "tp1_too_ambitious" in recs:
                brain.tp1_gain_pct = max(1.80, brain.tp1_gain_pct - 0.08)
                print(f"  🧠 [AUTO-ADAPTACIÓN] TP1 re-calibrado a +{brain.tp1_gain_pct:.2f}%", flush=True)

            wr = report.get('overall', {}).get('win_rate', 0) * 100
            exp = report.get('overall', {}).get('expectancy', 0)
            fric = report.get('friction', {}).get('total_friction_cost', 0)
            print(f"  🧠 [AUTO-EVALUACIÓN REALIZADA] WinRate Últimos 10: {wr:.1f}% | Esperanza: ${exp:+.4f} | Fricción: ${fric:.2f}", flush=True)

            # Re-entrenamiento automático continuo del Centinela de Riesgo
            meta_gate.train_model()
        except Exception as e:
            print(f"  [Error Auto-Evaluación] {e}", flush=True)

    def check_survival(self, equity: float) -> bool:
        if not self.is_alive:
            return False
        if equity < INITIAL_CAPITAL * MIN_EQUITY_RATIO:
            self.drawdown_ticks += 1
            if self.drawdown_ticks >= 4:
                self.is_alive = False
                self.death_reason = f"Equity cayó a {equity:.2f} USDT ({equity / INITIAL_CAPITAL * 100:.1f}%) confirmado por 4 ticks"
                return False
        else:
            self.drawdown_ticks = 0
        return True


    def log_equity(self, equity: float, prices: Dict[str, float]):
        now_iso = datetime.now().isoformat()
        holdings_val = self.get_holdings_value(prices)
        open_pos_count = len([l for l in self.longs.values() if l.active])
        rpnl_total = self.total_realized_pnl()
        vault.insert_equity(
            now_iso, equity, self.cash, holdings_val, open_pos_count,
            rpnl_total, self.total_fees_paid, self.total_slippage_cost,
            self.max_drawdown * 100
        )
        with CSV_LOGS_LOCK:
            with open(EQUITY_LOG, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    now_iso,
                    round(equity, 4),
                    round(self.cash, 4),
                    round(holdings_val, 4),
                    open_pos_count,
                    round(rpnl_total, 4),
                    round(self.total_fees_paid, 4),
                    round(self.total_slippage_cost, 4),
                    round(self.max_drawdown * 100, 2)
                ])

    def log_trade(self, symbol: str, strategy: str, side: str, price: float,
                  amount: float, pnl: float, fee: float, slippage: float,
                  extra: str = "", pos_id: str = "", status: str = "OPEN"):
        now_iso = datetime.now().isoformat()
        vault.insert_trade(
            now_iso, symbol, strategy, side, price, amount, pnl, fee, slippage, extra, pos_id, status
        )
        with CSV_LOGS_LOCK:
            with open(TRADES_LOG, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    now_iso, symbol, strategy, side,
                    round(price, 6), round(amount, 6), round(pnl, 4),
                    round(fee, 4), round(slippage, 4), extra, pos_id, status
                ])

        if status in ("CLOSED", "PARTIAL_CLOSED") and pnl != 0:
            self.total_trades += 1
            if pnl > 0:
                self.wins += 1
            else:
                self.losses += 1
            self.total_realized_pnl_acc += pnl
            self.trades_since_eval += 1
            if self.trades_since_eval >= 5:
                self.trades_since_eval = 0
                self.run_self_evaluation()

        self.save_portfolio_state()

    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (self.wins / self.total_trades) * 100

    def update_drawdown(self, equity: float):
        if equity > self.peak_equity:
            self.peak_equity = equity
        if self.peak_equity > 0:
            dd = (self.peak_equity - equity) / self.peak_equity
            if dd > self.max_drawdown:
                self.max_drawdown = dd

    def close_grid_market(self, symbol: str, current_price: float, reason: str = "Cierre Manual a Mercado") -> Optional[Dict]:
        """
        Cierra forzosamente una malla activa:
        - Cancela todas las órdenes de compra pendientes, recuperando el USDT no ejecutado.
        - Vende a mercado todos los tokens retenidos aplicando slippage real de mercado (0.08%) y comisión taker.
        - Registra la operación, actualiza el PnL y guarda el portafolio.
        """
        grid = self.grids.get(symbol)
        if not grid or not grid.active:
            for g in self.grids.values():
                if g.active and (g.symbol == symbol or g.grid_id == symbol):
                    grid = g
                    break
        if not grid or not grid.active:
            return None

        recovered_buy_cash = 0.0
        sold_tokens = 0.0
        total_buy_cost = 0.0

        for l in grid.lines:
            if not l.get("active"):
                continue
            if l.get("side") == "buy":
                recovered_buy_cash += (float(l["price"]) * float(l["amount"]))
            elif l.get("side") == "sell":
                amt = float(l["amount"])
                sold_tokens += amt
                total_buy_cost += (amt * float(l.get("buy_price", l["price"] / (1 + grid.step_pct))))
            l["active"] = False

        # Simulación de Ejecución Real a Mercado: Slippage taker (0.08%) y comisión
        effective_market_price = current_price * (1.0 - 0.0008) if sold_tokens > 0 else current_price
        gross_sell = sold_tokens * effective_market_price
        taker_fee = gross_sell * (FEE_RATE * 1.5)
        sell_proceeds = (gross_sell - taker_fee) if sold_tokens > 0 else 0.0
        liquidation_pnl = (sell_proceeds - total_buy_cost) if sold_tokens > 0 else 0.0
        total_recovered = recovered_buy_cash + sell_proceeds

        grid.realized_pnl += liquidation_pnl
        self.total_realized_pnl_acc += liquidation_pnl
        self.cash += total_recovered

        if liquidation_pnl >= 0:
            self.wins += 1
        else:
            self.losses += 1
        self.total_trades += 1

        self.log_trade(
            symbol=grid.symbol,
            strategy="grid_circuit_breaker" if "CATASTRÓFICO" in reason or "TIME-STOP" in reason else "grid_manual_market_exit",
            side="sell",
            price=round(effective_market_price, 6),
            amount=sold_tokens,
            pnl=round(liquidation_pnl, 4),
            fee=round(taker_fee, 4),
            slippage=round(sold_tokens * (current_price - effective_market_price), 4),
            extra=f"{reason}: Canceladas compras (${recovered_buy_cash:.2f}) + Vendidos {sold_tokens:.4f} {grid.symbol} @ ${effective_market_price:.6f} (-0.08% slip). Liberados ${total_recovered:.2f} a caja líquida",
            pos_id=grid.grid_id,
            status="CLOSED"
        )

        grid.active = False
        grid.status_msg = f"{reason} ({liquidation_pnl:+.4f} USDT | +${total_recovered:.2f} a caja)"

        # Cooldown de protección: pausar el activo durante 45 minutos si fue liquidado por Circuit Breaker
        if "CATASTRÓFICO" in reason.upper() or "TIME-STOP" in reason.upper():
            try:
                brain.coin_blacklist_until[grid.symbol] = time.time() + (45 * 60)
                brain.save_state()
                print(f"  ⏳ [COOLDOWN POST-LIQUIDACIÓN] {grid.symbol} en pausa por 45 minutos tras cierre por Circuit Breaker ({reason}).", flush=True)
            except Exception as e:
                pass

        self.save_portfolio_state()
        print(f"\n  🛑⚡ [{reason.upper()}: {grid.symbol}] Malla liquidada. Tokens vendidos: {sold_tokens:.4f} @ ${effective_market_price:.6f} (slip: -0.08%) | PnL: {liquidation_pnl:+.4f} USDT | Liberados ${total_recovered:.2f} a caja libre.\n", flush=True)

        return {
            "symbol": symbol,
            "sold_tokens": sold_tokens,
            "sell_proceeds": sell_proceeds,
            "recovered_buy_cash": recovered_buy_cash,
            "total_recovered": total_recovered,
            "pnl": liquidation_pnl
        }

    def reset_and_close_all(self, target_cash: float = INITIAL_CAPITAL):
        print(f"\n⚡ [REINICIO TOTAL SOLICITADO] Limpiando portafolio e iniciando en ${target_cash:.2f} USDT...", flush=True)
        self.cash = target_cash
        self.holdings.clear()
        self.longs.clear()
        self.grids.clear()
        self.pending_orders.clear()
        self.peak_equity = target_cash
        self.wins = 0
        self.losses = 0
        self.total_trades = 0
        self.total_realized_pnl_acc = 0.0
        self.total_fees_paid = 0.0
        self.total_slippage_cost = 0.0
        self.max_drawdown = 0.0
        self.latest_pnl_audit = []
        self.save_portfolio_state()
        vault.reset_vault(target_cash)
        try:
            with CSV_LOGS_LOCK:
                with open(EQUITY_LOG, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["timestamp", "equity", "cash", "holdings_value", "open_longs", "realized_pnl_total", "fees_paid", "slippage_cost", "max_drawdown"])
                    writer.writerow([datetime.now().isoformat(), round(target_cash, 2), round(target_cash, 2), 0.0, 0, 0.0, 0.0, 0.0, 0.0])
                with open(TRADES_LOG, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["timestamp", "symbol", "strategy", "side", "price", "amount", "pnl", "fee", "slippage", "extra_info", "position_id", "status"])
        except Exception as e:
            print(f"Error reiniciando logs: {e}", flush=True)
        print(f"⚡ [REINICIO COMPLETADO] Efectivo Disponible: ${self.cash:.2f} USDT | Mallas: 0 | Posiciones: 0\n", flush=True)


# ====================== ANÁLISIS CUANTITATIVO AGRESIVO ======================
def _compute_rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else 50.0


def _compute_adx_full(df: pd.DataFrame, period: int = 14):
    high = df["high"]
    low = df["low"]
    close = df["close"]

    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean() / atr
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)) * 100
    adx = dx.ewm(alpha=1/period, adjust=False).mean()

    return adx, plus_di, minus_di, atr


def compute_pid_and_squeeze(df_15m: pd.DataFrame) -> Dict:
    """
    Control PID & Indicador Predictivo de Despegue (Launchpad Anticipator).
    - SP = EMA20 de 15m (equilibrio dinámico).
    - Error e(t) = ((Close - EMA20) / EMA20) * 100.
    - P (Proporcional): Distancia porcentual actual al equilibrio.
    - I (Integral): Media de error en las últimas 5 velas (acumulación en soporte).
    - D (Derivada / Velocidad): v(t) = Close[t] - Close[t-1].
    - Acc (Aceleración de 2do orden): a(t) = v[t] - v[t-1] = Close[t] - 2*Close[t-1] + Close[t-2].
      La física cuantitativa dicta que la aceleración debe ser positiva (a > 0) antes de la vela de despegue.
    - Squeeze de Volatilidad (Bollinger Bands 20, 2.0 vs Keltner Channel 20, 1.5 ATR):
      Ratio de compresión = (BB_Width / KC_Width). Si <= 1.0, el resorte está comprimido (coiling).
    """
    close = df_15m["close"]
    high = df_15m["high"]
    low = df_15m["low"]
    n = len(close)
    if n < 20:
        return {
            "P": 0.0, "I": 0.0, "D": 0.0, "Acc": 0.0,
            "sq_ratio": 1.0, "squeeze_on": False,
            "is_launchpad": False, "stage": "INSUFFICIENT_DATA", "anticipatory_boost": 0.0
        }

    ema20 = close.ewm(span=20).mean()
    err = ((close - ema20) / ema20) * 100
    p_val = float(err.iloc[-1])
    i_val = float(err.iloc[-5:].mean()) if n >= 5 else p_val
    v = close.diff()
    a = v.diff()
    d_val = float(v.iloc[-1])
    acc_val = float(a.iloc[-1])

    # Squeeze John Carter TTM
    std20 = close.rolling(20).std()
    bb_width = 4.0 * std20
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()
    kc_width = 3.0 * atr14

    last_bb_w = float(bb_width.iloc[-1]) if not np.isnan(bb_width.iloc[-1]) else 1.0
    last_kc_w = float(kc_width.iloc[-1]) if not np.isnan(kc_width.iloc[-1]) and float(kc_width.iloc[-1]) > 0 else 1.0
    sq_ratio = last_bb_w / last_kc_w if last_kc_w > 0 else 1.0
    squeeze_on = (sq_ratio <= 1.0)

    # Evaluación Predictiva:
    # 1. Compresión de resorte: sq_ratio <= 1.08
    # 2. Aceleración positiva (inflexión alcista iniciada): acc_val > 0
    # 3. En piso de lanzamiento: -1.5 <= p_val <= 0.15
    is_launchpad = (sq_ratio <= 1.08) and (acc_val > 0) and (-1.5 <= p_val <= 0.15)

    if is_launchpad:
        stage = "🚀 LAUNCHPAD (PRE-DESPEGUE)"
        boost = 30.0
    elif squeeze_on:
        stage = "🟡 COILING COMPRESIÓN"
        boost = 15.0
    elif p_val > 0.25:
        stage = "🔴 CRESTA EXTENDIDA"
        boost = -50.0
    else:
        stage = "⚪ TRANSICIÓN NEUTRA"
        boost = 0.0

    return {
        "P": round(p_val, 2),
        "I": round(i_val, 2),
        "D": round(d_val, 6),
        "Acc": round(acc_val, 6),
        "sq_ratio": round(sq_ratio, 2),
        "squeeze_on": bool(squeeze_on),
        "is_launchpad": bool(is_launchpad),
        "stage": stage,
        "anticipatory_boost": boost
    }


# ponytail: dead code — retained for reference
def get_sniper_analysis_aggressive(symbol: str, df_15m: pd.DataFrame, df_1h: pd.DataFrame, volume_m: float, btc_mom: float = 0.0) -> Dict:
    if len(df_1h) < 30 or len(df_15m) < 20:
        return {"recommendation": "skip", "score": 0.0}

    close_1h = df_1h["close"]
    ema20_1h = close_1h.ewm(span=20).mean().iloc[-1]
    ema50_1h = close_1h.ewm(span=50).mean().iloc[-1]
    adx_1h_s, plus_1h, minus_1h, atr_1h_s = _compute_adx_full(df_1h, 14)
    adx_1h = float(adx_1h_s.iloc[-1])
    di_spread_1h = float(plus_1h.iloc[-1]) - float(minus_1h.iloc[-1])
    atr_pct_1h = (float(atr_1h_s.iloc[-1]) / close_1h.iloc[-1]) * 100
    atr_val_1h = float(atr_1h_s.iloc[-1])

    macro_bullish = ((ema20_1h >= ema50_1h * 0.998) and (di_spread_1h >= 1.0)) or (adx_1h >= 24.0 and di_spread_1h > 0)

    close_15m = df_15m["close"]
    open_15m = df_15m["open"]
    high_15m = df_15m["high"]
    low_15m = df_15m["low"]
    ema20_15m = close_15m.ewm(span=20).mean().iloc[-1]
    rsi_15m = _compute_rsi(close_15m, 14)
    dist_to_ema20_15m = ((close_15m.iloc[-1] / ema20_15m) - 1) * 100

    last_candle_bullish = (close_15m.iloc[-1] >= open_15m.iloc[-1] * 0.998) or (
        (close_15m.iloc[-1] - low_15m.iloc[-1]) > (high_15m.iloc[-1] - close_15m.iloc[-1])
    )

    # CÁLCULO PREDICTIVO PID & SQUEEZE:
    pid_sq = compute_pid_and_squeeze(df_15m)

    # VETO ESTRICTO ANTI-CRESTA (Anti-FOMO / Cero compras en techos de ola):
    is_extended_crest = (dist_to_ema20_15m > 0.20) or (rsi_15m > 56.5) or (pid_sq["stage"].startswith("🔴"))

    # PISO DE LANZAMIENTO / SOPORTE EXACTO:
    is_at_support_valley = (-1.8 <= dist_to_ema20_15m <= 0.15) and (33.0 <= rsi_15m <= 56.0)

    # CÁLCULO DE EFICIENCIA DIRECCIONAL DE KAUFMAN (KER) & BIAS DE MONEDA:
    ker_val = compute_kaufman_efficiency_ratio(close_15m, 14)
    pnl_hist = brain.coin_pnl_memory.get(symbol, [])
    coin_bias_val = round(sum(pnl_hist[-3:]), 3) if pnl_hist else 0.0

    features_dict = {
        "adx": round(adx_1h, 1),
        "dist_ema20": round(dist_to_ema20_15m, 2),
        "rsi": round(rsi_15m, 1),
        "atr_pct": round(atr_pct_1h, 2),
        "volume_m": round(volume_m, 1),
        "volume_24h": max(0.0, float(volume_m)) * 1_000_000,
        "pid_p": pid_sq["P"],
        "pid_d": pid_sq["D"],
        "pid_acc": pid_sq["Acc"],
        "sq_ratio": pid_sq["sq_ratio"],
        "stage": pid_sq["stage"],
        "is_launchpad": pid_sq["is_launchpad"],
        "ker": ker_val,
        "btc_mom": btc_mom,
        "coin_bias": coin_bias_val
    }

    # SEÑAL TÉCNICA PRIMARIA (Modelo Nivel 1 - PID / Squeeze / Soporte):
    is_primary_long = (
        macro_bullish
        and is_at_support_valley
        and not is_extended_crest
        and (pid_sq["is_launchpad"] or last_candle_bullish)
        and (atr_pct_1h >= 1.5)
        and (not brain.is_blacklisted(symbol))
    )

    # GATEKEEPER SECUNDARIO (Meta-Labeling de Marcos López de Prado - Nivel 2):
    meta_veto = False
    p_win = 0.50
    bet_multiplier = 1.0
    meta_reason = "No evaluado (sin señal primaria)"

    if is_primary_long:
        meta_veto, p_win, bet_multiplier, meta_reason = meta_gate.predict_probability(symbol, features_dict)
        if meta_veto:
            rec = "skip"
            print(f"  🛡️ [META-LABELING VETO] {symbol}: {meta_reason}", flush=True)
        else:
            rec = "long"
            print(f"  ✅ [META-LABELING APROBADO] {symbol} (P={p_win:.1%}, Bet={bet_multiplier:.2f}x, KER={ker_val:.2f})", flush=True)
    else:
        rec = "skip"

    rl_score = 0.0
    return {
        "score": rl_score,
        "recommendation": rec,
        "adx_1h": round(adx_1h, 1),
        "rsi_15m": round(rsi_15m, 1),
        "dist_ema20_15m": round(dist_to_ema20_15m, 2),
        "atr_pct": round(atr_pct_1h, 2),
        "atr_value": atr_val_1h,
        "pid_p": pid_sq["P"],
        "pid_d": pid_sq["D"],
        "pid_acc": pid_sq["Acc"],
        "sq_ratio": pid_sq["sq_ratio"],
        "stage": pid_sq["stage"],
        "is_launchpad": pid_sq["is_launchpad"],
        "ker": ker_val,
        "p_win": p_win,
        "bet_multiplier": bet_multiplier,
        "meta_reason": meta_reason,
        "features": features_dict
    }



# ====================== ESCÁNER DE MERCADO MULTI-FACTOR (MACRO + MICRO) ======================
def select_best_opportunities(bot: PaperBot, top_n: int = 6) -> List[Dict]:
    try:
        tickers = exchange.fetch_tickers()
        candidates = []
        for sym, t in tickers.items():
            if not sym.endswith("/USDT"):
                continue
            base = sym.split("/")[0]
            if base in STABLE_BASES:
                continue
            vol = t.get("quoteVolume", 0) or 0
            pct = t.get("percentage", 0) or 0
            last_p = t.get("last", 0) or 0
            # Filtro de Liquidez Institucional: Mínimo $15M en 24h para garantizar ejecución fluida
            if vol >= 15_000_000 and last_p > 0:
                candidates.append((sym, vol, pct, last_p))

        # Canasta Cuantitativa Especializada para Mallas (Grid Mean-Reversion):
        # Seleccionamos activos en rango saludable (-4.5% a +6.0%), evitando cimas de pumps parabólicos
        grid_pool = [c for c in candidates if -4.5 <= c[2] <= 6.0]
        by_vol = sorted(grid_pool, key=lambda x: x[1], reverse=True)[:15]
        by_accumulation = sorted([c for c in grid_pool if -4.0 <= c[2] <= 1.0], key=lambda x: x[1], reverse=True)[:10]

        seen = set()
        top_candidates = []
        for item in by_vol + by_accumulation:
            if item[0] not in seen:
                seen.add(item[0])
                top_candidates.append(item)
    except Exception as e:
        print(f"  [Scan Error] {e}", flush=True)
        return []

    btc_macro = macro_engine.btc_macro_state
    bot.btc_risk_off = btc_macro.get("is_risk_off", False)

    results = []
    for symbol, volume, pct_chg, last_price in top_candidates:
        if symbol in bot.longs or symbol in bot.pending_orders:
            continue

        try:
            macro_info = macro_engine.analyze_coin_macro(symbol)
            ohlcv_15m = exchange.fetch_ohlcv(symbol, "15m", limit=30)
            ohlcv_1h = exchange.fetch_ohlcv(symbol, "1h", limit=30)
            if not ohlcv_15m or not ohlcv_1h:
                continue

            df_15m = pd.DataFrame(ohlcv_15m, columns=["ts", "open", "high", "low", "close", "volume"])
            df_1h = pd.DataFrame(ohlcv_1h, columns=["ts", "open", "high", "low", "close", "volume"])
            vol_m = volume / 1_000_000

            # Evaluación con Arsenal Multi-Factor Completo (6 Pilares)
            analysis = evaluate_multi_factor_arsenal(
                symbol, df_15m, df_1h, macro_info, btc_macro, vol_m
            )

            # Filtro Antiestancamiento de Volatilidad Viva:
            # Exigir ATR mínimo >= 1.20% para asegurar que el activo tiene movimiento y cosecha rápida
            coin_atr_pct = analysis.get("features", {}).get("atr_pct", analysis.get("atr_pct", 0.0))
            if coin_atr_pct < 1.20:
                continue

            # Evaluación de Microestructura LOB (Order Book Depth 10)
            lob = fetch_order_book_microstructure(exchange, symbol, depth=10)
            analysis["lob"] = lob
            if "features" not in analysis:
                analysis["features"] = {}
            analysis["features"]["obi"] = lob["obi"]
            analysis["features"]["spread_pct"] = lob["spread_pct"]
            is_rec_short = (analysis.get("recommendation") == "short")
            analysis["features"]["is_short"] = is_rec_short
            analysis["features"]["direction"] = "short" if is_rec_short else "long"

            # Gatekeeper Cuantitativo: Evaluar probabilidad para todos los candidatos
            meta_veto, p_win, bet_mult, meta_reason = meta_gate.predict_probability(symbol, analysis.get("features", {}))
            analysis["p_win"] = p_win
            analysis["bet_multiplier"] = bet_mult

            # Estimación del Proceso de Ornstein-Uhlenbeck (Reversión a la Media)
            ou_metrics = estimate_ornstein_uhlenbeck(df_15m["close"].values, dt_minutes=15.0)
            analysis["ou"] = ou_metrics

            # Telemetría de Radar Cuantitativo (Datos objetivos para el Comité Multi-Agente)
            stage_txt = analysis.get("squeeze_state", "COILING")
            ker_val = analysis.get("ker", 0.35)
            ou_lbl = f"OU={ou_metrics['status_label']} (τ={ou_metrics['half_life_min']:.0f}m)" if ou_metrics.get("is_mean_reverting") else f"OU={ou_metrics['status_label']}"
            print(f"  📊 [RADAR CANDIDATO] {symbol} | Score: {analysis['score']:.1f} | OBI={lob['obi']:+.2f} | KER={ker_val:.2f} | {ou_lbl} | Sq={stage_txt}", flush=True)

            # Mantener en la lista de resultados para que el usuario y la oficina vean TODAS las monedas auditadas
            results.append({
                "symbol": symbol,
                "score": analysis["score"],
                "analysis": analysis,
                "volume": volume,
                "price": last_price,
                "stage": analysis.get("squeeze_state", "COILING"),
                "macro_bias": macro_info.get("macro_bias", "NEUTRAL"),
                "limit_buy_price": analysis.get("limit_buy_price", last_price),
                "obv_slope": analysis.get("obv_slope", 0.0),
                "vol_surge": analysis.get("vol_surge", 1.0),
                "ker": analysis.get("ker", 0.35),
                "obi": lob.get("obi", 0.0),
                "spread_pct": lob.get("spread_pct", 0.0),
                "p_win": p_win,
                "bet_multiplier": bet_mult,
                "ou": ou_metrics
            })
        except Exception:
            continue

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]


# ====================== EJECUCIÓN REALISTA ======================
def apply_slippage(price: float, side: str, atr_pct: float, volume_24h: float, is_limit: bool = False) -> Tuple[float, float]:
    """
    Slippage realista:
    - Órdenes LIMIT (Maker): Slippage = 0 SIEMPRE (se ejecutan al precio fijado).
    - Órdenes MARKET (Taker): Slippage micro (0.01% a 0.03% max) proporcional a liquidez.
    """
    if is_limit:
        return price, 0.0
    # Market order: slippage mínimo realista
    max_slip_pct = 0.0003  # 0.03% máximo
    if volume_24h < 15_000_000:
        max_slip_pct = 0.0005  # 0.05% para baja liquidez
    slip_pct = random.uniform(0, max_slip_pct)
    executed = price * (1 + slip_pct) if side == "buy" else price * (1 - slip_pct)
    return executed, slip_pct


# ====================== FLUJO CONCENTRADO E INTERÉS COMPUESTO ======================
def calculate_compound_order_size(bot: PaperBot, equity: float) -> float:
    """
    Calcula el tamaño de la orden con RECICLAJE DINÁMICO DE SLOTS:
    - Si ya hay 2 posiciones en fase de riesgo inicial (sin TP1 cobrado), retorna 0.
    - Si una posición cobra TP1 y su SL está blindado en Break-Even, LIBERA SU SLOT.
    - Asigna hasta el 48% del Equity (~$38.80) o el 96% de la caja libre disponible.
    - Mínimo $25.00 USDT por trade (cero órdenes residuales enanas).
    """
    if bot.active_risk_positions_count() >= MAX_RISK_SLOTS or bot.open_positions_count() >= MAX_TOTAL_POSITIONS:
        return 0.0

    target_capital = equity * COMPOUND_ALLOCATION_PCT
    max_affordable_capital = bot.cash * 0.96
    capital = min(target_capital, max_affordable_capital)

    if capital < MIN_ORDER_USDT:
        return 0.0

    return round(capital, 2)



# ====================== MOTOR DE ÓRDENES LÍMITE PREDICTIVAS (CERO SLIPPAGE / MAKER) ======================
# ====================== MOTOR DE ÓRDENES LÍMITE PREDICTIVAS (CERO SLIPPAGE / MAKER) ======================
def place_limit_buy(bot: PaperBot, symbol: str, capital: float, current_price: float,
                    analysis: Dict, volume_24h: float, side: str = "long", is_retest: bool = False) -> bool:
    """
    Coloca una orden LÍMITE predictiva en el soporte (para Long) o resistencia (para Short).
    En lugar de pagar slippage y fees taker persiguiendo velas,
    el bot fija su orden límite pasiva (Maker) esperando la absorción institucional.
    Si is_retest=True, exige un retroceso más profundo para confirmar el retesteo.
    """
    bet_mult = float(analysis.get("bet_multiplier", 1.0))
    capital = max(MIN_ORDER_USDT, round(capital * bet_mult, 2))

    if capital < MIN_ORDER_USDT:
        return False

    if symbol in bot.longs or symbol in bot.pending_orders:
        return False

    reserved_cash = sum(o.capital for o in bot.pending_orders.values())
    fee_estimate = capital * FEE_RATE
    if (bot.cash - reserved_cash) < (capital + fee_estimate):
        return False

    # Cálculo predictivo del precio límite Tight Maker (Mejor Bid / Profundidad Nivel 1)
    offset_base = 0.0030 if is_retest else 0.0010
    limit_price = float(analysis.get("limit_order_price", analysis.get("limit_buy_price", 0.0)))
    if side == "short":
        if limit_price <= 0.0 or limit_price <= current_price:
            limit_price = current_price * (1 + offset_base)
        else:
            limit_price = min(limit_price, current_price * (1.0050 if is_retest else 1.0020))
        pull_offset_pct = (limit_price - current_price) / current_price
    else:
        if limit_price <= 0.0 or limit_price >= current_price:
            limit_price = current_price * (1 - offset_base)
        else:
            limit_price = max(limit_price, current_price * (0.9950 if is_retest else 0.9980))
        pull_offset_pct = (current_price - limit_price) / current_price

    atr_val = float(analysis.get("atr_value", current_price * 0.02))
    atr_pct = float(analysis.get("atr_pct", 2.0))

    order_id = f"lim_{int(time.time()*1000)}"
    forward_target = float(analysis.get("forward_target", 0.0))
    rr_ratio = float(analysis.get("rr_ratio", 0.0))
    validity_secs = 600 if is_retest else 360

    order = PendingLimitOrder(
        order_id=order_id,
        symbol=symbol,
        limit_price=limit_price,
        capital=capital,
        atr_val=atr_val,
        atr_pct=atr_pct,
        analysis=analysis,
        volume_24h=volume_24h,
        side=side,
        created_at=time.time(),
        expires_at=time.time() + validity_secs,
        status="PENDING"
    )
    bot.pending_orders[symbol] = order
    meta_gate.register_signal(order_id, symbol, analysis.get("features", {}))
    tactic_label = "ESPERAR RETESTEO" if is_retest else "MAKER LÍMITE"
    dir_label = "SHORT (Venta en Resistencia)" if side == "short" else "LONG (Compra en Soporte)"
    print(f"  🎯 [ORDEN {tactic_label} {dir_label}] {symbol} (Gen #{brain.generation})", flush=True)
    print(f"       Precio Actual: ${current_price:.5f} -> LÍMITE: ${limit_price:.5f} ({'+' if side == 'short' else '-'}{pull_offset_pct*100:.2f}%)", flush=True)
    if forward_target > 0:
        print(f"       🎯 Target Predictivo: ${forward_target:.5f} | R:R Proyectado: {rr_ratio:.2f}x", flush=True)
    print(f"       Capital: ${capital:.2f} | Válida: {validity_secs}s | Deslizamiento: $0.00 (Maker Pasivo)", flush=True)
    return True


def manage_pending_limit_orders(bot: PaperBot, prices: Dict[str, float], prev_prices: Optional[Dict[str, float]] = None):
    """
    Verifica las órdenes límite pendientes:
    - Si el precio de mercado toca o cruza el rango [tick_low, tick_high] -> EJECUTADA (Cero Slippage).
    - Si expira el tiempo sin retroceder -> CANCELADA (Previene persecución en FOMO/Crestas).
    """
    now_ts = time.time()
    for symbol, order in list(bot.pending_orders.items()):
        curr_price = prices.get(symbol)
        if curr_price is None or curr_price <= 0:
            continue

        prev_price = (prev_prices or {}).get(symbol, curr_price)
        tick_low = min(prev_price, curr_price)
        tick_high = max(prev_price, curr_price)

        is_filled = False
        is_short = (getattr(order, "side", "long") == "short")
        if not is_short and order.limit_price >= tick_low:
            is_filled = True
        elif is_short and order.limit_price <= tick_high:
            is_filled = True

        if is_filled:
            executed_price = order.limit_price
            amount = order.capital / executed_price
            maker_fee = order.capital * (FEE_RATE * 0.75)  # Tarifa Maker con descuento (0.075%)

            if bot.cash < (order.capital + maker_fee):
                del bot.pending_orders[symbol]
                continue

            bot.cash -= (order.capital + maker_fee)
            if not is_short:
                bot.holdings[symbol] = bot.holdings.get(symbol, 0.0) + amount
            bot.total_fees_paid += maker_fee

            sl_dist = order.atr_val * brain.sl_atr_mult
            if not is_short:
                sl_price = executed_price - sl_dist
                tp1_target = executed_price * (1 + brain.tp1_gain_pct / 100)
            else:
                sl_price = executed_price + sl_dist
                tp1_target = executed_price * (1 - brain.tp1_gain_pct / 100)

            pos_id = f"pos_{int(time.time()*1000)}"

            pos = LongPosition(
                position_id=pos_id,
                symbol=symbol,
                initial_amount=amount,
                amount=amount,
                entry_price=executed_price,
                stop_loss=sl_price,
                initial_sl=sl_price,
                trailing_stop=sl_price,
                highest_price=executed_price,
                lowest_price=executed_price,
                capital_allocated=order.capital,
                atr_at_entry=order.atr_val,
                features_at_entry=order.analysis.get("features", {}),
                side="short" if is_short else "long",
                strategy="short_limit" if is_short else "long_limit"
            )
            bot.longs[symbol] = pos
            meta_gate.register_signal(pos_id, symbol, order.analysis.get("features", {}))

            strat_name = "short_limit" if is_short else "long_limit"
            side_str = "sell" if is_short else "buy"
            bot.log_trade(
                symbol=symbol, strategy=strat_name, side=side_str, price=executed_price, amount=amount,
                pnl=0.0, fee=maker_fee, slippage=0.0,
                extra=f"Entrada Límite Maker ({'SHORT' if is_short else 'LONG'}): SL=${sl_price:.5f} | TP1=${tp1_target:.5f} (±{brain.tp1_gain_pct:.2f}%)",
                pos_id=pos_id, status="OPEN"
            )

            fill_tag = "RESISTENCIA (SHORT)" if is_short else "SOPORTE (LONG)"
            print(f"  ⚡ [LÍMITE EJECUTADA EN {fill_tag}] {symbol} @ ${executed_price:.5f}!", flush=True)
            print(f"       Capital: ${order.capital:.2f} | Deslizamiento: $0.0000 (Maker) | SL: ${sl_price:.5f} | TP1: ${tp1_target:.5f}", flush=True)
            del bot.pending_orders[symbol]
            bot.save_portfolio_state()

        elif now_ts >= order.expires_at:
            print(f"  ⏱️ [LÍMITE EXPIRADA SIN FILL] {symbol} @ ${order.limit_price:.5f} (Nivel no alcanzado; liberando slot)", flush=True)
            del bot.pending_orders[symbol]


# ====================== EJECUCIÓN AGRESIVA A MERCADO (BREAKOUT / TAKER) ======================
def open_market_trade(bot: PaperBot, symbol: str, capital: float, current_price: float,
                      analysis: Dict, volume_24h: float, side: str = "long", extra_info: str = "") -> bool:
    """
    Ejecuta una orden a mercado inmediata si el comité multi-agente decide BREAKOUT_MARKET.
    Aplica cálculo de slippage realista y tarifa taker.
    """
    if capital < MIN_ORDER_USDT:
        return False

    fee_estimate = capital * FEE_RATE
    total_cost_required = capital + fee_estimate

    if bot.cash < total_cost_required:
        return False

    atr_val = analysis.get("atr_value", current_price * 0.02)
    atr_pct = analysis.get("atr_pct", 2.0)
    is_short = (side == "short")
    slip_side = "sell" if is_short else "buy"

    executed_price, slip_pct = apply_slippage(current_price, slip_side, atr_pct, volume_24h, is_limit=False)
    amount = capital / executed_price
    actual_fee = capital * FEE_RATE

    bot.cash -= (capital + actual_fee)
    if not is_short:
        bot.holdings[symbol] = bot.holdings.get(symbol, 0.0) + amount
    bot.total_fees_paid += actual_fee
    bot.total_slippage_cost += abs(executed_price - current_price) * amount

    sl_dist = atr_val * brain.sl_atr_mult
    if not is_short:
        sl_price = executed_price - sl_dist
        tp1_target = executed_price * (1 + brain.tp1_gain_pct / 100)
    else:
        sl_price = executed_price + sl_dist
        tp1_target = executed_price * (1 - brain.tp1_gain_pct / 100)

    pos_id = f"pos_{int(time.time()*1000)}"

    pos = LongPosition(
        position_id=pos_id,
        symbol=symbol,
        initial_amount=amount,
        amount=amount,
        entry_price=executed_price,
        stop_loss=sl_price,
        initial_sl=sl_price,
        trailing_stop=sl_price,
        highest_price=executed_price,
        lowest_price=executed_price,
        capital_allocated=capital,
        atr_at_entry=atr_val,
        features_at_entry=analysis.get("features", {}),
        side="short" if is_short else "long",
        strategy="short_market" if is_short else "long_market"
    )
    bot.longs[symbol] = pos

    trade_strat = "short_market" if is_short else "long_market"
    trade_side_log = "sell" if is_short else "buy"
    info_tag = f"SL=${sl_price:.5f} | TP1=${tp1_target:.5f} (±{brain.tp1_gain_pct:.2f}%) | {extra_info}"
    bot.log_trade(
        symbol=symbol, strategy=trade_strat, side=trade_side_log, price=executed_price, amount=amount,
        pnl=0.0, fee=actual_fee, slippage=abs(executed_price - current_price) * amount,
        extra=info_tag, pos_id=pos_id, status="OPEN"
    )

    dir_tag = "SHORT" if is_short else "LONG"
    print(f"  ⚡ [EJECUCIÓN MARKET BREAKOUT {dir_tag}] {symbol} @ ${executed_price:.5f} (Toma de Liquidez Inmediata)", flush=True)
    print(f"       Capital: ${capital:.2f} | Fee: ${actual_fee:.4f} | Deslizamiento: {slip_pct*100:.3f}% | SL: ${sl_price:.5f} | TP1: ${tp1_target:.5f}", flush=True)
    bot.save_portfolio_state()
    return True


def open_long(bot: PaperBot, symbol: str, capital: float, current_price: float,
              analysis: Dict, volume_24h: float) -> bool:
    return open_market_trade(bot, symbol, capital, current_price, analysis, volume_24h, side="long")


def manage_longs(bot: PaperBot, prices: Dict[str, float], atrs: Dict[str, float]):
    """
    Gestiona todas las posiciones vivas (LONG y SHORT):
    - Long: gana si precio sube, pierde si cae por debajo de SL.
    - Short: gana si precio cae, pierde si sube por encima de SL.
    """
    for symbol, pos in list(bot.longs.items()):
        if not pos.active:
            continue

        price = prices.get(symbol)
        if price is None or price <= 0:
            continue

        pos.total_checks += 1
        is_short = (getattr(pos, "side", "long") == "short")

        # Cálculo de rentabilidad porcentual
        if not is_short:
            gain_pct = ((price / pos.entry_price) - 1) * 100
            if price > pos.highest_price:
                pos.highest_price = price
        else:
            gain_pct = ((pos.entry_price / price) - 1) * 100
            if price < getattr(pos, "lowest_price", 99999999.0):
                pos.lowest_price = price

        if gain_pct > pos.max_gain_pct:
            pos.max_gain_pct = gain_pct

        atr = atrs.get(symbol, pos.atr_at_entry)

        # 1. ESCUDO BREAK-EVEN TEMPRANO (+1.80% DE GANANCIA)
        if not pos.break_even_activated and (gain_pct >= EARLY_BREAK_EVEN_TRIGGER_PCT or pos.max_gain_pct >= EARLY_BREAK_EVEN_TRIGGER_PCT):
            if not is_short:
                be_price = pos.entry_price * (1 + EARLY_BREAK_EVEN_LOCK_PCT / 100)
                if be_price > pos.stop_loss:
                    pos.stop_loss = be_price
                    pos.trailing_stop = be_price
                    pos.break_even_activated = True
                    pos.status_msg = f"🛡️ BREAK-EVEN BLINDADO (+{EARLY_BREAK_EVEN_LOCK_PCT:.2f}% ASEGURADO)"
                    print(f"  🛡️ [ESCUDO BREAK-EVEN LONG] {symbol} tocó +{gain_pct:.2f}%! SL elevado a ${be_price:.5f}", flush=True)
                    bot.save_portfolio_state()
            else:
                be_price = pos.entry_price * (1 - EARLY_BREAK_EVEN_LOCK_PCT / 100)
                if be_price < pos.stop_loss:
                    pos.stop_loss = be_price
                    pos.trailing_stop = be_price
                    pos.break_even_activated = True
                    pos.status_msg = f"🛡️ BREAK-EVEN BLINDADO (+{EARLY_BREAK_EVEN_LOCK_PCT:.2f}% ASEGURADO)"
                    print(f"  🛡️ [ESCUDO BREAK-EVEN SHORT] {symbol} tocó +{gain_pct:.2f}%! SL bajado a ${be_price:.5f}", flush=True)
                    bot.save_portfolio_state()

        # 2. TOMA DE BENEFICIOS TP1 (15% para cubrir todas las comisiones y dejar 85% RUNNER)
        pos_vol = get_position_volume_24h(pos)
        if not pos.tp1_hit and gain_pct >= brain.tp1_gain_pct:
            # Solo cerramos el 15% de la posición: cubre comisiones de entrada, salida y asegura ganancia neta en caja
            close_amount = pos.amount * 0.15
            slip_side = "buy" if is_short else "sell"
            exec_p, _ = apply_slippage(price, slip_side, (atr / price) * 100, pos_vol)

            if not is_short:
                revenue = close_amount * exec_p
                fee = revenue * FEE_RATE
                pnl_tp1 = revenue - fee - (close_amount * pos.entry_price)
                bot.cash += (revenue - fee)
                bot.holdings[symbol] = max(0.0, bot.holdings.get(symbol, 0.0) - close_amount)
                be_price = pos.entry_price * 1.0025
                pos.stop_loss = max(pos.stop_loss, be_price)
                pos.trailing_stop = max(pos.trailing_stop, be_price)
            else:
                # En short: compramos de vuelta más barato para cerrar el 15%
                cost_to_cover = close_amount * exec_p
                fee = cost_to_cover * FEE_RATE
                orig_capital = close_amount * pos.entry_price
                pnl_tp1 = orig_capital - cost_to_cover - fee
                # Retornamos el margen original + la ganancia neta a la caja
                bot.cash += (orig_capital + pnl_tp1)
                be_price = pos.entry_price * 0.9975
                pos.stop_loss = min(pos.stop_loss, be_price)
                pos.trailing_stop = min(pos.trailing_stop, be_price)
            pos.capital_allocated -= (close_amount / pos.initial_amount) * pos.capital_allocated
            pos.amount -= close_amount
            pos.realized_pnl += pnl_tp1
            bot.total_fees_paid += fee
            pos.tp1_hit = True
            pos.break_even_activated = True
            pos.status_msg = "🎯 FEES CUBIERTOS (+15% EN CAJA) | 85% RUNNER LIBRE 🚀"

            strat_tp1 = "short_tp1" if is_short else "long_tp1"
            side_tp1 = "buy" if is_short else "sell"
            bot.log_trade(
                symbol=symbol, strategy=strat_tp1, side=side_tp1, price=exec_p, amount=close_amount,
                pnl=pnl_tp1, fee=fee, slippage=0.0,
                extra=f"TP1 Fee Buffer ({'SHORT' if is_short else 'LONG'}): +{gain_pct:.2f}% | SL en Break-Even ${pos.stop_loss:.5f} | 85% Runner Corriendo",
                pos_id=pos.position_id, status="PARTIAL_CLOSED"
            )
            print(f"  🎯 [TP1 FEE BUFFER {'SHORT' if is_short else 'LONG'}] {symbol}: +{pnl_tp1:+.4f} USDT (Comisiones cubiertas). ¡85% de la posición corriendo libre!", flush=True)

        # 3. TRAILING STOP AGRESIVO DEL RUNNER (+3.20% o más)
        if pos.tp1_hit and gain_pct >= RUNNER_TRAILING_TRIGGER_PCT:
            if not pos.trailing_activated:
                pos.trailing_activated = True
                print(f"  🚀 [RUNNER TRAILING AGRESIVO {'SHORT' if is_short else 'LONG'}] {symbol} superó +{gain_pct:.2f}%!", flush=True)

            if pos.trailing_activated:
                if not is_short:
                    runner_trailing = price - (atr * RUNNER_ATR_MULT)
                    if runner_trailing > pos.stop_loss:
                        pos.stop_loss = runner_trailing
                        pos.trailing_stop = runner_trailing
                        pos.status_msg = f"🚀 RUNNER TRAILING ACTIVO (${pos.trailing_stop:.5f})"
                else:
                    runner_trailing = price + (atr * RUNNER_ATR_MULT)
                    if runner_trailing < pos.stop_loss:
                        pos.stop_loss = runner_trailing
                        pos.trailing_stop = runner_trailing
                        pos.status_msg = f"🚀 RUNNER TRAILING ACTIVO (${pos.trailing_stop:.5f})"

        # 4. SALIDA Y CIERRE POR STOP LOSS, TRAILING O BARRERA TEMPORAL (Triple Barrier)
        exit_reason = None
        pos_entry_ts = getattr(pos, "entry_time", 0.0)
        if not pos_entry_ts and getattr(pos, "created_at", ""):
            try:
                pos_entry_ts = datetime.fromisoformat(pos.created_at).timestamp()
            except Exception:
                pos_entry_ts = time.time()
        elapsed_pos_sec = time.time() - pos_entry_ts if pos_entry_ts else 0.0

        # Verificación de Stop Loss
        hit_stop = (price <= pos.stop_loss) if not is_short else (price >= pos.stop_loss)
        if hit_stop:
            if pos.trailing_activated:
                exit_reason = "Runner Trailing Stop Agresivo"
            elif pos.break_even_activated:
                exit_reason = "Escudo Break-Even (+0.20% Protegido)"
            else:
                exit_reason = "Stop Loss Inicial (2.2x ATR)"

        if exit_reason:
            slip_side = "buy" if is_short else "sell"
            executed_price, slip_pct = apply_slippage(price, slip_side, (atr / price) * 100, pos_vol)

            if not is_short:
                revenue = pos.amount * executed_price
                fee = revenue * FEE_RATE
                pnl_final = revenue - fee - (pos.amount * pos.entry_price)
                bot.cash += (revenue - fee)
                bot.holdings[symbol] = max(0.0, bot.holdings.get(symbol, 0.0) - pos.amount)
                if bot.holdings.get(symbol, 0) < 1e-10:
                    bot.holdings.pop(symbol, None)
            else:
                cost_to_cover = pos.amount * executed_price
                fee = cost_to_cover * FEE_RATE
                orig_capital = pos.amount * pos.entry_price
                pnl_final = orig_capital - cost_to_cover - fee
                # Retornar margen + ganancia neta de short
                bot.cash += (orig_capital + pnl_final)

            bot.total_fees_paid += fee
            bot.total_slippage_cost += abs(executed_price - price) * pos.amount
            total_trade_pnl = pos.realized_pnl + pnl_final
            pos.realized_pnl = total_trade_pnl
            pos.active = False

            strat_exit = "short_exit" if is_short else "long_exit"
            side_exit = "buy" if is_short else "sell"
            bot.log_trade(
                symbol=symbol, strategy=strat_exit, side=side_exit, price=executed_price, amount=pos.amount,
                pnl=pnl_final, fee=fee, slippage=abs(executed_price - price) * pos.amount,
                extra=exit_reason, pos_id=pos.position_id, status="CLOSED"
            )

            brain.learn_from_trade(
                symbol=symbol, strategy="short" if is_short else "long", entry_p=pos.entry_price,
                exit_p=executed_price, pnl=total_trade_pnl, exit_reason=exit_reason,
                max_gain_pct=pos.max_gain_pct, features=pos.features_at_entry
            )
            meta_gate.label_trade_outcome(pos.position_id, total_trade_pnl)

            pos_dir_tag = "SHORT" if is_short else "LONG"
            print(f"  🏁 [CIERRE {pos_dir_tag}] {symbol} @ ${executed_price:.5f} | PnL Total: {total_trade_pnl:+.4f} USDT ({exit_reason})", flush=True)

            # Auditoría Forense Asíncrona con IA de NVIDIA (NIM)
            ai_auditor.audit_async({
                "symbol": symbol,
                "side": "short" if is_short else "long",
                "net_pnl": total_trade_pnl,
                "entry_price": pos.entry_price,
                "exit_price": executed_price,
                "hold_min": elapsed_pos_sec / 60.0,
                "exit_reason": exit_reason,
                "entry_score": getattr(pos, "entry_score", 50.0)
            })

            del bot.longs[symbol]
            bot.save_portfolio_state()


# ====================== STREAMING DE ESTADO EN VIVO ======================
LIVE_STATE_LOCK = threading.Lock()
LAST_HTML_SYNC_TS = 0.0
LAST_PNL_AUDIT_TS = 0.0

def update_live_state(bot: PaperBot, prices: Dict[str, float],
                      latest_opportunities: List[Dict], cycle_num: int):
    global LATEST_LIVE_STATE, LAST_HTML_SYNC_TS, LAST_PNL_AUDIT_TS
    now_audit = time.time()
    if (now_audit - LAST_PNL_AUDIT_TS) >= 15.0 or not bot.latest_pnl_audit:
        LAST_PNL_AUDIT_TS = now_audit
        try:
            bot.latest_pnl_audit = auditor.get_pnl_audit()[:30]
        except Exception:
            pass
    equity = bot.get_equity(prices)
    grid_market_val = sum(
        (l["amount"] * (prices.get(g.symbol) or ((g.grid_upper + g.grid_lower) / 2.0))) if l["side"] == "sell" else (l["price"] * l["amount"])
        for g in bot.grids.values() if g.active
        for l in g.lines if l.get("active")
    )
    holdings_val = bot.get_holdings_value(prices) + grid_market_val
    # Calcular PnL Flotante de Posiciones Sniper y de Mallas Activas
    total_cost_basis = 0.0
    unrealized_pnl = 0.0
    for pos in bot.longs.values():
        if not pos.active:
            continue
        total_cost_basis += pos.amount * pos.entry_price
        curr_p = prices.get(pos.symbol, pos.entry_price)
        if getattr(pos, "side", "long") != "short":
            unrealized_pnl += (curr_p - pos.entry_price) * pos.amount
        else:
            unrealized_pnl += (pos.entry_price - curr_p) * pos.amount

    # Incorporar mallas en flotante y valor retenido
    for grid in bot.grids.values():
        if not grid.active:
            continue
        curr_p = prices.get(grid.symbol, grid.grid_upper)
        for line in grid.lines:
            if not line["active"]:
                continue
            if line["side"] == "buy":
                total_cost_basis += (line["price"] * line["amount"])
            elif line["side"] == "sell":
                # Monedas compradas a la espera de venta límite arriba
                cost_of_buy = line["amount"] * (line["price"] / (1 + grid.step_pct))
                total_cost_basis += cost_of_buy
                unrealized_pnl += (line["amount"] * curr_p - cost_of_buy)

    # PnL Realizado total y PnL Flotante exactos por identidad contable estricta
    has_active_risk = any(p.active for p in bot.longs.values()) or any(g.active for g in bot.grids.values())
    if not has_active_risk or holdings_val <= 0.0001:
        unrealized_pnl = 0.0
        unrealized_pct = 0.0
        realized_pnl = round(equity - INITIAL_CAPITAL, 4)
    else:
        # Si hay posiciones abiertas, el flotante acumulado es el valor vivo en riesgo
        realized_pnl = round((equity - INITIAL_CAPITAL) - unrealized_pnl, 4)
        unrealized_pct = (unrealized_pnl / holdings_val * 100) if holdings_val > 0 else 0.0

    recent_trades = vault.get_recent_trades(limit=250)
    equity_hist = vault.get_equity_history(sample_limit=300)
    if not equity_hist:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        equity_hist = [{"t": now_str, "v": round(equity, 2)}]

    positions_list = []
    for pos in bot.longs.values():
        if not pos.active:
            continue
        curr_p = prices.get(pos.symbol, pos.entry_price)
        is_pos_short = (getattr(pos, "side", "long") == "short")
        
        if not is_pos_short:
            flot_dollar = (curr_p - pos.entry_price) * pos.amount
            flot_pct = ((curr_p / pos.entry_price) - 1) * 100 if pos.entry_price > 0 else 0.0
            tp1_target_p = pos.entry_price * (1 + brain.tp1_gain_pct / 100)
        else:
            flot_dollar = (pos.entry_price - curr_p) * pos.amount
            flot_pct = ((pos.entry_price / curr_p) - 1) * 100 if curr_p > 0 else 0.0
            tp1_target_p = pos.entry_price * (1 - brain.tp1_gain_pct / 100)

        curr_val = pos.capital_allocated + flot_dollar
        positions_list.append({
            "symbol": pos.symbol,
            "side": getattr(pos, "side", "long"),
            "strategy": pos.strategy,
            "entry_price": round(pos.entry_price, 7),
            "current_price": round(curr_p, 7),
            "amount": round(pos.amount, 4),
            "capital": round(curr_val, 2),
            "capital_initial": round(pos.capital_allocated, 2),
            "capital_current": round(curr_val, 2),
            "floating_pnl": round(flot_dollar, 4),
            "floating_pct": round(flot_pct, 2),
            "max_gain_pct": round(pos.max_gain_pct, 2),
            "tp1_price": round(tp1_target_p, 7),
            "stop_loss": round(pos.stop_loss, 7),
            "tp1_hit": pos.tp1_hit,
            "break_even_activated": pos.break_even_activated,
            "status_msg": pos.status_msg,
            "position_id": pos.position_id
        })

    compound_sz = calculate_compound_order_size(bot, equity)

    # Lista de órdenes límite pendientes para la UI
    pending_list = []
    now_ts = time.time()
    for s, po in bot.pending_orders.items():
        curr_p = prices.get(s, po.limit_price)
        dist_to_limit = ((curr_p / po.limit_price) - 1) * 100 if po.limit_price > 0 else 0.0
        rem_sec = max(0, int(po.expires_at - now_ts))
        pending_list.append({
            "order_id": po.order_id,
            "symbol": po.symbol,
            "side": getattr(po, "side", "long"),
            "limit_price": round(po.limit_price, 7),
            "price": round(po.limit_price, 7),
            "current_price": round(curr_p, 7),
            "capital": round(po.capital, 2),
            "distance_pct": round(dist_to_limit, 2),
            "remaining_sec": rem_sec,
            "status": po.status
        })

    new_state = {
        "timestamp": datetime.now().isoformat(),
        "cycle": cycle_num,
        "generation": brain.generation,
        "equity": round(equity, 2),
        "initial_capital": INITIAL_CAPITAL,
        "max_grids": max(1, min(6, int(equity // 125.0))) if equity >= 80.0 else 1,
        "cash": round(bot.cash, 2),
        "holdings_val": round(holdings_val, 2),
        "unrealized_pnl": round(unrealized_pnl, 4),
        "unrealized_pct": round(unrealized_pct, 2),
        "realized_pnl": round(realized_pnl, 4),
        "win_rate": round(bot.win_rate(), 1),
        "wins": bot.wins,
        "losses": bot.losses,
        "total_trades": bot.total_trades,
        "tp1_gain_pct": round(brain.tp1_gain_pct, 2),
        "min_score": round(brain.min_score_required, 1),
        "weights": brain.weights,
        "compound_size": compound_sz,
        "positions": positions_list,
        "grids": [
            {
                **g.to_dict(),
                "current_price": prices.get(g.symbol) or ((g.grid_upper + g.grid_lower) / 2.0),
                "unrealized_pnl": round(sum(
                    (l["amount"] * (prices.get(g.symbol) or ((g.grid_upper + g.grid_lower) / 2.0)) - (l["amount"] * l.get("buy_price", l["price"] / (1 + g.step_pct))))
                    for l in g.lines if l.get("active") and l.get("side") == "sell"
                ), 4),
                "fills_count": getattr(g, "fills_count", 0),
                "buy_fills_count": getattr(g, "buy_fills_count", 0),
                "sell_fills_count": getattr(g, "sell_fills_count", 0),
                "trade_history": (lambda trades, g_obj, p_curr: trades if trades else [{
                    "id": 0,
                    "timestamp": g_obj.created_at,
                    "symbol": g_obj.symbol,
                    "strategy": "grid_init",
                    "side": "setup",
                    "price": p_curr,
                    "amount": round(sum(l["amount"] for l in g_obj.lines if l.get("side") == "sell"), 4),
                    "pnl": 0.0,
                    "fee": 0.0,
                    "slippage": 0.0,
                    "extra_info": f"Malla Desplegada: {g_obj.grid_lines} órdenes (${g_obj.capital_total:.2f} USDT)",
                    "position_id": g_obj.grid_id,
                    "status": "OPEN"
                }])(vault.get_trades_for_position(g.grid_id), g, prices.get(g.symbol) or ((g.grid_upper + g.grid_lower) / 2.0)),
                "market_value": round(sum(
                    (l["amount"] * (prices.get(g.symbol) or ((g.grid_upper + g.grid_lower) / 2.0))) if l["side"] == "sell" else (l["price"] * l["amount"])
                    for l in g.lines if l.get("active")
                ), 2),
                "tokens_held": round(sum(l["amount"] for l in g.lines if l.get("active") and l["side"] == "sell"), 4),
                "reval_diagnosis": (lambda diag, curr_p, be_p: {
                    **diag,
                    "state": diag.get("state", "MONITORING"),
                    "reason": diag.get("reason", "Monitoreo activo de volumen, ADX y libro de órdenes cada ciclo."),
                    "be_price": be_p,
                    "held_tokens": diag.get("held_tokens", round(sum(l["amount"] for l in g.lines if l.get("active") and l["side"] == "sell"), 2)),
                    "recovered_cash": diag.get("recovered_cash", 0.0),
                    "time_in_anomaly": diag.get("time_in_anomaly") or (
                        f"{int(max(0.0, time.time() - (getattr(g, 'anomaly_start_ts', 0.0) or getattr(g, 'last_fill_ts', time.time()))) // 3600)}h {int((max(0.0, time.time() - (getattr(g, 'anomaly_start_ts', 0.0) or getattr(g, 'last_fill_ts', time.time()))) % 3600) // 60)}m"
                    ),
                    "deviation_floor_pct": diag.get("deviation_floor_pct", round(((curr_p - g.grid_lower) / g.grid_lower) * 100.0, 2) if g.grid_lower > 0 else 0.0),
                    "dist_to_be_pct": diag.get("dist_to_be_pct", round(((be_p - curr_p) / curr_p) * 100.0, 2) if curr_p > 0 else 0.0),
                    "floor_price": round(g.grid_lower, 4),
                    "ceil_price": round(g.grid_upper, 4),
                    "clinical_verdict": diag.get("clinical_verdict", "Monitoreo activo de libro y salida en Breakeven.")
                })(
                    getattr(g, "reval_diagnosis", {}) or {},
                    prices.get(g.symbol) or ((g.grid_upper + g.grid_lower) / 2.0),
                    (getattr(g, "reval_diagnosis", {}) or {}).get("be_price") or (
                        round(sum(l["amount"] * l.get("buy_price", l["price"] / (1 + g.step_pct)) for l in g.lines if l.get("active") and l["side"] == "sell") / max(0.0001, sum(l["amount"] for l in g.lines if l.get("active") and l["side"] == "sell")), 6)
                        if any(l.get("active") and l["side"] == "sell" for l in g.lines) else (prices.get(g.symbol) or ((g.grid_upper + g.grid_lower) / 2.0))
                    )
                )
            }
            for g in bot.grids.values() if g.active
        ],
        "pending_limit_orders": pending_list,
        "pnl_audit": bot.latest_pnl_audit or [],
        "self_eval": bot.latest_self_eval or {},
        "meta_model": meta_gate.get_summary(),
        "scanner_opportunities": latest_opportunities,
        "btc_macro": macro_engine.btc_macro_state,
        "ai_audits": ai_auditor.audits[-6:],
        "system_memory": ai_auditor.system_memory,
        "committee_deliberations": agent_committee.deliberations[-5:],
        "active_parameters": {
            "sl_atr_mult": brain.sl_atr_mult,
            "min_score": brain.min_score_required,
            "tp1_pct": brain.tp1_gain_pct
        },
        "recent_trades": recent_trades,
        "equity_history": equity_hist,
        "last_agent_pct": LAST_AGENT_PCT
    }

    with LIVE_STATE_LOCK:
        LATEST_LIVE_STATE = new_state

    try:
        with open(LIVE_STATE_FILE_LOCAL, "w", encoding="utf-8") as f:
            json.dump(new_state, f)
        if LIVE_STATE_FILE_ARTIFACT and os.path.exists(ARTIFACT_DIR):
            with open(LIVE_STATE_FILE_ARTIFACT, "w", encoding="utf-8") as f:
                json.dump(new_state, f)

        # Sincronizar HTML a disco cada 30 segundos (evita 2400 escrituras pesadas innecesarias por hora)
        now_write = time.time()
        if (now_write - LAST_HTML_SYNC_TS) >= 30.0 or LAST_HTML_SYNC_TS == 0.0:
            LAST_HTML_SYNC_TS = now_write
            html_spa = dashboard_spa.get_dashboard_spa_html(initial_state=new_state)
            with open(DASHBOARD_HTML_LOCAL, "w", encoding="utf-8") as f:
                f.write(html_spa)
            if DASHBOARD_HTML_ARTIFACT and os.path.exists(ARTIFACT_DIR):
                with open(DASHBOARD_HTML_ARTIFACT, "w", encoding="utf-8") as f:
                    f.write(html_spa)
    except Exception:
        pass


# ====================== SERVIDOR HTTP REACTIVO PARA DASHBOARD DINÁMICO ======================
class DynamicDashboardHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        try:
            clean_path = self.path.split("?")[0].rstrip("/")
            if clean_path in ("/api/state", "/live_state.json"):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                with LIVE_STATE_LOCK:
                    state_obj = dict(LATEST_LIVE_STATE)
                if not state_obj and os.path.exists(LIVE_STATE_FILE_LOCAL):
                    try:
                        with open(LIVE_STATE_FILE_LOCAL, "r", encoding="utf-8") as f:
                            state_obj = json.load(f)
                    except Exception:
                        pass
                state_bytes = json.dumps(state_obj).encode("utf-8")
                self.wfile.write(state_bytes)
            elif clean_path in ("", "/dashboard", "/dashboard.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                with LIVE_STATE_LOCK:
                    current_snap = dict(LATEST_LIVE_STATE)
                if not current_snap and os.path.exists(LIVE_STATE_FILE_LOCAL):
                    try:
                        with open(LIVE_STATE_FILE_LOCAL, "r", encoding="utf-8") as f:
                            current_snap = json.load(f)
                    except Exception:
                        pass
                html_content = dashboard_spa.get_dashboard_spa_html(initial_state=current_snap)
                self.wfile.write(html_content.encode("utf-8"))
            elif clean_path in ("/office", "/office.html"):
                office_file = os.path.join(LOG_DIR, "office.html")
                if os.path.exists(office_file):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    with open(office_file, "r", encoding="utf-8") as f:
                        self.wfile.write(f.read().encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()
        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            print(f"  [Dashboard HTTP Server Error] {e}", flush=True)

    def do_POST(self):
        try:
            if self.path == "/api/close_grid":
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
                data = json.loads(body) if body else {}
                symbol = data.get("symbol", "")

                with COMMAND_QUEUE_LOCK:
                    COMMAND_QUEUE.append({"action": "close_grid", "symbol": symbol, "timestamp": time.time()})

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "queued", "action": "close_grid", "symbol": symbol}).encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))

    def log_message(self, format, *args):
        pass


def start_live_http_server(port: int = HTTP_PORT):
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), DynamicDashboardHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        print(f"  🌐 [DASHBOARD DINÁMICO EN VIVO] Accede en: http://localhost:{port}", flush=True)
    except Exception as e:
        print(f"  [Dashboard HTTP Server Warning] {e}", flush=True)


# ====================== LOOP PRINCIPAL ======================
def run_paper_trading(reset_all: bool = False):
    bot = PaperBot()

    if reset_all:
        bot.reset_and_close_all(target_cash=INITIAL_CAPITAL)

    # Sincronizar archivos HTML del Dashboard SPA
    html_spa = dashboard_spa.get_dashboard_spa_html()
    try:
        with open(DASHBOARD_HTML_LOCAL, "w", encoding="utf-8") as f:
            f.write(html_spa)
        if os.path.exists(ARTIFACT_DIR):
            with open(DASHBOARD_HTML_ARTIFACT, "w", encoding="utf-8") as f:
                f.write(html_spa)
    except Exception:
        pass

    # Iniciar servidor HTTP en vivo
    start_live_http_server(HTTP_PORT)

    trading_mode = os.environ.get("TRADING_MODE", "paper").upper()
    exchange_target = os.environ.get("EXCHANGE", "pionex").upper()
    print("=" * 80, flush=True)
    print("  QUANTITATIVE SPOT GRID BOT v12 - INTERÉS COMPUESTO & MOTOR DE ALTA FRECUENCIA", flush=True)
    print(f"  • Modo Operativo                 -> [{trading_mode}] Exchange Objetivo: {exchange_target}", flush=True)
    print(f"  • Pionex Bridge Adapter          -> Listo para Ejecución Real (HMAC-SHA256)", flush=True)
    print(f"  • Interés Compuesto              -> 100% Activo (Re-inversión automática de cada micro-ganancia)", flush=True)
    print(f"  • Malla Adaptativa               -> 6 a 7 Líneas dinámicas (Paso: 0.95% - 1.35% ATR)", flush=True)
    print(f"  • Mínimo por Orden               -> ${MIN_ORDER_USDT:.2f} USDT Estricto (Líneas de ~$10.50-$13.00 USDT)", flush=True)
    print(f"  • Dashboard Reactivo en Vivo     -> Streaming continuo en http://localhost:{HTTP_PORT}", flush=True)
    print(f"  • Saldo Disponible: ${bot.cash:.2f} USDT | Saldo Base: ${INITIAL_CAPITAL:.2f} USDT", flush=True)
    print("=" * 80, flush=True)

    cycle = 0
    last_scan_time = 0
    latest_opportunities = []
    if os.path.exists(LIVE_STATE_FILE_LOCAL):
        try:
            with open(LIVE_STATE_FILE_LOCAL, "r", encoding="utf-8") as f:
                latest_opportunities = json.load(f).get("scanner_opportunities", [])
        except Exception:
            pass

    last_known_prices: Dict[str, float] = {}
    last_trade_timestamps: Dict[str, int] = {}
    cached_atrs: Dict[str, tuple] = {}  # symbol -> (atr_value, cached_timestamp)
    deliberation_cooldown: Dict[str, float] = {}

    # Ejecutar primera auto-evaluación con el historial previo
    bot.run_self_evaluation()
    
    # Inicializar estado macro antes de empezar para la UI
    macro_engine.run_macro_cycle(["BTC/USDT", "ETH/USDT"])

    while bot.is_alive:
        try:
            cycle += 1
            now_ts = time.time()
            now_str = datetime.now().strftime("%H:%M:%S")

            # Decaimiento temporal suave del cerebro para evitar estancamiento
            if cycle % 10 == 0:
                brain.time_decay()

            prev_tick_prices = dict(last_known_prices)
            prices, volumes, atrs, tick_ranges = {}, {}, {}, {}
            monitored_symbols = set(list(bot.holdings.keys()) + list(bot.longs.keys()) + list(bot.pending_orders.keys()) + [g.symbol for g in bot.grids.values() if g.active])

            for sym in monitored_symbols:
                try:
                    t = exchange.fetch_ticker(sym)
                    last_p = float(t["last"])
                    prices[sym] = last_p
                    last_known_prices[sym] = last_p
                    volumes[sym] = float(t.get("quoteVolume") or (float(t.get("baseVolume", 0) or 0) * last_p) or 15_000_000)
                    previous_trade_ts = last_trade_timestamps.get(
                        sym, int((now_ts - CHECK_INTERVAL_SECONDS) * 1000)
                    )
                    try:
                        trades = exchange.fetch_trades(sym, since=previous_trade_ts, limit=1000)
                    except Exception:
                        trades = []
                    trade_timestamps = [
                        int(trade["timestamp"])
                        for trade in trades
                        if isinstance(trade, dict) and trade.get("timestamp") is not None
                    ]
                    if trade_timestamps:
                        last_trade_timestamps[sym] = max(trade_timestamps)
                    tick_ranges[sym] = get_tick_price_range(
                        trades, prev_tick_prices.get(sym, last_p), last_p
                    )
                    
                    # Cache de ATR 1h (TTL: 60s) para ticks ultra-rápidos de 1.5s sin latencia de red
                    if sym in cached_atrs and (now_ts - cached_atrs[sym][1]) < 60.0:
                        atrs[sym] = cached_atrs[sym][0]
                    else:
                        ohlcv = exchange.fetch_ohlcv(sym, "1h", limit=20)
                        df = pd.DataFrame(ohlcv, columns=["ts", "o", "h", "l", "c", "v"])
                        tr = pd.concat([
                            df["h"] - df["l"],
                            (df["h"] - df["c"].shift()).abs(),
                            (df["l"] - df["c"].shift()).abs()
                        ], axis=1).max(axis=1)
                        atr_v = float(tr.mean())
                        atrs[sym] = atr_v
                        cached_atrs[sym] = (atr_v, now_ts)
                except Exception:
                    if sym in last_known_prices:
                        prices[sym] = last_known_prices[sym]
                    elif sym in bot.longs and bot.longs[sym].entry_price > 0:
                        prices[sym] = bot.longs[sym].entry_price
                    elif sym in bot.pending_orders:
                        prices[sym] = bot.pending_orders[sym].limit_price
                    if sym in cached_atrs:
                        atrs[sym] = cached_atrs[sym][0]

            # Procesar comandos manuales recibidos desde el Dashboard SPA
            with COMMAND_QUEUE_LOCK:
                pending_cmds = list(COMMAND_QUEUE)
                COMMAND_QUEUE.clear()

            for cmd in pending_cmds:
                action = cmd.get("action")
                cmd_sym = cmd.get("symbol")
                if action == "close_grid" and cmd_sym:
                    cur_p = prices.get(cmd_sym) or last_known_prices.get(cmd_sym, 0.0)
                    if cur_p > 0:
                        bot.close_grid_market(cmd_sym, cur_p)
                    else:
                        print(f"  ⚠️ [CMD CLOSE_GRID] Precio no disponible para {cmd_sym}", flush=True)

            # 1. Gestionar Órdenes Límite Pendientes y Mallas (Grid Engine)
            for grid_key, grid in list(bot.grids.items()):
                if not grid.active:
                    continue
                sym = grid.symbol
                curr_p = prices.get(sym)
                if not curr_p:
                    continue

                tick_low, tick_high = tick_ranges.get(
                    sym, (min(prev_tick_prices.get(sym, curr_p), curr_p), max(prev_tick_prices.get(sym, curr_p), curr_p))
                )
                step_sz = getattr(grid, "step_size", 0.0)
                 
                # Check lines: Procesar compras ordenadas de mayor a menor precio
                active_buys = active_grid_orders(grid.lines, "buy")
                active_sells = active_grid_orders(grid.lines, "sell")
                for line in sorted(active_buys, key=lambda x: -x["price"]):
                    # SIMULACIÓN REALISTA DE COLA LOB (0.03% de penetración para superar la fila en Binance/Pionex)
                    penetration_buy_p = line["price"] * (1.0 - 0.0003)
                    if tick_low <= penetration_buy_p:
                        # Ejecutar Compra Limit
                        fees = (line["amount"] * line["price"]) * FEE_RATE
                        line["active"] = False
                        grid.ticks_without_fill = 0
                        grid.last_fill_ts = time.time()
                        grid.fills_count = getattr(grid, "fills_count", 0) + 1
                        grid.buy_fills_count = getattr(grid, "buy_fills_count", 0) + 1
                        
                        # Crear orden de venta en el siguiente escalón simétrico
                        if step_sz > 0:
                            sell_price = line["price"] + step_sz
                        else:
                            sell_price = line["price"] * (1 + grid.step_pct)
                        amt_after_fee = line["amount"] * (1 - FEE_RATE)
                        
                        grid.lines.append({"price": sell_price, "side": "sell", "amount": amt_after_fee, "buy_price": line["price"], "active": True})
                        bot.log_trade(
                            symbol=sym, strategy="grid_buy", side="buy", price=line["price"], amount=line["amount"],
                            pnl=0.0, fee=fees, slippage=0.0,
                            extra=f"Malla Escalón Comprado: Venta colocada en ${sell_price:.4f} (+{(sell_price/line['price'] - 1)*100:.2f}%)",
                            pos_id=grid.grid_id, status="OPEN"
                        )
                        print(f"  🕸️🟢 [MALLA BUY {sym}] Comprado a ${line['price']:.4f}. Venta colocada a ${sell_price:.4f}", flush=True)
                        bot.save_portfolio_state()
                        
                # Check lines: Procesar ventas ordenadas de menor a mayor precio
                for line in sorted(active_sells, key=lambda x: x["price"]):
                    # SIMULACIÓN REALISTA DE COLA LOB (0.03% de penetración por encima para superar la fila)
                    penetration_sell_p = line["price"] * (1.0 + 0.0003)
                    if tick_high >= penetration_sell_p:
                        # Ejecutar Venta Limit
                        gross = line["amount"] * line["price"]
                        fees = gross * FEE_RATE
                        net_usdt = gross - fees
                        
                        line["active"] = False
                        grid.ticks_without_fill = 0
                        grid.last_fill_ts = time.time()
                        grid.fills_count = getattr(grid, "fills_count", 0) + 1
                        grid.sell_fills_count = getattr(grid, "sell_fills_count", 0) + 1
                        
                        # Ganancia real rigurosa basada en el precio de compra real guardado
                        fallback_buy_p = (line["price"] - step_sz) if step_sz > 0 else (line["price"] / (1 + grid.step_pct))
                        real_buy_price = line.get("buy_price", fallback_buy_p)
                        buy_cost = line["amount"] * real_buy_price
                        profit = net_usdt - buy_cost
                        grid.realized_pnl += profit
                        bot.total_realized_pnl_acc += profit
                        bot.cash += net_usdt
                        bot.wins += 1
                        bot.total_trades += 1
                        
                        # RE-EVALUACIÓN CUANTITATIVA: ESCUDO ANTI-MECHAZOS (Anti-Wick Shield)
                        regime_sell = get_symbol_1h_regime(sym)
                        rsi_sell = regime_sell.get("rsi_1h", 50.0)
                        upper_bb_sell = regime_sell.get("upper_bb", 999999.0)
                        is_overextended = (rsi_sell >= 70.0) or (curr_p >= upper_bb_sell)

                        if is_overextended:
                            # Sobrecompra extrema / Clímax alcista: NO recomprar la punta de la mecha
                            print(f"  🛡️⚠️ [ESCUDO ANTI-MECHAZOS {sym}] Venta cobrada en ${line['price']:.4f}. RSI 1h={rsi_sell:.1f} >= 70 o sobre Bollinger. Efectivo (+${net_usdt:.2f} USDT) protegido en caja líquida sin recomprar la punta de la mecha.", flush=True)
                            grid.status_msg = f"Escudo Anti-Mechazos: RSI {rsi_sell:.1f} >= 70. Ganancia en caja, recompras congeladas en máximos."
                        else:
                            # Régimen sano dentro del rango: recolocar compra normal escalonada abajo simétrica
                            if step_sz > 0:
                                buy_price = line["price"] - step_sz
                            else:
                                buy_price = line["price"] / (1 + grid.step_pct)
                            cost = line["amount"] * buy_price
                            if bot.cash >= cost:
                                bot.cash -= cost
                                grid.lines.append({"price": buy_price, "side": "buy", "amount": line["amount"], "buy_price": buy_price, "active": True})
                                print(f"  🕸️🔴 [MALLA SELL {sym}] Vendido a ${line['price']:.4f}. Ganancia: +${profit:.4f}. Recomprando a ${buy_price:.4f}", flush=True)
                            else:
                                print(f"  ⚠️ [MALLA {sym}] Saldo insuficiente para recolocar compra a ${buy_price:.4f}", flush=True)

                        recompra_txt = "Anti-Mechazo (Caja Segura)" if is_overextended else f"Recompra lista en ${buy_price:.4f}"
                        bot.log_trade(
                            symbol=sym, strategy="grid_sell", side="sell", price=line["price"], amount=line["amount"],
                            pnl=profit, fee=fees, slippage=0.0,
                            extra=f"Malla Escalón Cosechado: Ganancia neta +${profit:.4f} USDT | {recompra_txt}",
                            pos_id=grid.grid_id, status="CLOSED"
                        )
                        bot.save_portfolio_state()

                # =========================================================================
                # 🤖 SUPERVISOR DINÁMICO DE MALLA (Vigilancia Inteligente y No Estática)
                # =========================================================================
                grid.ticks_without_fill = getattr(grid, "ticks_without_fill", 0) + 1

                # 1. COMPRESIÓN DINÁMICA Y RE-EVALUACIÓN POR ESTANCAMIENTO:
                # Si la moneda lateraliza en seco sin cruzar ninguna línea por ~35-40 segundos (>25 ticks)
                if grid.ticks_without_fill >= 25:
                    grid.ticks_without_fill = 0 # Resetear contador
                    
                    # Si el paso aún permite compresión (> 0.40% libre de comisiones):
                    old_step = compress_grid_spacing(grid, curr_p)
                    if old_step is not None:
                        step_sz = grid.step_size
                        grid.dynamic_adjustments_count = getattr(grid, "dynamic_adjustments_count", 0) + 1
                        grid.status_msg = f"Intervalos comprimidos ({old_step*100:.2f}% -> {grid.step_pct*100:.2f}%)"
                        print(f"  ⚡ [SUPERVISOR DINÁMICO {sym}] Sin fills. Paso comprimido de {old_step*100:.2f}% a {grid.step_pct*100:.2f}%.", flush=True)
                    else:
                        grid.status_msg = "Rebalanceando escalones cerca del precio vivo"

                    # RE-EVALUACIÓN ANTE ANOMALÍAS (Solo si se sale de lo normal):
                    # Si el precio y el volumen están en rangos normales, la malla opera libremente sin intervención.
                    active_sells = [l for l in grid.lines if l.get("active") and l.get("side") == "sell"]
                    active_buys = [l for l in grid.lines if l.get("active") and l.get("side") == "buy"]

                    total_held_tokens = sum(l["amount"] for l in active_sells)
                    total_held_cost = sum(l["amount"] * l.get("buy_price", l["price"] / (1 + grid.step_pct)) for l in active_sells)
                    be_price = (total_held_cost / total_held_tokens) * (1 + (FEE_RATE * 2.2)) if total_held_tokens > 0 else curr_p

                    # Detección de Anomalías Reales:
                    # 1. Ruptura por debajo del piso de la malla
                    is_below_floor = curr_p < grid.grid_lower
                    # 2. Estancamiento anómalo extremo: más de 80 ticks consecutivos sin fill Y volumen < $8M
                    vol_now = volumes.get(sym, 15_000_000)
                    is_extreme_stagnation = (getattr(grid, "ticks_without_fill", 0) >= 80) and (vol_now < 8_000_000)

                    if (is_below_floor or is_extreme_stagnation) and total_held_tokens > 0:
                        # Si es la primera vez que entra en anomalía, registrar el timestamp de inicio
                        if getattr(grid, "anomaly_start_ts", 0.0) == 0.0:
                            grid.anomaly_start_ts = getattr(grid, "last_fill_ts", 0.0) or time.time()

                        elapsed_s = max(0.0, time.time() - grid.anomaly_start_ts)
                        hrs = int(elapsed_s // 3600)
                        mins = int((elapsed_s % 3600) // 60)
                        time_str = f"{hrs}h {mins}m" if hrs > 0 else f"{mins}m"

                        dev_floor_pct = ((curr_p - grid.grid_lower) / grid.grid_lower) * 100.0 if grid.grid_lower > 0 else 0.0
                        dist_be_pct = ((be_price - curr_p) / curr_p) * 100.0 if curr_p > 0 else 0.0

                        if abs(dev_floor_pct) <= 1.0:
                            clinical_verdict = f"Desviación Leve ({dev_floor_pct:+.2f}%): Oscila apenas pegado al piso. Paciencia recomendada para rebote."
                        elif abs(dev_floor_pct) <= 3.0:
                            clinical_verdict = f"Desviación Moderada ({dev_floor_pct:+.2f}%): Retesteo de soporte. Salida en Breakeven a {dist_be_pct:+.2f}%."
                        else:
                            clinical_verdict = f"Caída Profunda ({dev_floor_pct:+.2f}%): Cortafuegos activo (límite -3.50%)."

                        # =========================================================================
                        # 🛡️ CORTAFUEGOS INSTITUCIONAL (CIRCUIT BREAKERS DE SALIDA)
                        # =========================================================================
                        # 1. STOP CATASTRÓFICO POR DESVIACIÓN PROFUNDA:
                        # Si el precio perfora más de -3.50% por debajo del piso de la malla,
                        # liquidar de inmediato para proteger el capital ante una capitulación.
                        if dev_floor_pct <= -3.50:
                            print(f"\n  🚨🛑 [CIRCUIT BREAKER: STOP CATASTRÓFICO {sym}] Desviación extrema ({dev_floor_pct:+.2f}% <= -3.50%). Liquidando inventario para proteger capital...", flush=True)
                            bot.close_grid_market(sym, curr_p, reason="Stop Catastrófico: Caída > 3.5% bajo el piso")
                            continue

                        # 2. TIME-STOP / ROTACIÓN DE CAPITAL:
                        # Si la malla permanece más de 4 horas (14400s) estancada bajo el piso sin poder rebotar al Breakeven,
                        # liquidar la posición para liberar el USDT líquido y rotar al nuevo candidato líder del radar.
                        if elapsed_s >= 4.0 * 3600.0:
                            print(f"\n  ⏱️🛑 [CIRCUIT BREAKER: TIME-STOP {sym}] {time_str} estancado bajo el piso sin alcanzar Breakeven. Liquidando posición para rotación de capital...", flush=True)
                            bot.close_grid_market(sym, curr_p, reason=f"Time-Stop: {time_str} sin rebote a Breakeven")
                            continue

                        # =========================================================================
                        # 🧗 RE-EVALUACIÓN CUANTITATIVA: TRAILING DOWN vs BREAKEVEN DEFENSIVO
                        # =========================================================================
                        can_shift, reval_verdict, current_score = evaluate_anomaly_trailing_down(
                            grid, sym, curr_p, dev_floor_pct, latest_opportunities, macro_engine.btc_macro_state
                        )

                        if can_shift:
                            new_low, new_high = apply_trailing_down_shift(grid, curr_p)
                            grid.status_msg = f"Trailing Down ejecutado: Piso ${new_low:.4f} (Score: {current_score:.0f})"
                            reval_diag = {
                                "state": "TRAILING_DOWN_LADDER",
                                "reason": f"Re-evaluación positiva: {reval_verdict}. Rango adaptado para capturar rebote.",
                                "be_price": round(be_price, 6),
                                "held_tokens": round(total_held_tokens, 2),
                                "recovered_cash": 0.0,
                                "time_in_anomaly": "0m",
                                "elapsed_seconds": 0,
                                "deviation_floor_pct": 0.0,
                                "dist_to_be_pct": round(dist_be_pct, 2),
                                "floor_price": round(new_low, 4),
                                "ceil_price": round(new_high, 4),
                                "clinical_verdict": f"Trailing Down activo. Nuevo soporte en ${new_low:.4f}."
                            }
                            grid.reval_diagnosis = reval_diag
                            print(f"\n  🧗⚡ [TRAILING DOWN / ESCALÓN DE DESCUENTO {sym}]", flush=True)
                            print(f"       {reval_verdict}", flush=True)
                            print(f"       Nuevo Rango: ${new_low:.4f} - ${new_high:.4f} | Escalón {grid.trailing_down_shifts}/1.", flush=True)
                            continue

                        # PROTOCOLO DE SALIDA INTELIGENTE EN BREAKEVEN ANTE ANOMALÍA (RECHAZADO TRAILING DOWN)
                        grid.freeze_buys = True
                        recovered_buy_cash = 0.0
                        for b in active_buys:
                            recovered_buy_cash += (b["price"] * b["amount"])
                            b["active"] = False
                        bot.cash += recovered_buy_cash

                        # Concentrar ventas retenidas en precio de equilibrio (Breakeven + comisiones)
                        for s in active_sells:
                            s["price"] = max(be_price, curr_p * (1 + 0.0015))

                        grid.status_msg = f"Anomalía ({reval_verdict}): Compras canceladas (+${recovered_buy_cash:.2f} libre). Ventas en Breakeven (${be_price:.6f})"
                        reval_diag = {
                            "state": "ANOMALY_BREAKEVEN",
                            "reason": f"Anomalía detectada ({reval_verdict}). Ventas listas en Breakeven (${be_price:.6f}) para salir sin pérdida.",
                            "be_price": round(be_price, 6),
                            "held_tokens": round(total_held_tokens, 2),
                            "recovered_cash": round(recovered_buy_cash, 2),
                            "time_in_anomaly": time_str,
                            "elapsed_seconds": round(elapsed_s, 0),
                            "deviation_floor_pct": round(dev_floor_pct, 2),
                            "dist_to_be_pct": round(dist_be_pct, 2),
                            "floor_price": round(grid.grid_lower, 4),
                            "ceil_price": round(grid.grid_upper, 4),
                            "clinical_verdict": f"{clinical_verdict} (Re-evaluación: {reval_verdict})"
                        }
                        print(f"  🛡️⚡ [ANOMALÍA DETECTADA: {sym}] {reval_verdict}. Canceladas compras inferiores (+${recovered_buy_cash:.2f} a caja). Ventas en breakeven (${be_price:.6f}) para salida sin pérdida.", flush=True)
                    else:
                        grid.anomaly_start_ts = 0.0
                        # OPERACIÓN NORMAL ESTÁNDAR: No interferir con la malla
                        reval_diag = {
                            "state": "NORMAL",
                            "reason": f"Comportamiento normal dentro de rango. La malla cosecha habitualmente (${grid.grid_lower:.4f} - ${grid.grid_upper:.4f}).",
                            "be_price": round(be_price, 6),
                            "held_tokens": round(total_held_tokens, 2),
                            "recovered_cash": 0.0,
                            "time_in_anomaly": "0m",
                            "elapsed_seconds": 0,
                            "deviation_floor_pct": 0.0,
                            "dist_to_be_pct": round(((be_price - curr_p) / curr_p) * 100.0, 2) if curr_p > 0 else 0.0,
                            "floor_price": round(grid.grid_lower, 4),
                            "ceil_price": round(grid.grid_upper, 4),
                            "clinical_verdict": "Malla operando en rango normal con oscilación activa."
                        }
                    grid.reval_diagnosis = reval_diag

                    # Reajustar la distribución de escalones para que SIEMPRE haya compras abajo y ventas arriba
                    active_buys = [l for l in grid.lines if l["active"] and l["side"] == "buy"]
                    active_sells = [l for l in grid.lines if l["active"] and l["side"] == "sell"]
                    
                    # Si todas las compras se habían ejecutado y solo quedaban ventas, colocar compras escalonadas abajo (Solo si no está congelado por caída o breakeven exit)
                    is_buys_frozen = getattr(grid, "freeze_buys", False)
                    if len(active_buys) < 2 and bot.cash >= 10.0 and not is_buys_frozen:
                        rebalance_cap = min(bot.cash * 0.7, 25.0)
                        lines_to_add = 3
                        sub_cap = rebalance_cap / lines_to_add
                        step_val = step_sz if step_sz > 0 else (curr_p * grid.step_pct)
                        for step_i in range(1, lines_to_add + 1):
                            p_buy = curr_p - (step_val * step_i)
                            bot.cash -= sub_cap
                            grid.lines.append({"price": p_buy, "side": "buy", "amount": sub_cap / p_buy, "buy_price": p_buy, "active": True})
                            print(f"  🕸️🟢 [REBALANCEO DINÁMICO {sym}] Compra simétrica recolocada a ${p_buy:.4f}", flush=True)
                    
                    # Ajustar precios de órdenes existentes asegurando SIEMPRE ganancia neta (preservar target profit)
                    step_val = step_sz if step_sz > 0 else (curr_p * grid.step_pct)
                    for idx, l in enumerate(sorted([x for x in grid.lines if x['active'] and x['side'] == 'sell'], key=lambda x: x['price'])):
                        min_profit_price = l.get('buy_price', curr_p) + step_val
                        if l.get('price', 0.0) < min_profit_price:
                            l['price'] = min_profit_price
                    if not is_buys_frozen:
                        for idx, l in enumerate(sorted([x for x in grid.lines if x['active'] and x['side'] == 'buy'], key=lambda x: -x['price'])):
                            reserved = l['price'] * l['amount']
                            l['price'] = curr_p - (step_val * (idx + 1))
                            l['amount'] = reserved / l['price']
                            l['buy_price'] = l['price']

                # 2. GESTIÓN JERÁRQUICA DE COSECHA TOTAL Y RUPTURA:
                active_sells = [l for l in grid.lines if l.get("active") and l.get("side") == "sell"]

                # A. Victoria Total o Trailing Up (Todas las Ventas Cosechadas con Ganancia):
                if len(active_sells) == 0 and getattr(grid, "fills_count", 0) > 0:
                    opp = next((o for o in (latest_opportunities or []) if o.get("symbol") == sym), None)
                    current_score = float(opp.get("score", 0.0)) if opp else 0.0
                    features = opp.get("analysis", {}).get("features", {}) if opp else {}
                    rsi_val = float(features.get("rsi", 50.0))
                    is_healthy_trend = (current_score >= 55.0) and (rsi_val < 75.0)

                    # Trailing Up libre e ilimitado mientras el activo mantenga salud cuantitativa:
                    if is_healthy_trend and bot.cash >= 10.0:
                        new_low, new_high, recov = apply_trailing_up_shift(grid, bot, curr_p)
                        grid_pnl_val = getattr(grid, "realized_pnl", 0.0)
                        print(f"\n  🚀🧗 [TRAILING UP ILIMITADO {sym}]", flush=True)
                        print(f"       100% de ventas cobradas. Tendencia activa (Score {current_score:.1f} >= 55 | RSI {rsi_val:.1f} < 75).", flush=True)
                        print(f"       Desplazando rango hacia arriba a ${new_low:.4f} - ${new_high:.4f} (Escalón #{grid.trailing_up_shifts}).", flush=True)
                        print(f"       Ganancia acumulada en la malla: +${grid_pnl_val:.4f} USDT. ¡Cosecha continúa!\n", flush=True)
                        bot.save_portfolio_state()
                        continue
                    else:
                        recovered_cash = sum((l["price"] * l["amount"]) for l in grid.lines if l.get("active") and l.get("side") == "buy")
                        for l in grid.lines:
                            l["active"] = False
                        bot.cash += recovered_cash
                        grid.active = False
                        grid_pnl_val = getattr(grid, "realized_pnl", 0.0)
                        grid.status_msg = f"Victoria Total Cosechada (+{grid_pnl_val:+.2f} USDT). Capital liberado a caja."
                        bot.save_portfolio_state()
                        print(f"  🚀🟢 [VICTORIA TOTAL / COSECHA {sym}] 100% de órdenes cobradas. Cierre y toma de beneficios (+{grid_pnl_val:+.4f} USDT). ${recovered_cash:.2f} USDT devueltos a caja líquida.", flush=True)

                # B. Si el precio cae por debajo del piso de la malla (con inventario vivo):
                elif curr_p < grid.grid_lower:
                    grid.freeze_buys = True  # 1. Congelar compras de inmediato (Anti-Knife Shield)
                    grid.out_of_range_ticks = getattr(grid, "out_of_range_ticks", 0) + 1
                    dist_below_floor_pct = ((grid.grid_lower - curr_p) / grid.grid_lower) * 100
                    
                    # Consultar Indicador Estructural Único: Bollinger Bands (1h) + RSI 14 (1h)
                    regime = get_symbol_1h_regime(sym)
                    rsi_1h = regime.get("rsi_1h", 50.0)
                    lower_bb = regime.get("lower_bb", grid.grid_lower)

                    # Calcular VWAP exacto de todas las órdenes de venta activas (inventario retenido)
                    total_tokens = sum(l["amount"] for l in active_sells)
                    total_buy_cost = sum(l["amount"] * l.get("buy_price", l["price"] / (1 + grid.step_pct)) for l in active_sells)
                    vwap = (total_buy_cost / total_tokens) if total_tokens > 0 else grid.grid_lower

                    # =========================================================================
                    # REGLA 1: "ELÁSTICO ESTIRADO" (RSI 1h < 30.0 o Precio bajo Lower Bollinger)
                    # =========================================================================
                    if rsi_1h < 30.0 or curr_p <= lower_bb:
                        grid.status_msg = f"Elástico Estirado (RSI 1h: {rsi_1h:.1f} < 30) | Modo Paciente: Compras congeladas. Esperando rebote al VWAP (${vwap:.4f}) para Relief Exit."
                        
                        # SALIDA DE ALIVIO (Relief Exit) en Rebote Técnico:
                        # Si el precio rebota al VWAP o breakeven (+-0.2%):
                        if curr_p >= (vwap * 0.998) and len(active_sells) > 0:
                            half_count = max(1, len(active_sells) // 2)
                            sells_to_liquidate = sorted(active_sells, key=lambda x: x["price"])[:half_count]
                            
                            rel_cost = sum(l["amount"] * l.get("buy_price", l["price"] / (1 + grid.step_pct)) for l in sells_to_liquidate)
                            rel_tokens = sum(l["amount"] for l in sells_to_liquidate)
                            rel_val = (rel_tokens * curr_p) * (1 - FEE_RATE)
                            rel_pnl = rel_val - rel_cost
                            
                            for l in sells_to_liquidate:
                                l["active"] = False
                            
                            grid.realized_pnl += rel_pnl
                            bot.total_realized_pnl_acc += rel_pnl
                            bot.cash += rel_val
                            if rel_pnl >= 0:
                                bot.wins += 1
                            else:
                                bot.losses += 1
                            bot.total_trades += 1
                            
                            bot.log_trade(
                                symbol=sym, strategy="grid_relief_exit", side="sell", price=curr_p, amount=rel_tokens,
                                pnl=round(rel_pnl, 4), fee=round(rel_val * FEE_RATE, 4), slippage=0.0,
                                extra=f"Relief Exit 50%: Liberados ${rel_val:.2f} USDT en breakeven/alivio (PnL: {rel_pnl:+.4f})",
                                pos_id=grid.grid_id, status="CLOSED"
                            )
                            grid.status_msg = f"Relief Exit ejecutado: 50% vendido a ${curr_p:.4f}. ${rel_val:.2f} USDT liberados a caja."
                            print(f"  ⚡🟢 [RELIEF EXIT {sym}] Rebote a VWAP (${vwap:.4f}). Vendido 50% ({rel_tokens:.4f} {sym}). Liberados ${rel_val:.2f} USDT a caja líquida.", flush=True)
                            bot.save_portfolio_state()

                    # =========================================================================
                    # REGLA 2: "TENDENCIA DESTRUCTIVA" (RSI 1h >= 40.0 Y Caída > 3.5% bajo el piso)
                    # =========================================================================
                    elif rsi_1h >= 40.0 and dist_below_floor_pct >= 3.5:
                        print(f"  🛑⚠️ [STOP ESTRUCTURAL {sym}] Ruptura de Régimen: RSI 1h={rsi_1h:.1f} >= 40 con caída de -{dist_below_floor_pct:.1f}% bajo piso. Liquidando...", flush=True)
                        total_sell_val = 0.0
                        recovered_cash = 0.0
                        sold_tokens = 0.0
                        for l in grid.lines:
                            if not l["active"]:
                                continue
                            if l["side"] == "buy":
                                recovered_cash += (l["price"] * l["amount"])
                            elif l["side"] == "sell":
                                sell_val = (l["amount"] * curr_p) * (1 - FEE_RATE)
                                total_sell_val += sell_val
                                recovered_cash += sell_val
                                sold_tokens += l["amount"]
                            l["active"] = False

                        liquidation_loss = total_sell_val - total_buy_cost
                        grid.realized_pnl += liquidation_loss
                        bot.total_realized_pnl_acc += liquidation_loss
                        bot.cash += recovered_cash
                        if liquidation_loss < 0:
                            bot.losses += 1
                        else:
                            bot.wins += 1
                        bot.total_trades += 1
                        bot.log_trade(
                            symbol=sym, strategy="grid_structural_stop", side="sell", price=curr_p, amount=sold_tokens,
                            pnl=round(liquidation_loss, 4), fee=round(total_sell_val * FEE_RATE, 4), slippage=0.0,
                            extra=f"Stop Estructural por Ruptura: RSI {rsi_1h:.1f} | Pérdida {liquidation_loss:+.4f} USDT | Liberados ${recovered_cash:.2f}",
                            pos_id=grid.grid_id, status="CLOSED"
                        )
                        grid.active = False
                        grid.status_msg = f"Stop estructural ejecutado ({liquidation_loss:+.2f} USDT)"
                        bot.save_portfolio_state()

                    else:
                        grid.status_msg = f"Modo Paciente: Caída -{dist_below_floor_pct:.1f}% bajo piso (RSI 1h: {rsi_1h:.1f}). Compras congeladas, esperando resolución."

                # C. Ruptura de Techo hacia arriba (Tendencia alcista fuerte con ventas aún vivas):
                elif curr_p > grid.grid_upper * 1.012:
                    grid.freeze_buys = False
                    grid.out_of_range_ticks = getattr(grid, "out_of_range_ticks", 0) + 1
                    grid.status_msg = f"Ruptura alcista (+{((curr_p/grid.grid_upper)-1)*100:.1f}%)"
                    if grid.out_of_range_ticks >= 15:  # ~35s confirmado
                        opp = next((o for o in (latest_opportunities or []) if o.get("symbol") == sym), None)
                        current_score = float(opp.get("score", 0.0)) if opp else 0.0
                        features = opp.get("analysis", {}).get("features", {}) if opp else {}
                        rsi_val = float(features.get("rsi", 50.0))
                        is_healthy_trend = (current_score >= 55.0) and (rsi_val < 75.0)

                        # Trailing Up libre e ilimitado mientras el activo mantenga salud cuantitativa:
                        if is_healthy_trend and bot.cash >= 10.0:
                            new_low, new_high, recov = apply_trailing_up_shift(grid, bot, curr_p)
                            grid_pnl_val = getattr(grid, "realized_pnl", 0.0)
                            print(f"\n  🚀🧗 [TRAILING UP POR RUPTURA {sym}]", flush=True)
                            print(f"       Ruptura alcista confirmada (Score {current_score:.1f} >= 55 | RSI {rsi_val:.1f} < 75).", flush=True)
                            print(f"       Desplazando rango hacia arriba a ${new_low:.4f} - ${new_high:.4f} (Escalón #{grid.trailing_up_shifts}).", flush=True)
                            print(f"       Ganancia acumulada en la malla: +${grid_pnl_val:.4f} USDT. ¡Cosecha continúa!\n", flush=True)
                            bot.save_portfolio_state()
                            continue

                        # Si el score decayó o entró en sobrecompra extrema (RSI >= 75): Tomar ganancias finales completas
                        active_sells = [l for l in grid.lines if l.get("active") and l.get("side") == "sell"]
                        sold_tokens = sum(l["amount"] for l in active_sells)
                        sell_proceeds = (sold_tokens * curr_p) * (1 - FEE_RATE) if sold_tokens > 0 else 0.0
                        total_buy_cost = sum(l["amount"] * l.get("buy_price", l["price"] / (1 + grid.step_pct)) for l in active_sells)
                        trailing_profit = (sell_proceeds - total_buy_cost) if sold_tokens > 0 else 0.0

                        recovered_buy_cash = sum((l["price"] * l["amount"]) for l in grid.lines if l.get("active") and l.get("side") == "buy")
                        total_recovered = recovered_buy_cash + sell_proceeds

                        for l in grid.lines:
                            l["active"] = False

                        bot.cash += total_recovered
                        grid.realized_pnl += trailing_profit
                        bot.total_realized_pnl_acc += trailing_profit
                        if trailing_profit >= 0:
                            bot.wins += 1
                        else:
                            bot.losses += 1
                        bot.total_trades += 1

                        if sold_tokens > 0:
                            bot.log_trade(
                                symbol=sym, strategy="grid_trailing_exit", side="sell", price=curr_p, amount=sold_tokens,
                                pnl=round(trailing_profit, 4), fee=round(sell_proceeds * FEE_RATE, 4), slippage=0.0,
                                extra=f"Trailing Alcista Techo: Vendidos {sold_tokens:.4f} {sym} a ${curr_p:.4f} (+${trailing_profit:.4f} USDT) | Liberados ${total_recovered:.2f} a caja",
                                pos_id=grid.grid_id, status="CLOSED"
                            )

                        grid.active = False
                        grid.status_msg = f"Trailing alcista finalizado: Capital liberado (${total_recovered:.2f} USDT)"
                        bot.save_portfolio_state()
                        print(f"  🚀🟢 [TRAILING ALCISTA CIERRE {sym}] Rompimiento alcista exitoso completado. Malla reciclada liberando ${total_recovered:.2f} (${recovered_buy_cash:.2f} compras canceladas + ${sell_proceeds:.2f} tokens vendidos a ${curr_p:.4f}).", flush=True)

                # D. En Rango Normal:
                else:
                    grid.freeze_buys = False
                    grid.out_of_range_ticks = 0

            manage_pending_limit_orders(bot, prices, prev_tick_prices)

            # 2. Gestionar Posiciones Long Vivas (TP1, Break-Even, Trailing, SL)
            if bot.longs:
                try:
                    manage_longs(bot, prices, atrs)
                except Exception as err:
                    print(f"  [Error Posición] {err}", flush=True)

            equity = bot.get_equity(prices)
            bot.log_equity(equity, prices)
            bot.update_drawdown(equity)

            if not bot.check_survival(equity):
                print(f"\n[ALERTA] BOT DETENIDO POR SUPERVIVENCIA: {bot.death_reason}", flush=True)
                break

            # Actualización de Régimen Macro Independiente (cada 60s)
            if macro_engine.is_update_due():
                macro_engine.run_macro_cycle(list(monitored_symbols) + ["BTC/USDT", "ETH/USDT"])

            # Escaneo de Oportunidades del Mercado (Radar):
            # Concurrencia Dinámica Escalonada por Capital (Modelo Híbrido Autónomo):
            # $80 - $125 USDT -> 1 malla activa
            # $125 - $250 USDT -> 2 mallas activas
            # $250 - $375 USDT -> 3 mallas activas
            # $375 - $550 USDT -> 4 mallas activas máximo
            # > $550 USDT -> escala orgánicamente
            max_allowed_grids = max(1, min(6, int(equity // 125.0))) if equity >= 80.0 else 1
            active_grids_count = len([g for g in bot.grids.values() if g.active])
            slots_available = (active_grids_count < max_allowed_grids and bot.open_positions_count() < MAX_TOTAL_POSITIONS and len(bot.pending_orders) < MAX_TOTAL_POSITIONS)
            scan_interval = FAST_SCAN_INTERVAL_SECONDS if slots_available else 60.0
            scan_due = (now_ts - last_scan_time >= scan_interval) or (not latest_opportunities)

            if scan_due:
                latest_opportunities = select_best_opportunities(bot, TOP_N_SCAN)
                last_scan_time = now_ts

            # Disparo Francotirador: El Comité Multi-Agente delibera y decide si hay slots disponibles
            if slots_available and latest_opportunities:
                if cycle <= 2:
                    if cycle == 1:
                        print(f"  🛡️ [CALENTAMIENTO DEL SISTEMA] Sincronizando feeds y radar multi-factor (Ciclo {cycle}/2)...", flush=True)
                else:
                    if bot.cash >= MIN_ORDER_USDT:
                        # Selección Inteligente de Candidatos por Convicción & Calidad:
                        # 1. Filtro de Pureza Institucional: NUNCA abrir mallas en monedas mediocres (Score < 55 o Vol < $10M).
                        # 2. Diversificación Natural: Si hay múltiples monedas líderes (Score >= 55), se abren en monedas diferentes.
                        # 3. Concentración por Ultra-Convicción: Si la moneda líder tiene Score >= 65 y el resto del mercado
                        #    es mediocre, se le permite abrir una 2da malla escalonada (Tier 2 / Pullback) en rangos distintos.
                        symbol_grid_counts = {}
                        for g in bot.grids.values():
                            if g.active:
                                symbol_grid_counts[g.symbol] = symbol_grid_counts.get(g.symbol, 0) + 1

                        valid_opps = [
                            opp for opp in latest_opportunities
                            if opp.get("score", 0.0) >= 55.0 and opp.get("volume", 0.0) >= 10_000_000
                        ]

                        best_candidate = None
                        is_tiered_discount_grid = False

                        # Opción A: Buscar una moneda líder diferente que aún no tenga malla
                        for opp in valid_opps:
                            sym = opp["symbol"]
                            if sym in bot.longs or sym in bot.pending_orders:
                                continue
                            if symbol_grid_counts.get(sym, 0) == 0:
                                if (now_ts - deliberation_cooldown.get(sym, 0.0)) < 75.0:
                                    continue
                                best_candidate = opp
                                is_tiered_discount_grid = False
                                break

                        # Opción B: Si no hay otra moneda nueva con Score >= 55, pero la líder tiene Score >= 65
                        # y tiene menos de 2 mallas activas:
                        if not best_candidate and valid_opps:
                            top_opp = valid_opps[0]
                            top_sym = top_opp["symbol"]
                            if top_opp.get("score", 0.0) >= 65.0 and symbol_grid_counts.get(top_sym, 0) < 2:
                                if (now_ts - deliberation_cooldown.get(top_sym, 0.0)) >= 75.0:
                                    best_candidate = top_opp
                                    is_tiered_discount_grid = True

                        if best_candidate:
                            sym = best_candidate["symbol"]
                            analysis = best_candidate["analysis"]

                            print(f"\n  🏛️ [EVALUACIÓN CUANTITATIVA -> COMITÉ INSTITUCIONAL] Analizando parámetros óptimos para {sym}...", flush=True)
                            committee_verdict = agent_committee.deliberate_opportunity(best_candidate, macro_engine.btc_macro_state)
                            deliberation_cooldown[sym] = now_ts

                            decision = committee_verdict.get("decision", "RECHAZADO")
                            grid_upper = float(committee_verdict.get("grid_upper", 0.0))
                            grid_lower = float(committee_verdict.get("grid_lower", 0.0))
                            grid_lines = int(committee_verdict.get("grid_lines", 0))
                            comm_mult = float(committee_verdict.get("multiplicador_capital", 0.50))
                            razon = committee_verdict.get("razon_clave", "Consenso alcanzado")
                            debate = committee_verdict.get("debate", {})

                            print(f"       Centinela: {debate.get('centinela_macro', '')}", flush=True)
                            print(f"       Arquitecto: {debate.get('arquitecto_mallas', '')}", flush=True)
                            print(f"       Riesgo: {debate.get('jefe_riesgo', '')}", flush=True)
                            print(f"       Ejecución: {debate.get('coordinador_ejecucion', '')}", flush=True)

                            if decision != "APROBADO":
                                print(f"  🛑 [COMITÉ RECHAZÓ {sym}] {razon}", flush=True)
                            else:
                                global LAST_AGENT_PCT
                                available_funds = bot.cash * 0.98
                                # Poder total autónomo al bot: asigna hasta el 100% del efectivo disponible según el veredicto del comité
                                target_by_agents = round(available_funds * comm_mult, 2)
                                adjusted_capital = max(MIN_ORDER_USDT, min(available_funds, target_by_agents))
                                pct_display = round(comm_mult * 100, 0)
                                LAST_AGENT_PCT = pct_display
                                
                                print(f"  🏛️ [MALLA APROBADA {sym}] Techo: ${grid_upper:.4f} | Piso: ${grid_lower:.4f} | Líneas: {grid_lines} | Capital: ${adjusted_capital:.2f} ({pct_display:.0f}%)", flush=True)
                                
                                # Instanciar la Malla
                                if grid_lines >= 2 and grid_upper > grid_lower:
                                    if is_tiered_discount_grid:
                                        # Malla Tier 2 de Descuento (Pullback Ladder):
                                        # Se desplaza hacia abajo para pescar retrocesos de liquidez sin solapar la malla principal
                                        shift_down = (grid_upper - grid_lower) * 0.45
                                        grid_upper = max(best_candidate["price"] * 1.002, grid_upper - shift_down)
                                        grid_lower = grid_lower - shift_down
                                        print(f"  🧗 [MALLA TIER 2 / ESCALÓN DE DESCUENTO {sym}] Rango diferenciado: ${grid_lower:.4f} - ${grid_upper:.4f}", flush=True)

                                    # Ajuste institucional híbrido: Al tener 1 solo bot concentrado en $80 USDT,
                                    # expandimos las líneas a 6 o 7 para acelerar la cadencia de rebotes y micro-ganancias:
                                    if (adjusted_capital / 6.0) >= 10.0:
                                        grid_lines = max(6, min(7, int(adjusted_capital // 10.4)))
                                    elif (adjusted_capital / 5.0) >= 10.0:
                                        grid_lines = 5
                                    else:
                                        grid_lines = max(3, min(4, int(adjusted_capital // 10.0)))
                                    step_size = (grid_upper - grid_lower) / (grid_lines - 1)
                                    step_pct = step_size / grid_lower
                                    
                                    # Malla Centrada (Neutral Grid Pionex-style)
                                    cap_per_line = adjusted_capital / grid_lines
                                    if cap_per_line >= 10.0:
                                        lines = []
                                        total_cash_needed = 0.0
                                        buys_count = 0
                                        sells_count = 0
                                        current_price = best_candidate["price"]
                                        
                                        p = grid_lower
                                        while p <= grid_upper + (step_size * 0.1): # Tolerancia de flotantes
                                            if p < current_price * 0.998:
                                                # Orden Límite de Compra
                                                lines.append({"price": p, "side": "buy", "amount": cap_per_line / p, "buy_price": p, "active": True})
                                                total_cash_needed += cap_per_line
                                                buys_count += 1
                                            elif p > current_price * 1.002:
                                                # Orden Límite de Venta (Requiere compra inicial a current_price)
                                                amount = cap_per_line / p
                                                cost = amount * current_price * (1 + FEE_RATE)
                                                lines.append({"price": p, "side": "sell", "amount": amount, "buy_price": current_price, "active": True})
                                                total_cash_needed += cost
                                                sells_count += 1
                                            else:
                                                # Si el escalón cae virtualmente en el precio de mercado (+-0.2%), reubicarlo medio paso abajo para evitar fills inmediatos con pérdida de fee
                                                p_buy = current_price * (1 - (step_pct * 0.5))
                                                lines.append({"price": p_buy, "side": "buy", "amount": cap_per_line / p_buy, "buy_price": p_buy, "active": True})
                                                total_cash_needed += cap_per_line
                                                buys_count += 1
                                            p += step_size
                                            
                                        if bot.cash >= total_cash_needed:
                                            new_grid = GridPosition(
                                                grid_id=f"grid_{int(time.time()*1000)}",
                                                symbol=sym,
                                                grid_upper=grid_upper,
                                                grid_lower=grid_lower,
                                                grid_lines=grid_lines,
                                                step_pct=step_pct,
                                                capital_total=total_cash_needed,
                                                capital_per_line=cap_per_line,
                                                lines=lines,
                                                step_size=step_size
                                            )
                                            bot.grids[new_grid.grid_id] = new_grid
                                            bot.cash -= total_cash_needed
                                            bot.save_portfolio_state()
                                            print(f"  🕸️ [MALLA DESPLEGADA {sym}] ID: {new_grid.grid_id} | {buys_count} Compras abajo, {sells_count} Ventas arriba.", flush=True)
                                        else:
                                            print(f"  ⚠️ [MALLA CANCELADA] Saldo insuficiente para armar la malla centrada.", flush=True)
                                    else:
                                        print(f"  ⚠️ [MALLA CANCELADA] Capital por línea (${cap_per_line:.2f}) es menor al mínimo de $10.", flush=True)
                                # Actualizar estado en vivo en memoria y JSON para el frontend dinámico
            update_live_state(bot, prices, latest_opportunities, cycle)

            active_summary = []
            for s, l in bot.longs.items():
                p = prices.get(s, 0.0)
                active_summary.append(f"{s}: ${p:.6f} [{l.status_msg}]")

            pending_summary = []
            for s, po in bot.pending_orders.items():
                p = prices.get(s, po.limit_price)
                pending_summary.append(f"⏳ LÍMITE {s} @ ${po.limit_price:.6f} (Actual: ${p:.6f})")

            risk_slots = bot.active_risk_positions_count()
            total_open = bot.open_positions_count()
            free_runners = len([l for l in bot.longs.values() if l.tp1_hit])
            if risk_slots >= MAX_RISK_SLOTS or total_open >= MAX_TOTAL_POSITIONS:
                slot_info = f"SLOTS RIESGO OCUPADOS ({risk_slots}/{MAX_RISK_SLOTS}) | {free_runners} Runners Libres | En Juego: ${equity-bot.cash:.2f}"
            else:
                next_sz = calculate_compound_order_size(bot, equity)
                slot_info = f"Caja Libre: ${bot.cash:.2f} | Mallas: {active_grids_count}/{max_allowed_grids} (Slots Dinámicos) | Próximo Trade: ${next_sz:.2f}"

            combined_str = " | ".join(active_summary + pending_summary) if (active_summary or pending_summary) else "0 Posiciones (Escaneando cada 45s)"

            print(
                f"[{now_str}] Tick #{cycle:04d} (Gen #{brain.generation}) | Equity: ${equity:.2f} | {slot_info} | {combined_str}",
                flush=True
            )

            time.sleep(CHECK_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print("\n  Bot detenido manualmente.", flush=True)
            break
        except Exception as e:
            print(f"  [Error Ciclo #{cycle}] {e}", flush=True)
            time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    reset = ("--reset" in sys.argv)
    run_paper_trading(reset_all=reset)
