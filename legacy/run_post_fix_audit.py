import os
import sys
import requests
import json
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

MODELS = [
    {
        "id": "google/diffusiongemma-26b-a4b-it",
        "name": "Google Gemma 26B Instruct",
        "focus": "Arquitectura, Anti-Overfitting y Robustez"
    },
    {
        "id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        "name": "NVIDIA Nemotron 30B Reasoning",
        "focus": "Verificación Matemática de Riesgo y No-Sobreajuste"
    }
]

def read_file_clean(path, max_lines=75):
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return "".join([f.readline() for _ in range(max_lines)])

code_context = f"""
=== 1. MOTOR ADAPTATIVO POST-FIX (risk/adaptive.py) ===
{read_file_clean("risk/adaptive.py", 70)}

=== 2. MALLAS ACOTADAS CON GATING DE VOLATILIDAD (grid/bounded_grid.py) ===
{read_file_clean("grid/bounded_grid.py", 70)}

=== 3. ROTARY CASH & CARRY CON FILTRO ANTI-CHURNING (cash_carry_sim.py) ===
{read_file_clean("cash_carry_sim.py", 70)}

=== 4. BUDA MARKET MAKER SPREAD HARVESTER (buda_market_maker_sim.py) ===
{read_file_clean("buda_market_maker_sim.py", 70)}
"""

results = {}

for m in MODELS:
    print(f"\n>>> Consultando segunda auditoría a {m['name']} ({m['id']})...")
    prompt = f"""Eres un Auditor Cuantitativo Senior de Hedge Fund e Inspector de Riesgo.
Se aplicaron correcciones críticas al sistema:
1. Se añadió un suelo mínimo a la tasa de aprendizaje (min_lr=0.04) para evitar la parálisis por aprendizaje.
2. Se introdujo un Volatility Gating Ratio (canal <= 3.5x ATR y descarte de velas con caída > -1.6%) en las mallas para evitar colapsos.
3. Se implementó una barrera de fricción (Anti-Churning) en Cash & Carry que exige 2.5x comisiones antes de rotar.
4. Se blindó la base de datos con SQLite WAL y busy_timeout=5000.

Evalúa esta versión corregida y responde:
1. EVALUACIÓN DE LAS CORRECCIONES: ¿Resuelven con éxito las vulnerabilidades anteriores sin caer en sobreajuste (over-fitting)?
2. VEREDICTO DE CONDICIÓN OPERATIVA: ¿El sistema está ahora en condiciones óptimas para operar de forma sustentable?
3. NIVEL DE ROBUSTEZ FINAL: Calificación de 1 a 10 y justificación matemática breve.
Sé conciso, técnico y honesto."""
    
    payload = {
        "model": m["id"],
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": code_context}
        ],
        "max_tokens": 800,
        "temperature": 0.2
    }
    
    try:
        r = requests.post(URL, headers=HEADERS, json=payload, timeout=45)
        if r.status_code == 200:
            content = r.json()["choices"][0]["message"]["content"]
            results[m["name"]] = content
            print(f"[OK] Auditoria completada por {m['name']}")
        else:
            print(f"[ERROR] Error {r.status_code} en {m['name']}: {r.text[:120]}")
    except Exception as e:
        print(f"[WARN] Excepcion en {m['name']}: {e}")

with open("post_fix_audit_results.json", "w", encoding="utf-8") as out_f:
    json.dump(results, out_f, indent=2, ensure_ascii=False)

print("\nSegunda auditoria completada. Resultados guardados en post_fix_audit_results.json")
