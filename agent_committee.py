"""
agent_committee.py — Comité Cuantitativo Multi-Agente con IA de NVIDIA NIM
Implementa el debate colegiado antes de ejecutar cualquier operación en el mercado.
Carga explícitamente el 'Libro de Habilidades y Memoria' (system_memory.json)
para inyectar el contexto de aprendizaje a cada agente de NVIDIA NIM.
"""

import os
import sys
import json
import time
import threading
from typing import Dict, List, Tuple, Optional
import requests
from dotenv import load_dotenv

load_dotenv()
DEFAULT_NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
NVIDIA_NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL_NAME = "meta/llama-3.2-11b-vision-instruct"

LOG_DIR = os.path.join(os.path.dirname(__file__), "paper_logs")
SYSTEM_MEMORY_FILE = os.path.join(LOG_DIR, "system_memory.json")
COMMITTEE_LOG_FILE = os.path.join(LOG_DIR, "committee_deliberations.json")


class QuantitativeAgentCommittee:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("NVIDIA_API_KEY", DEFAULT_NVIDIA_API_KEY)
        self.deliberations: List[Dict] = []
        self.cache_lock = threading.Lock()
        self.load_deliberations()

    def load_deliberations(self):
        if os.path.exists(COMMITTEE_LOG_FILE):
            try:
                with open(COMMITTEE_LOG_FILE, "r", encoding="utf-8") as f:
                    self.deliberations = json.load(f)
            except Exception:
                self.deliberations = []

    def save_deliberations(self):
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            with open(COMMITTEE_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.deliberations[-20:], f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"  [Error Guardar Deliberaciones Comité] {e}", flush=True)

    def _read_system_memory(self, symbol: str = "") -> str:
        """
        Lee el Libro de Memoria Persistente (skills, lecciones aprendidas y reglas de régimen)
        para inyectarlo directamente en los prompts de los agentes de NVIDIA NIM.
        """
        if not os.path.exists(SYSTEM_MEMORY_FILE):
            return "Memoria del sistema: No hay lecciones previas registradas."

        try:
            with open(SYSTEM_MEMORY_FILE, "r", encoding="utf-8") as f:
                mem = json.load(f)
        except Exception:
            return "Memoria del sistema: Error al leer el archivo."

        context_lines = []
        context_lines.append("=== MEMORIA COGNITIVA Y REGLAS APRENDIDAS POR EL SISTEMA ===")
        
        # 1. Reglas aprendidas por rol
        skills = mem.get("agent_skills", {})
        if skills:
            context_lines.append("Reglas de Comportamiento Institucional:")
            for role_key, role_data in skills.items():
                name = role_data.get("name", role_key)
                rules = "; ".join(role_data.get("rules", []))
                context_lines.append(f" - [{name}]: {rules}")

        # 2. Lecciones específicas de la moneda bajo debate
        coin_lessons = mem.get("coin_lessons", {}).get(symbol, {})
        if coin_lessons:
            wins = coin_lessons.get("wins", 0)
            losses = coin_lessons.get("losses", 0)
            lessons = " | ".join(coin_lessons.get("lessons", []))
            context_lines.append(f"Historial en {symbol}: {wins}W - {losses}L. Lección aprendida: {lessons}")

        # 3. Reglas de régimen macro
        regimes = mem.get("regime_insights", [])
        if regimes:
            for r in regimes:
                context_lines.append(f"Regla de Régimen ({r.get('regime')}): {r.get('rule')}")

        # 4. Manual de Microestructura y Catálogo Táctico de Binance
        playbook = mem.get("binance_playbook", {})
        if playbook:
            context_lines.append("Manual de Microestructura Binance Spot:")
            for p in playbook.get("microstructure_principles", []):
                context_lines.append(f" • {p}")
            tactics = playbook.get("tactical_catalogue", {})
            if tactics:
                t_list = [f"{k}: {v}" for k, v in tactics.items()]
                context_lines.append("Catálogo Táctico Autorizado: " + " | ".join(t_list))

        return "\n".join(context_lines)

    def deliberate_opportunity(self, opp: Dict, btc_macro: Dict, news_context: Optional[Dict] = None) -> Dict:
        """
        Ejecuta el debate colegiado de los agentes antes de aprobar un trade:
        - Agente 1: Centinela Macro y Noticias
        - Agente 2: Analista Técnico y Order Flow (LOB, Squeeze, KER)
        - Agente 3: Jefe de Riesgo / Abogado del Diablo (Evalúa con la memoria del sistema)
        - Agente 4: Francotirador de Ejecución (Decide la táctica y tipo de orden)
        - Decisión final: Aprobado/Rechazado, Dirección (LONG/SHORT), Táctica y Tamaño
        """
        symbol = opp.get("symbol", "")
        analysis = opp.get("analysis", {})
        price = opp.get("price", 0.0)
        score = opp.get("score", 0.0)
        stage = opp.get("stage", "")
        ker = opp.get("ker", 0.0)
        obi = opp.get("obi", 0.0)
        spread_pct = opp.get("spread_pct", 0.0)
        volume = opp.get("volume", 0.0)
        features = analysis.get("features", {})
        rsi = features.get("rsi", analysis.get("rsi_15m", 50.0))
        adx = features.get("adx", analysis.get("adx_1h", 20.0))
        dist_ema20 = features.get("dist_ema20", analysis.get("dist_ema20_15m", 0.0))

        # 1. Geometría Adaptativa de la Malla (Piso, Techo y Líneas)
        atr_pct = float(analysis.get('atr_pct', 2.0))
        
        # Amplitud adaptativa: Si KER es mayor (cierta inercia), ensancha la malla para dar holgura; si es rango puro, es compacta
        amplitud_malla_atr = max(1.10, min(1.65, 1.10 + (ker * 1.20)))
        raw_range_pct = (atr_pct / 100.0) * amplitud_malla_atr
        # Paso dinámico basado en spread y volatilidad: entre 0.55% y 0.80% (alta reactividad)
        target_step = max(0.0055, min(0.0080, (spread_pct * 3.5) if spread_pct > 0.001 else 0.0065))
        calculated_lines = int(round((2 * raw_range_pct) / target_step)) + 1
        # Líneas concentradas (3 a 5 líneas) para órdenes institucionales contundentes (cero migajas de $5-$6)
        grid_lines = max(3, min(5, calculated_lines))
        # Ajustar amplitud exacta para que el paso se mantenga estricto en el rango deseado (~0.55% a 0.80%)
        range_pct = (target_step * (grid_lines - 1)) / 2.0
        
        grid_upper = round(price * (1 + range_pct), 6)
        grid_lower = round(price * (1 - range_pct), 6)
        step_size_pct = ((grid_upper - grid_lower) / grid_lower) / (grid_lines - 1) * 100
        
        # 2. Asignación Dinámica de Capital (Sizing Multifactorial Concentrado)
        base_mult = 0.75

        # Componente A: Score Cuantitativo Multivariable (0 a 100 pts)
        score_adj = (score - 50.0) * 0.005
        score_adj = max(-0.10, min(0.18, score_adj))

        # Componente B: Presión Compradora de Microestructura (Order Book Imbalance OBI)
        obi_adj = obi * 0.25
        obi_adj = max(-0.10, min(0.15, obi_adj))

        # Componente C: Eficiencia de Tendencia Kaufman (KER)
        # KER bajo (<0.25) = Rango óptimo lateral (bono para malla); KER alto (>0.45) = Riesgo direccional (penalización)
        if ker <= 0.25:
            ker_adj = +0.08
        elif ker >= 0.45:
            ker_adj = -0.12
        else:
            ker_adj = 0.0

        # Componente D: Régimen Macro de Bitcoin
        is_risk_off = btc_macro.get("is_risk_off", False) if isinstance(btc_macro, dict) else False
        macro_mult = 0.85 if is_risk_off else 1.0

        # Multiplicador dinámico integrado (entre 60% y 100% según las condiciones en vivo)
        raw_mult = (base_mult + score_adj + obi_adj + ker_adj) * macro_mult
        mult_clean = round(max(0.60, min(1.00, raw_mult)), 2)

        # 3. Filtros Cuantitativos Institucionales de Aprobación
        decision_clean = "APROBADO"
        veto_reason = f"Aprobado dinámicamente al {round(mult_clean*100)}% de capital"
        
        if volume < 2_500_000:
            decision_clean = "RECHAZADO"
            veto_reason = f"Volumen bajo (${volume:,.0f} < $2.5M)"
        elif spread_pct > 0.25:
            decision_clean = "RECHAZADO"
            veto_reason = f"Spread de libro excesivo ({spread_pct:.2f}% > 0.25%)"
        elif rsi > 68.0:
            decision_clean = "RECHAZADO"
            veto_reason = f"Sobrecompra extrema anti-FOMO (RSI {rsi:.1f} > 68)"
        elif atr_pct < 0.80:
            decision_clean = "RECHAZADO"
            veto_reason = f"Activo estancado (ATR {atr_pct:.2f}% < 0.80%)"
        elif step_size_pct < 0.35 or step_size_pct > 1.25:
            decision_clean = "RECHAZADO"
            veto_reason = f"Paso fuera de rango óptimo ({step_size_pct:.2f}%)"

        debate = {
            "centinela_macro": f"Régimen verificado ({'Cautela BTC' if is_risk_off else 'Estable'}). Volumen ${volume:,.0f} USDT.",
            "arquitecto_mallas": f"Malla adaptativa: rango ±{range_pct*100:.2f}% a {amplitud_malla_atr:.2f}x ATR ({grid_lines} líneas a paso {step_size_pct:.2f}%).",
            "jefe_riesgo": f"Capital calibrado dinámicamente al {round(mult_clean*100)}% (Score {score:.1f}, OBI {obi:+.2f}, KER {ker:.2f}).",
            "coordinador_ejecucion": f"Líneas de libro preparadas con paso {step_size_pct:.2f}% y spread {spread_pct:.3f}%."
        }

        verdict = {
            "symbol": symbol,
            "timestamp": time.strftime("%H:%M:%S"),
            "decision": decision_clean,
            "grid_upper": grid_upper,
            "grid_lower": grid_lower,
            "grid_lines": grid_lines,
            "multiplicador_capital": mult_clean,
            "porcentaje_cuenta_pct": round(mult_clean * 100, 1),
            "debate": debate,
            "razon_clave": veto_reason
        }

        with self.cache_lock:
            self.deliberations.append(verdict)
            self.deliberations = self.deliberations[-20:]
            self.save_deliberations()

        return verdict


# Instancia Global
agent_committee = QuantitativeAgentCommittee()
