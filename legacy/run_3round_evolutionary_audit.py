import os
import sys
import json
import time
import requests
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv()

API_KEY = os.environ.get("NVIDIA_API_KEY")
URL = "https://integrate.api.nvidia.com/v1/chat/completions"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

# 3 Rondas con IAs validadas
MODEL_R1 = "google/diffusiongemma-26b-a4b-it"                     # Ronda 1: Auditoría Estructural & Microestructura
MODEL_R2 = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"        # Ronda 2: Ataque Adversarial & Stress-Testing
MODEL_R3 = "google/diffusiongemma-26b-a4b-it"                     # Ronda 3: Consenso Final & Certificación Anti-Overfitting

def read_file_snippet(path, max_lines=75):
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return "".join([f.readline() for _ in range(max_lines)])

code_risk = read_file_snippet("risk/adaptive.py", 70)
code_grid = read_file_snippet("grid/bounded_grid.py", 70)
code_carry = read_file_snippet("cash_carry_sim.py", 70)
code_buda = read_file_snippet("buda_market_maker_sim.py", 70)
code_swing = read_file_snippet("engine/swing_bot.py", 70)

context_code = f"""
=== 1. MOTOR ADAPTATIVO & RIESGO GEN 15 (risk/adaptive.py) ===
{code_risk}

=== 2. MALLAS ACOTADAS REVERSIÓN A LA MEDIA (grid/bounded_grid.py) ===
{code_grid}

=== 3. PILAR CASH & CARRY DELTA-NEUTRAL (cash_carry_sim.py) ===
{code_carry}

=== 4. PILAR BUDA WALL-BOUNCE MARKET MAKER (buda_market_maker_sim.py) ===
{code_buda}

=== 5. PILAR SWING SNIPER FUERZA RELATIVA & SATÉLITES (engine/swing_bot.py) ===
{code_swing}
"""

def query_nvidia(model_id, system_msg, user_msg, max_tokens=1800, temperature=0.2):
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ],
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    for attempt in range(3):
        try:
            res = requests.post(URL, headers=HEADERS, json=payload, timeout=90)
            if res.status_code == 200:
                data = res.json()
                msg = data["choices"][0]["message"]
                content = msg.get("content")
                if content and str(content).strip():
                    return str(content).strip()
                reasoning = msg.get("reasoning_content")
                if reasoning and str(reasoning).strip():
                    return str(reasoning).strip()
                return "Respuesta vacía recibida del modelo."
            else:
                print(f"[Intento {attempt+1}] Error {res.status_code}: {res.text[:150]}")
                time.sleep(3)
        except Exception as e:
            print(f"[Intento {attempt+1}] Excepción: {e}")
            time.sleep(3)
    return "Error al contactar con el modelo tras 3 intentos."

print("="*80)
print("INICIANDO AUDITORÍA EVOLUTIVA DE 3 RONDAS CON IA DE NVIDIA (ANTI-OVERFITTING)")
print("="*80)

# -------------------------------------------------------------
# RONDA 1: AUDITORÍA ARQUITECTÓNICA Y BÚSQUEDA DE SOBREAJUSTE
# -------------------------------------------------------------
print(f"\n[RONDA 1/3] Ejecutando con {MODEL_R1}...")
sys_r1 = """Eres un Auditor Cuantitativo Principal de Hedge Fund e Ingeniero de Microestructura.
Analiza el código del sistema de trading multi-estrategia (Swing Fuerza Relativa, Mallas Acotadas, Cash & Carry y Buda Market Maker).
Tu foco principal es:
1. Puntos fuertes del edge matemático real.
2. Detección de posibles vulnerabilidades o sesgos de sobreajuste (overfitting sintético) en los parámetros (ATR multipliers, stops, thresholds, filtros).
3. Fricciones de microestructura en el mundo real (spreads L2, deslizamiento, comisiones cambiantes).
Sé riguroso, directo y técnico."""

prompt_r1 = f"""Audita el código actual del sistema:

{context_code}

Entrega tu diagnóstico estructurado destacando qué componentes son matemáticamente sólidos y dónde detectas posibles riesgos de sobreajuste o fragilidad."""

res_r1 = query_nvidia(MODEL_R1, sys_r1, prompt_r1, max_tokens=1500, temperature=0.25)
print("\n--- RESULTADO RONDA 1 COMPLETADO ---")
print(res_r1[:300] + "...\n")

# -------------------------------------------------------------
# RONDA 2: ABOGADO DEL DIABLO ADVERSARIAL Y PRUEBA DE ESTRÉS
# -------------------------------------------------------------
print(f"\n[RONDA 2/3] Ejecutando con {MODEL_R2} (Reasoning Engine)...")
sys_r2 = """Eres un Gestor de Riesgo Adversarial ('Abogado del Diablo') y Cuantitativo de Derivados.
Tu trabajo es DESAFIAR y poner a prueba los hallazgos de la Ronda 1.
No seas complaciente. Somete el sistema a 3 escenarios de choque extremo en cripto:
1. Choque de Correlación y Desplome de Liquidez (Flash crash de BTC con apertura violenta de spreads y fallos de stop).
2. Régimen de Compresión Prolongada y Funding Negativo (Impacto en Cash & Carry y sobreoperación de mallas).
3. Falso Muro de Liquidez en Buda (Spoofing o retiro súbito de los muros de $240k USDT antes del fill).
Evalúa si los parámetros de la Gen 15 (Target ATR 4.2x, Stop ATR 1.25x, BE trigger 1.5%, Trail distance 1.9x ATR) están sobreajustados a simulaciones ideales o si son genuinamente robustos."""

prompt_r2 = f"""Aquí tienes los hallazgos de la Ronda 1:

{res_r1}

Desafía críticamente estos puntos. Aplica el análisis de choque y determina qué salvaguardas evitan que el bot sufra un draw-down destructivo en el mercado real sin sobreajustar."""

res_r2 = query_nvidia(MODEL_R2, sys_r2, prompt_r2, max_tokens=1600, temperature=0.2)
print("\n--- RESULTADO RONDA 2 COMPLETADO ---")
print(res_r2[:300] + "...\n")

# -------------------------------------------------------------
# RONDA 3: CONSENSO FINAL, OPTIMIZACIÓN NO-SOBREAJUSTADA Y CERTIFICACIÓN
# -------------------------------------------------------------
print(f"\n[RONDA 3/3] Ejecutando con {MODEL_R3} (Síntesis y Consenso Institucional)...")
sys_r3 = """Eres el Chief Investment Officer (CIO) y Director de Modelado Cuantitativo.
Tu misión es sintetizar la Auditoría Arquitectónica (Ronda 1) y el Ataque Adversarial de Riesgo (Ronda 2) para emitir el veredicto definitivo.
Debes dictar:
1. Calibración Óptima Anti-Overfitting de los parámetros clave (Target ATR, Stop ATR, BE Trigger, Trailing Distance, Step-TP, Hurdle rates).
2. Reglas de Invariancia: Qué condiciones deben cumplirse para garantizar que el sistema opere en su máximo nivel de eficiencia estadística sin depender de curvas sobreajustadas.
3. Veredicto Final y Calificación Institucional (1 a 10) en:
   - Robustez Anti-Drawdown
   - Solidez Matemática
   - Realismo de Microestructura (Fee/Slippage)
   - Resistencia a Overfitting."""

prompt_r3 = f"""Sintetiza y emite el dictamen final a partir de las dos rondas previas:

=== RONDA 1 (AUDITORÍA ARQUITECTÓNICA & MICROESTRUCTURA) ===
{res_r1}

=== RONDA 2 (ATAQUE ADVERSARIAL Y PRUEBA DE ESTRÉS) ===
{res_r2}

Emite el consenso final, tabla de parámetros certificados y veredicto definitivo."""

res_r3 = query_nvidia(MODEL_R3, sys_r3, prompt_r3, max_tokens=1800, temperature=0.2)
print("\n--- RESULTADO RONDA 3 COMPLETADO ---")
print(res_r3[:300] + "...\n")

# Guardar informe consolidado
audit_data = {
    "round_1": {
        "model": MODEL_R1,
        "title": "Auditoría Arquitectónica y Detección de Fricciones",
        "output": res_r1
    },
    "round_2": {
        "model": MODEL_R2,
        "title": "Ataque Adversarial, Prueba de Estrés y Anti-Overfitting",
        "output": res_r2
    },
    "round_3": {
        "model": MODEL_R3,
        "title": "Consenso de Parámetros, Certificación Institucional y Veredicto",
        "output": res_r3
    }
}

with open("audit_3rounds_nvidia_results.json", "w", encoding="utf-8") as f:
    json.dump(audit_data, f, ensure_ascii=False, indent=2)

print("="*80)
print("AUDITORÍA DE 3 RONDAS COMPLETADA EXITOSAMENTE Y GUARDADA EN 'audit_3rounds_nvidia_results.json'")
print("="*80)
