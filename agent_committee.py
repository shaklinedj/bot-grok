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

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.35,
            "max_tokens": 700
        }

        # Fallback de máxima seguridad (FAIL-SAFE)
        verdict_fallback = {
            "symbol": symbol,
            "timestamp": time.strftime("%H:%M:%S"),
            "decision": "RECHAZADO",
            "grid_upper": 0.0,
            "grid_lower": 0.0,
            "grid_lines": 0,
            "multiplicador_capital": 0.0,
            "debate": {
                "centinela_macro": "Filtro de seguridad activado por desconexión temporal de IA.",
                "arquitecto_mallas": "Sin diseño de malla por fallo de telemetría.",
                "jefe_riesgo": "VETO PREVENTIVO: Prohibido operar a ciegas.",
                "coordinador_ejecucion": "Orden en pausa."
            },
            "razon_clave": "Filtro preventivo de seguridad"
        }

        try:
            resp = requests.post(NVIDIA_NIM_URL, headers=headers, json=payload, timeout=35)
            if resp.status_code == 200:
                raw_txt = resp.json()["choices"][0]["message"]["content"].strip()
                # Extraer bloque JSON con delimitadores o buscando llaves
                if "```json" in raw_txt:
                    raw_txt = raw_txt.split("```json")[1].split("```")[0].strip()
                elif "```" in raw_txt:
                    raw_txt = raw_txt.split("```")[1].split("```")[0].strip()
                else:
                    start_idx = raw_txt.find('{')
                    end_idx = raw_txt.rfind('}')
                    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                        raw_txt = raw_txt[start_idx:end_idx+1].strip()

                parsed = json.loads(raw_txt)
                decision_val = str(parsed.get("decision", "RECHAZADO")).strip().upper()
                if "APROB" in decision_val:
                    decision_clean = "APROBADO"
                else:
                    decision_clean = "RECHAZADO"

                amplitud_malla_atr = float(parsed.get("amplitud_malla_atr", 2.0))
                grid_lines = int(parsed.get("grid_lines", 0))
                
                # Calcular matemáticamente el grid exacto basado en el ATR real de la moneda
                atr_pct = analysis.get('atr_pct', 2.0)
                range_pct = (atr_pct / 100.0) * amplitud_malla_atr
                
                grid_upper = price * (1 + range_pct)
                grid_lower = price * (1 - range_pct)

                # Validación de seguridad de la malla
                if decision_clean == "APROBADO":
                    if grid_lines < 2:
                        decision_clean = "RECHAZADO"
                        parsed["razon_clave"] = "Líneas < 2"
                    else:
                        step_size_pct = ((grid_upper - grid_lower) / grid_lower) / (grid_lines - 1) * 100
                        if step_size_pct < 0.40:
                            decision_clean = "RECHAZADO"
                            parsed["razon_clave"] = f"Paso microscópico ({step_size_pct:.2f}%) riesgo de fees"
                        elif step_size_pct > 0.95:
                            decision_clean = "RECHAZADO"
                            parsed["razon_clave"] = f"Paso muy holgado ({step_size_pct:.2f}%) demasiado lento"
                        

                # Porcentaje de la cuenta decidido por los agentes (25% a 95%)
                pct_raw = parsed.get("porcentaje_cuenta_pct", None)
                if pct_raw is not None:
                    try:
                        pct_val = float(str(pct_raw).replace("%", "").strip())
                        mult_clean = max(0.25, min(0.95, pct_val / 100.0))
                    except Exception:
                        mult_clean = 0.50
                else:
                    mult_clean = max(0.25, min(0.95, float(parsed.get("multiplicador_capital", 0.50))))

                verdict = {
                    "symbol": symbol,
                    "timestamp": time.strftime("%H:%M:%S"),
                    "decision": decision_clean,
                    "grid_upper": grid_upper,
                    "grid_lower": grid_lower,
                    "grid_lines": grid_lines,
                    "multiplicador_capital": round(mult_clean, 2),
                    "porcentaje_cuenta_pct": round(mult_clean * 100, 1),
                    "debate": parsed.get("debate", verdict_fallback["debate"]),
                    "razon_clave": parsed.get("razon_clave", "Consenso colegiado alcanzado")
                }
            else:
                print(f"⚠️ [NIM IA ERROR HTTP {resp.status_code}] {resp.text[:120]}", flush=True)
                verdict = verdict_fallback
        except Exception as e:
            print(f"⚠️ [NIM IA EXCEPTION] {type(e).__name__}: {e}", flush=True)
            verdict = verdict_fallback

        with self.cache_lock:
            self.deliberations.append(verdict)
            self.deliberations = self.deliberations[-20:]
            self.save_deliberations()

        return verdict


# Instancia Global
agent_committee = QuantitativeAgentCommittee()
