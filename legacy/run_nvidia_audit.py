import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("NVIDIA_API_KEY")
URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL = "google/diffusiongemma-26b-a4b-it"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# Leer extractos clave del sistema actual
def read_snippet(path, max_lines=80):
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = [f.readline() for _ in range(max_lines)]
        return "".join(lines)

risk_code = read_snippet("risk/adaptive.py", 70)
grid_code = read_snippet("grid/bounded_grid.py", 70)
carry_code = read_snippet("cash_carry_sim.py", 70)
buda_code = read_snippet("buda_market_maker_sim.py", 70)

system_prompt = """Eres un Auditor Cuantitativo Senior de Hedge Fund e Ingeniero de Software de Alta Frecuencia.
Tu tarea es auditar este sistema multi-estrategia (Swing Sniper con Ruptura 15m, Bounded Grid con Hurst, Cash & Carry rotativo Binance, y Buda Market Maker).
Entrega una auditoría estructurada con:
1. Puntos Fuertes Cuantitativos (Edge estadístico).
2. Riesgos Críticos Ocultos (Adverse selection, fricción de comisiones, drawdown).
3. 3 Mejoras Concretas y Prioritarias para maximizar ganancia y estabilidad.
Sé conciso, técnico y directo al grano."""

user_content = f"""Revisa estos módulos clave del bot:

=== 1. MOTOR DE AUTOAPRENDIZAJE Y COHORTES (risk/adaptive.py) ===
{risk_code}

=== 2. MALLAS ACOTADAS DE REVERSIÓN A LA MEDIA (grid/bounded_grid.py) ===
{grid_code}

=== 3. ROTARY CASH & CARRY DELTA-NEUTRAL (cash_carry_sim.py) ===
{carry_code}

=== 4. BUDA MARKET MAKER SPREAD HARVESTER (buda_market_maker_sim.py) ===
{buda_code}
"""

payload = {
    "model": MODEL,
    "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ],
    "max_tokens": 1200,
    "temperature": 0.3
}

print(f"Enviando código del bot al modelo {MODEL} en NVIDIA NIM...")
try:
    res = requests.post(URL, headers=headers, json=payload, timeout=60)
    if res.status_code == 200:
        data = res.json()
        print("\n" + "="*80)
        print("AUDITORÍA DE ARQUITECTURA COMPLETADA EXITOSAMENTE (NVIDIA NIM):")
        print("="*80 + "\n")
        print(data["choices"][0]["message"]["content"])
    else:
        print("Error en llamada:", res.status_code, res.text)
except Exception as e:
    print("Excepción:", e)
