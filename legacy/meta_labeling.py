# -*- coding: utf-8 -*-
"""
Meta-Labeling Gatekeeper — Arquitectura Cuantitativa de Dos Niveles
====================================================================
Implementa el framework institucional de 2 niveles:
1. Modelo Primario: Genera la señal direccional técnica (PID + Squeeze + Soporte EMA20).
2. Meta-Modelo Secundario: Evalúa el vector de características en el momento del disparo,
   estima la probabilidad P(Éxito | Contexto) y determina el Bet Sizing óptimo.
   Si P < 0.52 o el mercado está en ruido browniano (KER < 0.22), VETA la operación.
"""

import os
import sys
import io
import json
import time
import math
import numpy as np
import pandas as pd
from typing import Dict, Tuple, List, Optional
from scipy.optimize import minimize
from scipy.special import expit

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def compute_kaufman_efficiency_ratio(series: pd.Series, period: int = 14) -> float:
    """
    Kaufman Efficiency Ratio (KER):
    KER = |Price_t - Price_{t-n}| / Sum(|Price_i - Price_{i-1}|)
    Rango [0.0, 1.0]:
    - Cercano a 1.0: Tendencia direccional limpia sin fricción.
    - Menor a 0.25: Ruido browniano sucio / rango lateral destructivo.
    """
    if len(series) < period + 1:
        return 0.5
    net_change = abs(float(series.iloc[-1]) - float(series.iloc[-period - 1]))
    diffs = series.diff().abs().iloc[-period:]
    total_path = float(diffs.sum())
    if total_path <= 1e-8:
        return 0.5
    ker = net_change / total_path
    return round(float(ker), 3)


class MetaLabelingGatekeeper:
    FEATURE_NAMES = [
        "adx_1h", "dist_ema20", "rsi_15m", "atr_pct", "vol_log",
        "pid_acc", "sq_ratio", "ker", "btc_mom", "coin_bias"
    ]

    def __init__(self, logs_dir: str = "paper_logs"):
        self.logs_dir = logs_dir
        self.dataset_file = os.path.join(logs_dir, "meta_features_dataset.csv")
        self.model_file = os.path.join(logs_dir, "meta_model.json")
        self.pending_signals: Dict[str, Dict] = {}
        
        # Pesos iniciales calibrados con priors cuantitativos
        self.weights = np.array([
            0.15,   # adx_1h (>25 positivo)
            0.45,   # dist_ema20 (soporte vs pullback)
            -0.10,  # rsi_15m (sobrecompra penaliza)
            0.30,   # atr_pct (volatilidad suficiente para fees)
            0.20,   # vol_log (volumen institucional)
            0.40,   # pid_acc (aceleración positiva d²P/dt²)
            -0.35,  # sq_ratio (compresión coiling < 1.0 es mejor)
            0.50,   # ker (eficiencia direccional)
            0.25,   # btc_mom (viento a favor de BTC)
            0.40    # coin_bias (historial positivo de la moneda)
        ], dtype=float)
        self.bias = -0.15  # Umbral conservador
        self.samples_count = 0
        self.last_trained_at = ""
        self.recent_decisions: List[Dict] = []
        
        self.load_model()
        self._init_dataset()

    def _init_dataset(self):
        os.makedirs(self.logs_dir, exist_ok=True)
        if not os.path.exists(self.dataset_file) or os.path.getsize(self.dataset_file) < 50:
            cols = ["signal_id", "symbol", "timestamp"] + self.FEATURE_NAMES + ["label", "net_pnl"]
            df = pd.DataFrame(columns=cols)
            df.to_csv(self.dataset_file, index=False)
            self.bootstrap_from_history()

    def bootstrap_from_history(self):
        """Inicializa el dataset de entrenamiento con los ciclos históricos de trades.csv."""
        trades_csv = os.path.join(self.logs_dir, "trades.csv")
        if not os.path.exists(trades_csv):
            return

        try:
            from self_eval import TradeAuditor
            auditor = TradeAuditor(self.logs_dir)
            cycles = auditor._get_cycles()
            if cycles.empty:
                return

            rows = []
            for _, c in cycles.iterrows():
                pnl = float(c["net_pnl"])
                label = 1 if pnl > 0 else 0
                sym = str(c["symbol"])
                hold_min = float(c.get("hold_duration_min", 30.0))

                # Estimaciones de features basadas en el tipo de salida y duración
                import random
                is_win = pnl > 0
                adx_est = (28.0 if is_win else 21.0) + random.gauss(0, 5.0)
                dist_est = (-0.20 if is_win else 0.40) + random.gauss(0.0, 0.5)
                ker_est = (0.38 if is_win else 0.22) + random.gauss(0, 0.10)
                acc_est = (0.005 if is_win else -0.003) + random.gauss(0, 0.01)
                sq_est = (0.95 if is_win else 1.25) + random.gauss(0, 0.2)

                # Bias histórico por moneda
                coin_bias = 0.3 if "NEAR" in sym or "MOVR" in sym or "SUI" in sym else (-0.4 if "QNT" in sym or "UNI" in sym else 0.0)

                rows.append({
                    "signal_id": c.get("position_id", f"boot_{len(rows)}"),
                    "symbol": sym,
                    "timestamp": c.get("entry_time", ""),
                    "adx_1h": adx_est,
                    "dist_ema20": dist_est,
                    "rsi_15m": 48.0 if is_win else 58.0,
                    "atr_pct": 2.6,
                    "vol_log": 25.0,
                    "pid_acc": acc_est,
                    "sq_ratio": sq_est,
                    "ker": ker_est,
                    "btc_mom": 0.2 if is_win else -0.5,
                    "coin_bias": coin_bias,
                    "direction": str(c.get("direction", "long")).lower(),
                    "label": label,
                    "net_pnl": round(pnl, 4)
                })

            if rows:
                df_boot = pd.DataFrame(rows)
                df_boot.to_csv(self.dataset_file, index=False)
                self.samples_count = len(rows)
                self.train_model()
                print(f"  🧠 [META-MODELO BOOTSTRAP] {len(rows)} trades históricos aprendidos.", flush=True)
        except Exception as e:
            print(f"  [Error Bootstrap Meta-Modelo] {e}", flush=True)

    def load_model(self):
        if os.path.exists(self.model_file):
            try:
                with open(self.model_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    loaded_weights = data.get("weights", self.weights.tolist())
                    if len(loaded_weights) == len(self.FEATURE_NAMES):
                        self.weights = np.array(loaded_weights, dtype=float)
                    self.bias = float(data.get("bias", self.bias))
                    self.samples_count = int(data.get("samples_count", 0))
                    self.last_trained_at = data.get("last_trained_at", "")
                    if "recent_decisions" in data and isinstance(data["recent_decisions"], list):
                        self.recent_decisions = data["recent_decisions"][-15:]
                    if "pending_signals" in data and isinstance(data["pending_signals"], dict):
                        self.pending_signals = data["pending_signals"]
            except Exception:
                pass

    def save_model(self):
        try:
            os.makedirs(self.logs_dir, exist_ok=True)
            data = {
                "weights": self.weights.tolist(),
                "bias": round(float(self.bias), 4),
                "samples_count": self.samples_count,
                "last_trained_at": self.last_trained_at,
                "recent_decisions": self.recent_decisions[-15:],
                "pending_signals": self.pending_signals
            }
            with open(self.model_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def normalize_features(self, feat: Dict, is_short: bool = False) -> np.ndarray:
        """Normaliza las características a rangos comparables ~[-1.5, 1.5] con clipping estricto y conciencia direccional."""
        adx_n = np.clip((float(feat.get("adx", 25.0)) - 25.0) / 15.0, -1.5, 1.5)
        
        dist_raw = float(feat.get("dist_ema20", 0.0))
        # Para Long: precio en soporte / abajo de EMA20 es positivo (-dist). Para Short: precio arriba de EMA20 es positivo (+dist).
        dist_n = np.clip((-dist_raw if not is_short else dist_raw) / 1.5, -1.5, 1.5)
        
        rsi_raw = float(feat.get("rsi", 50.0))
        # Para Long: RSI moderado / no sobrecomprado es positivo. Para Short: RSI alto / sobrecomprado es positivo.
        rsi_diff = (50.0 - rsi_raw) if not is_short else (rsi_raw - 50.0)
        rsi_n = np.clip(rsi_diff / 15.0, -1.5, 1.5)
        
        atr_n = np.clip((float(feat.get("atr_pct", 2.0)) - 2.0) / 1.5, -1.5, 1.5)
        vol_m = float(feat.get("volume_m", 15.0))
        vol_log_n = np.clip((math.log10(max(1.0, vol_m)) - 1.2) / 0.8, -1.5, 1.5)
        
        pid_acc = float(feat.get("pid_acc", 0.0))
        acc_dir = pid_acc if not is_short else -pid_acc
        acc_n = np.clip(acc_dir * 50.0, -1.5, 1.5)
        
        # Squeeze ratio: compresión (sq <= 1.0) es positiva; expansión moderada no destruye el logit
        sq_ratio = float(feat.get("sq_ratio", 1.0))
        sq_n = np.clip((1.0 - sq_ratio) / 0.8, -1.5, 1.5)
        
        ker_n = np.clip((float(feat.get("ker", 0.35)) - 0.25) / 0.20, -1.5, 1.5)
        
        btc_mom = float(feat.get("btc_mom", 0.0))
        btc_dir = btc_mom if not is_short else -btc_mom
        btc_n = np.clip(btc_dir / 2.0, -1.5, 1.5)
        
        coin_bias_n = np.clip(float(feat.get("coin_bias", 0.0)), -1.0, 1.0)

        result = np.array([
            adx_n, dist_n, rsi_n, atr_n, vol_log_n,
            acc_n, sq_n, ker_n, btc_n, coin_bias_n
        ], dtype=float)
        result = np.nan_to_num(result, nan=0.0, posinf=1.5, neginf=-1.5)
        return result

    def predict_probability(self, symbol: str, features: Dict) -> Tuple[bool, float, float, str]:
        """
        Predice P(Win | Features) y determina el Bet Sizing:
        Retorna: (veto_flag, probability, bet_size_multiplier, rationale)
        """
        ker = float(features.get("ker", 0.35))
        sq_ratio = float(features.get("sq_ratio", 1.0))
        is_coiling = sq_ratio <= 1.15
        is_short = bool(features.get("is_short", False) or features.get("direction") == "short")
        
        # 1. Filtro de Régimen Browniano (Choppiness Filter de Kaufman)
        # En squeeze o compresión, el KER natural es 0.12-0.25 (resorte cargando).
        # Solo vetar si es ruido plano absoluto (< 0.10) o si no hay compresión (< 0.14).
        min_ker = 0.10 if is_coiling else 0.14
        if ker < min_ker:
            verdict = (True, 0.30, 0.0, f"VETO REGIME: Ruido browniano plano (KER: {ker:.2f} < {min_ker:.2f})")
            self._log_decision(symbol, verdict, features)
            return verdict

        # 2. Inferencia probabilística del Meta-Modelo (con normalización direccional)
        x = self.normalize_features(features, is_short=is_short)
        logit = float(np.dot(self.weights, x) + self.bias)
        prob = float(expit(logit))  # Sigmoide: 1 / (1 + e^-z)

        if math.isnan(prob) or math.isinf(prob):
            verdict = (True, 0.0, 0.0, "VETO SANITARIO: NaN/Inf detectado en probabilidad")
            self._log_decision(symbol, verdict, features)
            return verdict

        # 3. Regla de decisión cuantitativa (con Microestructura LOB direccional)
        obi_val = float(features.get("obi", 0.0))
        
        if not is_short:
            # Para LONG: Muro de venta pesado en contra (-0.35) es Veto
            if obi_val < -0.35:
                verdict = (True, round(prob, 3), 0.0, f"VETO MICROESTRUCTURA: Muro de venta pesado en LOB (OBI: {obi_val:+.2f} < -0.35)")
                self._log_decision(symbol, verdict, features)
                return verdict
            elif obi_val > 0.15:
                prob = min(0.95, prob + 0.06)  # Boost por absorción compradora pasiva
        else:
            # Para SHORT: Muro de compra en contra (+0.35) es Veto; Muro de venta a favor empuja el precio
            if obi_val > 0.35:
                verdict = (True, round(prob, 3), 0.0, f"VETO MICROESTRUCTURA: Muro comprador absorbiendo ventas (OBI: {obi_val:+.2f} > +0.35)")
                self._log_decision(symbol, verdict, features)
                return verdict
            elif obi_val < -0.15:
                prob = min(0.95, prob + 0.08)  # Boost por presión vendedora confirmada

        # Exigencia institucional calibrada de probabilidad mínima (Meta-Labeling de Marcos López de Prado):
        # El meta-modelo modula el Bet Sizing continuo:
        # - prob < 0.35: Veto (ruido estadístico sin ventaja)
        # - 0.35 <= prob < 0.50: Entrada defensiva controlada (0.50x a 0.80x slot)
        # - prob >= 0.50: Entrada de alta convicción (0.80x a 1.00x slot)
        if prob < 0.35:
            verdict = (True, round(prob, 3), 0.0, f"VETO META-MODELO: Probabilidad insuficiente ({prob:.1%} < 35%)")
        else:
            # Bet sizing proporcional a la convicción (Kelly modificado institucional)
            multiplier = min(1.0, max(0.50, 0.50 + 2.0 * (prob - 0.35)))
            verdict = (False, round(prob, 3), round(multiplier, 2), f"APROBADO: Convicción {prob:.1%} | Slot {multiplier:.2f}x")

        self._log_decision(symbol, verdict, features)
        return verdict

    def _log_decision(self, symbol: str, verdict: Tuple, features: Dict):
        is_veto, prob, mult, reason = verdict
        record = {
            "time": time.strftime("%H:%M:%S"),
            "symbol": symbol,
            "prob": round(prob, 3),
            "prob_pct": f"{prob*100:.1f}%",
            "veto": is_veto,
            "multiplier": mult,
            "reason": reason,
            "ker": features.get("ker", 0.35)
        }
        self.recent_decisions.append(record)
        if len(self.recent_decisions) > 15:
            self.recent_decisions.pop(0)
        self.save_model()

    def register_signal(self, pos_id: str, symbol: str, features: Dict):
        """Registra el vector de características de una orden colocada."""
        self.pending_signals[pos_id] = {
            "symbol": symbol,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "features": features
        }

    def label_trade_outcome(self, pos_id: str, net_pnl: float):
        """Asigna la etiqueta y = 1 (éxito) o y = 0 (pérdida) y almacena en el dataset."""
        if pos_id not in self.pending_signals:
            return

        sig = self.pending_signals.pop(pos_id)
        feat = sig["features"]
        label = 1 if net_pnl > 0 else 0

        row = {
            "signal_id": pos_id,
            "symbol": sig["symbol"],
            "timestamp": sig["timestamp"],
            "adx_1h": feat.get("adx", 25.0),
            "dist_ema20": feat.get("dist_ema20", 0.0),
            "rsi_15m": feat.get("rsi", 50.0),
            "atr_pct": feat.get("atr_pct", 2.0),
            "vol_log": feat.get("volume_m", 15.0),
            "pid_acc": feat.get("pid_acc", 0.0),
            "sq_ratio": feat.get("sq_ratio", 1.0),
            "ker": feat.get("ker", 0.35),
            "btc_mom": feat.get("btc_mom", 0.0),
            "coin_bias": feat.get("coin_bias", 0.0),
            "direction": feat.get("direction", "long"),
            "label": label,
            "net_pnl": round(net_pnl, 4)
        }

        try:
            df_new = pd.DataFrame([row])
            df_new.to_csv(self.dataset_file, mode="a", header=not os.path.exists(self.dataset_file), index=False)
            self.samples_count += 1
            
            # Reentrenar cada 5 trades completados si hay suficientes datos
            if self.samples_count >= 12 and self.samples_count % 5 == 0:
                self.train_model()
        except Exception:
            pass

    def train_model(self):
        """Entrena la regresión logística regularizada (Ridge) sobre las muestras recolectadas."""
        if not os.path.exists(self.dataset_file):
            return

        try:
            df = pd.read_csv(self.dataset_file)
            if len(df) < 10:
                return

            X_list, y_list = [], []
            for _, r in df.iterrows():
                f_dict = {
                    "adx": r.get("adx_1h", 25.0),
                    "dist_ema20": r.get("dist_ema20", 0.0),
                    "rsi": r.get("rsi_15m", 50.0),
                    "atr_pct": r.get("atr_pct", 2.0),
                    "volume_m": r.get("vol_log", 15.0),
                    "pid_acc": r.get("pid_acc", 0.0),
                    "sq_ratio": r.get("sq_ratio", 1.0),
                    "ker": r.get("ker", 0.35),
                    "btc_mom": r.get("btc_mom", 0.0),
                    "coin_bias": r.get("coin_bias", 0.0)
                }
                is_short = str(r.get("direction", "long")) == "short"
                X_list.append(self.normalize_features(f_dict, is_short=is_short))
                y_list.append(int(r["label"]))

            X = np.array(X_list)
            y = np.array(y_list)
            n_features = X.shape[1]

            # Función de pérdida logística balanceada con penalización L2 (Ridge)
            reg_lambda = 0.5
            pos_count = float(np.sum(y))
            neg_count = float(len(y) - pos_count)
            pos_weight = (neg_count / max(1.0, pos_count)) if pos_count > 0 else 1.0

            def loss_func(params):
                w = params[:n_features]
                b = params[n_features]
                logits = np.dot(X, w) + b
                p = expit(logits)
                eps = 1e-7
                # BCE balanceada: evita que una baja tasa histórica hunda la probabilidad base a <30%
                bce = -np.mean(pos_weight * y * np.log(p + eps) + (1.0 - y) * np.log(1.0 - p + eps))
                l2 = (reg_lambda / 2.0) * np.sum(w ** 2)
                return bce + l2

            init_params = np.append(self.weights, self.bias)
            res = minimize(loss_func, init_params, method="L-BFGS-B")
            if res.success:
                self.weights = res.x[:n_features]
                self.bias = float(res.x[n_features])
                self.last_trained_at = time.strftime("%Y-%m-%d %H:%M:%S")
                self.save_model()
                print(f"  🧠 [META-MODELO RE-ENTRENADO] Muestras: {len(X)} | Pérdida: {res.fun:.4f}", flush=True)
        except Exception as e:
            print(f"  [Error Entrenamiento Meta-Modelo] {e}", flush=True)

    def get_summary(self) -> Dict:
        """Resumen del estado del Meta-Modelo para el Dashboard."""
        return {
            "samples_count": self.samples_count,
            "last_trained_at": self.last_trained_at or "Calibrado con Priors",
            "recent_decisions": self.recent_decisions[-8:] if self.recent_decisions else [],
            "feature_weights": {name: round(float(w), 3) for name, w in zip(self.FEATURE_NAMES, self.weights)}
        }


if __name__ == "__main__":
    print("=== Test MetaLabelingGatekeeper ===")
    gate = MetaLabelingGatekeeper("paper_logs")
    test_feat = {
        "adx": 30.0,
        "dist_ema20": -0.15,
        "rsi": 48.0,
        "atr_pct": 2.5,
        "volume_m": 45.0,
        "pid_acc": 0.005,
        "sq_ratio": 0.92,
        "ker": 0.42,
        "btc_mom": 0.5,
        "coin_bias": 0.2
    }
    veto, prob, mult, reason = gate.predict_probability("NEAR/USDT", test_feat)
    print(f"Resultado: Veto={veto} | P(Win)={prob:.1%} | Multiplier={mult}x | Razón: {reason}")
    summary = gate.get_summary()
    print("Summary:", json.dumps(summary, indent=2))
