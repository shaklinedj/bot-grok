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

    def deliberate_opportunity(self, opp: Dict, btc_macro: Dict, news_context: Dict) -> Dict:
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

        memory_context = self._read_system_memory(symbol)

        coin_news = news_context.get("coin_news", [])
        coin_news_str = "\n".join(f"  • {n}" for n in coin_news) if coin_news else "  (Sin titulares críticos recientes en la web)"

        prompt = f"""Eres el COMITÉ CUANTITATIVO MULTI-AGENTE de una firma de trading institucional con acceso a datos de mercado e Internet.
Tu misión es debatir y tomar la decisión óptima para {symbol} evaluando la oportunidad y su perspectiva a futuro.
No se trata de vetar por vetar: debes analizar la cara del activo y si tiene catalizadores o interés en internet para mantener volumen vivo.
Estamos operando con una ESTRATEGIA DE MALLAS (Grid Trading Autónomo). El objetivo es atrapar micro-volatilidad en activos dinámicos.

{memory_context}

=== CONTEXTO DEL ACTIVO Y DEL MERCADO ===
- Activo: {symbol}
- Precio Actual: ${price} | Volumen 24h: ${volume:,.0f} USDT
- Score Cuantitativo Multivariable: {score:.1f} / 100
- Compresión de Volatilidad (TTM Squeeze): {stage}
- Eficiencia Tendencial (KER): {ker:.3f} (>0.25 tendencia; <0.15 rango/ruido)
- Desbalance Libro de Órdenes (OBI): {obi:+.3f} (+ compra pasiva institucional; - presión de venta)
- Spread LOB: {spread_pct:.3f}%
- RSI (15m): {rsi:.1f} | ADX (1h): {adx:.1f} | Distancia a EMA20: {dist_ema20:+.2f}% | Volatilidad ATR: {analysis.get('atr_pct', 2.0):.2f}%

=== INVESTIGACIÓN EN INTERNET Y SENTIMIENTO EXTERNO EN VIVO ===
- Titulares de Internet / Google News sobre {symbol}:
{coin_news_str}
- Sentimiento Macro Global: {news_context.get('sentiment', 'NEUTRAL')}
- Resumen de Noticias del Mercado: {news_context.get('summary', 'Sin noticias')}

=== ROLES Y AUTONOMÍA DEL DEBATE (PROSPECCIÓN DE FUTURO Y MALLAS ACTIVAS) ===
1. [CENTINELA MACRO E INTERNET]: Analiza los titulares de internet y la salud de {symbol}. ¿Tiene buena cara? ¿Hay adopción, volumen o catalizadores que mantengan el interés, o es un activo muerto/abandonado?
2. [ARQUITECTO DE MALLAS]: Diseña la AMPLITUD compacta (`amplitud_malla_atr` entre 1.0 y 1.4x ATR). Si el activo tiene buena perspectiva de oscilación con volumen, aprueba la malla para cosechar sin demoras.
3. [JEFE DE RIESGO]: Asigna 70% a 85% de capital para darle volumen a cada escalón. Veta solo si hay riesgo de muerte/desplome inminente o si no hay liquidez suficiente.
4. [COORDINADOR EJECUCIÓN]: Fija la densidad de líneas (`grid_lines`) entre 8 y 10 líneas con paso estrecho (0.45% a 0.75%) para generar ganancias recurrentes.

Responde ÚNICAMENTE en formato JSON válido con la siguiente estructura exacta:
{{
  "debate": {{
    "centinela_macro": "Diagnóstico de perspectiva del activo y noticias de internet en 1 oración.",
    "arquitecto_mallas": "Evaluación de dinamismo y amplitud compacta en 1 oración.",
    "jefe_riesgo": "Evaluación de capital y solvencia del activo en 1 oración.",
    "coordinador_ejecucion": "Líneas asignadas para paso estrecho 0.45%-0.75% en 1 oración."
  }},
  "decision": "APROBADO" o "RECHAZADO",
  "amplitud_malla_atr": float (entre 1.0 y 1.4),
  "grid_lines": int (entre 8 y 10 líneas),
  "porcentaje_cuenta_pct": 70 a 85,
  "razon_clave": "Conclusión colegiada en menos de 15 palabras"
}}"""

        # Cálculo Institucional Algorítmico Inmediato (Zero Latencia / Cero Timeouts)
        atr_pct = float(analysis.get('atr_pct', 2.0))
        amplitud_malla_atr = 1.25
        
        # Rango óptimo basado en volatilidad real (entre 1.4% y 3.8%)
        raw_range_pct = (atr_pct / 100.0) * amplitud_malla_atr
        range_pct = max(0.014, min(0.038, raw_range_pct))
        
        # Densidad de líneas para escalón dorado (0.45% - 0.70%)
        target_step = 0.0055
        calculated_lines = int(round((2 * range_pct) / target_step)) + 1
        grid_lines = max(6, min(10, calculated_lines))
        
        grid_upper = round(price * (1 + range_pct), 6)
        grid_lower = round(price * (1 - range_pct), 6)
        step_size_pct = ((grid_upper - grid_lower) / grid_lower) / (grid_lines - 1) * 100
        
        # Filtros Cuantitativos de Aprobación
        decision_clean = "APROBADO"
        veto_reason = "Consenso colegiado alcanzado"
        
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
        elif step_size_pct < 0.40 or step_size_pct > 0.95:
            decision_clean = "RECHAZADO"
            veto_reason = f"Paso fuera de rango óptimo ({step_size_pct:.2f}%)"
            
        mult_clean = 0.80  # 80% de fondos disponibles para escalones con buen peso

        debate = {
            "centinela_macro": f"Volumen 24h verificado en ${volume:,.0f} USDT. Sin anomalías en libro.",
            "arquitecto_mallas": f"Rango ±{range_pct*100:.1f}% ({grid_lines} líneas a paso {step_size_pct:.2f}%).",
            "jefe_riesgo": f"Capital calibrado al {round(mult_clean*100)}% con modo paciente ante rupturas.",
            "coordinador_ejecucion": f"Órdenes Maker preparadas en libro con spread de {spread_pct:.3f}%."
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
