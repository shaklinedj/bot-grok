"""
ai_auditor.py — Auditor Cuantitativo Activo, Revisor Forense y Memoria Adaptativa (NVIDIA NIM)
Analiza trades cerrados con IA, mantiene el Libro Mayor de Memoria Persistente (system_memory.json)
y posee la potestad activa de AFINAR PARÁMETROS en el cerebro del bot (sl_atr_mult, min_score, cooldowms).
"""

import os
import sys
import io
import json
import time
import threading
from typing import Dict, List, Optional, Callable
import requests

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv

load_dotenv()
DEFAULT_NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
NVIDIA_NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL_NAME = "meta/llama-3.2-11b-vision-instruct"

LOG_DIR = os.path.join(os.path.dirname(__file__), "paper_logs")
AI_AUDIT_LOG_FILE = os.path.join(LOG_DIR, "ai_trade_audits.json")
SYSTEM_MEMORY_FILE = os.path.join(LOG_DIR, "system_memory.json")


class NvidiaTradeAuditor:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("NVIDIA_API_KEY", DEFAULT_NVIDIA_API_KEY)
        self.audits: List[Dict] = []
        self.system_memory: Dict = {
            "version": "2.0",
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "coin_lessons": {},
            "tuning_history": [],
            "regime_insights": []
        }
        self.tuning_handler: Optional[Callable] = None
        
        self.load_audits()
        self.load_memory()

    def register_tuning_handler(self, handler: Callable):
        """Registra la función del bot que aplica cambios de parámetros en tiempo de ejecución."""
        self.tuning_handler = handler

    def load_audits(self):
        if os.path.exists(AI_AUDIT_LOG_FILE):
            try:
                with open(AI_AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
                    self.audits = json.load(f)
            except Exception:
                self.audits = []

    def save_audits(self):
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            with open(AI_AUDIT_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.audits[-25:], f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"  [Error Guardar Auditorías IA] {e}", flush=True)

    def load_memory(self):
        if os.path.exists(SYSTEM_MEMORY_FILE):
            try:
                with open(SYSTEM_MEMORY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.system_memory = data
            except Exception:
                pass

    def save_memory(self):
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            self.system_memory["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(SYSTEM_MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.system_memory, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"  [Error Guardar Memoria] {e}", flush=True)

    def audit_closed_trade(self, trade_data: Dict) -> Dict:
        """
        Envía el trade a NVIDIA NIM para diagnóstico forense y ajuste de parámetros activo.
        """
        sym = trade_data.get("symbol", "UNKNOWN")
        side = trade_data.get("side", "long").upper()
        pnl = float(trade_data.get("net_pnl", trade_data.get("pnl", 0.0)))
        entry_p = float(trade_data.get("entry_price", 0.0))
        exit_p = float(trade_data.get("exit_price", trade_data.get("price", 0.0)))
        hold_min = float(trade_data.get("hold_min", 0.0))
        exit_reason = trade_data.get("exit_reason", trade_data.get("strategy", "Cierre"))
        score = trade_data.get("entry_score", "N/A")
        is_win = pnl > 0

        # Prevención estricta de análisis duplicados
        trade_sig = f"{sym}_{entry_p:.5f}_{exit_p:.5f}_{pnl:.4f}"
        for existing in self.audits:
            ex_sig = f"{existing.get('symbol')}_{existing.get('entry_p', 0):.5f}_{existing.get('exit_p', 0):.5f}_{existing.get('pnl', 0):.4f}"
            if trade_sig == ex_sig:
                return existing

        # Memoria previa sobre este activo para darle contexto al LLM
        coin_mem = self.system_memory.get("coin_lessons", {}).get(sym, {})
        past_losses = coin_mem.get("losses", 0)
        past_wins = coin_mem.get("wins", 0)
        past_lessons = " | ".join(coin_mem.get("lessons", [])) or "Ninguna previa."

        prompt = f"""Eres el Auditor Cuantitativo Senior y Controlador de Riesgo Activo de un Fondo Algorítmico Cripto.
Tu misión es hacer la autopsia forense de un trade cerrado y DECIDIR si se deben ajustar parámetros operativos para no repetir errores.

Expediente del Trade:
- Activo: {sym} ({side})
- Resultado: {'GANANCIA' if is_win else 'PÉRDIDA'} (${pnl:+.4f} USDT)
- Entrada: ${entry_p:.5f} -> Salida: ${exit_p:.5f}
- Duración en posición: {hold_min:.1f} minutos
- Causa de salida: {exit_reason}
- Score inicial del algoritmo: {score}
- Memoria histórica de {sym}: {past_wins}W / {past_losses}L. Lecciones anteriores: {past_lessons}

Responde ÚNICAMENTE en JSON con este esquema estricto:
{{
  "diagnostico_forense": "explicación concisa en 2 oraciones de qué ocurrió con la física del trade y por qué se ganó o perdió",
  "calidad_decision": "EXCELENTE | ACEPTABLE | DEFICIENTE | MEJORABLE",
  "puntaje_calidad": 8,
  "leccion_cuantitativa": "lección clave que el sistema debe recordar para {sym}",
  "ajuste_parametro": {{
    "accion": "AUMENTAR_SL_ATR | AUMENTAR_MIN_SCORE | DISMINUIR_TP1 | COOLDOWN_MONEDA | MANTENER",
    "parametro": "sl_atr_mult | min_score_required | tp1_gain_pct | cooldown",
    "nuevo_valor": 2.40,
    "justificacion": "motivo técnico del ajuste"
  }}
}}
"""

        payload = {
            "model": MODEL_NAME,
            "messages": [
                {"role": "system", "content": "Eres un auditor cuantitativo senior. Responde estrictamente formato JSON sin markdown."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 500
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        try:
            r = requests.post(NVIDIA_NIM_URL, json=payload, headers=headers, timeout=40)
            if r.status_code == 200:
                raw = r.json()["choices"][0]["message"]["content"].strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                raw = raw.strip()
                parsed = json.loads(raw)

                audit_record = {
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "symbol": sym,
                    "side": side,
                    "pnl": round(pnl, 4),
                    "is_win": is_win,
                    "entry_p": entry_p,
                    "exit_p": exit_p,
                    "exit_reason": exit_reason,
                    "diagnostico": parsed.get("diagnostico_forense", "Sin diagnóstico."),
                    "calidad": parsed.get("calidad_decision", "EVALUADO"),
                    "puntaje": parsed.get("puntaje_calidad", 7),
                    "leccion": parsed.get("leccion_cuantitativa", "Mantener disciplina algorítmica."),
                    "ajuste_sugerido": parsed.get("ajuste_parametro", {})
                }
                
                self.audits.append(audit_record)
                self.save_audits()

                # Actualizar Memoria del Sistema para esta moneda
                if sym not in self.system_memory["coin_lessons"]:
                    self.system_memory["coin_lessons"][sym] = {"wins": 0, "losses": 0, "lessons": []}
                if is_win:
                    self.system_memory["coin_lessons"][sym]["wins"] += 1
                else:
                    self.system_memory["coin_lessons"][sym]["losses"] += 1
                
                new_lesson = audit_record["leccion"]
                if new_lesson and new_lesson not in self.system_memory["coin_lessons"][sym]["lessons"]:
                    self.system_memory["coin_lessons"][sym]["lessons"].append(new_lesson)
                    self.system_memory["coin_lessons"][sym]["lessons"] = self.system_memory["coin_lessons"][sym]["lessons"][-3:]

                # APLICAR AJUSTE DE PARÁMETROS ACTIVO SI PROCEDE
                param_adjustment = parsed.get("ajuste_parametro", {})
                accion = str(param_adjustment.get("accion", "")).upper()
                if accion and accion != "MANTENER" and self.tuning_handler:
                    try:
                        self.tuning_handler(param_adjustment, audit_record)
                    except Exception as ex_t:
                        print(f"  [Error Aplicando Ajuste de Auditor] {ex_t}", flush=True)

                self.save_memory()
                print(f"  [AUDITORÍA IA NVIDIA] {sym} ({'WIN' if is_win else 'LOSS'}): {audit_record['diagnostico']}", flush=True)
                return audit_record
            else:
                print(f"  [Error API Auditoría] HTTP {r.status_code}", flush=True)
        except Exception as e:
            print(f"  [Error Auditoría IA] {e}", flush=True)

        return {}

    def audit_async(self, trade_data: Dict):
        """Ejecuta la auditoría en un hilo en segundo plano para jamás pausar los ticks."""
        t = threading.Thread(target=self.audit_closed_trade, args=(trade_data,), daemon=True)
        t.start()


# Instancia singleton
ai_auditor = NvidiaTradeAuditor()


if __name__ == "__main__":
    print("Probando Auditor IA Activo y Memoria del Sistema...")
    sample_trade = {
        "symbol": "MOVE/USDT",
        "side": "long",
        "pnl": -0.6676,
        "entry_price": 0.0105,
        "exit_price": 0.010121,
        "hold_min": 13.0,
        "exit_reason": "Stop Loss Inicial Ceñido",
        "entry_score": 68.0
    }
    res = ai_auditor.audit_closed_trade(sample_trade)
    print("Memoria Actualizada:")
    print(json.dumps(ai_auditor.system_memory, indent=2, ensure_ascii=False))
