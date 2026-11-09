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
        "focus": "Arquitectura de Software y Lógica Cuantitativa"
    },
    {
        "id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        "name": "NVIDIA Nemotron 30B Reasoning",
        "focus": "Gestión de Riesgo Matemático y Fragilidad"
    },
    {
        "id": "minimaxai/minimax-m3.1-flash",
        "name": "MiniMax M3.1 Flash",
        "focus": "Fricción de Comisiones, Latencia y Microestructura"
    }
]

def read_file_clean(path, max_lines=75):
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return "".join([f.readline() for _ in range(max_lines)])

code_context = f"""
=== 1. MOTOR ADAPTATIVO & COHORTES (risk/adaptive.py) ===
{read_file_clean("risk/adaptive.py", 65)}

=== 2. MALLAS ACOTADAS DE REVERSIÓN A LA MEDIA (grid/bounded_grid.py) ===
{read_file_clean("grid/bounded_grid.py", 65)}

=== 3. ROTARY CASH & CARRY DELTA-NEUTRAL (cash_carry_sim.py) ===
{read_file_clean("cash_carry_sim.py", 65)}

=== 4. BUDA MARKET MAKER SPREAD HARVESTER (buda_market_maker_sim.py) ===
{read_file_clean("buda_market_maker_sim.py", 65)}
"""

results = {}

for m in MODELS:
    print(f"\n>>> [1/3] Consultando a {m['name']} ({m['id']})...")
    prompt = f"""Eres un Auditor Cuantitativo de Élite enfocado en {m['focus']}.
Examina este sistema de trading algorítmico multi-estrategia y responde de forma estrictamente estructurada:
1. DIAGNÓSTICO CRÍTICO: 2 fallos o debilidades ocultas más importantes en tu área de especialidad.
2. MEJORA SUSTENTABLE REQUERIDA: 2 cambios concretos y accionables para blindar la rentabilidad a largo plazo.
Sé conciso, técnico y directo."""
    
    payload = {
        "model": m["id"],
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": code_context}
        ],
        "max_tokens": 700,
        "temperature": 0.2
    }
    
    try:
        r = requests.post(URL, headers=HEADERS, json=payload, timeout=45)
        if r.status_code == 200:
            content = r.json()["choices"][0]["message"]["content"]
            results[m["name"]] = content
            print(f"[OK] Respuesta recibida de {m['name']}")
        else:
            print(f"[ERROR] Error {r.status_code} en {m['name']}: {r.text[:120]}")
    except Exception as e:
        print(f"[WARN] Excepcion en {m['name']}: {e}")

with open("multi_model_audit_results.json", "w", encoding="utf-8") as out_f:
    json.dump(results, out_f, indent=2, ensure_ascii=False)

print("\nAudit multi-modelo completada. Resultados guardados en multi_model_audit_results.json")
