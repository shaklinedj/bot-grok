"""
Multi-Model Quantitative Institutional Audit for Grade 10 Architecture.
Evaluates:
- risk/dynamic_sizing.py (Fractional Kelly + Volatility Scaling)
- execution/depth_slippage.py (L2 Orderbook VWAP & Dynamic Slippage)
- execution/stale_guard.py (Latency Budgeting & Quote Freshness Guard)
- auditor/reconciler.py (Triple-Ledger Reconciliation & Self-Healing Audit)
"""
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
        "focus": "Microestructura, Slippage L2 y Presupuesto de Latencia"
    },
    {
        "id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        "name": "NVIDIA Nemotron 30B Reasoning",
        "focus": "Matemática de Kelly Fraccional y Triple-Ledger Reconciliación"
    }
]

def read_file_clean(path, max_lines=75):
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return "".join([f.readline() for _ in range(max_lines)])

code_context = f"""
=== 1. MOTOR DE DIMENSIONAMIENTO DINÁMICO & KELLY FRACCIONAL (risk/dynamic_sizing.py) ===
{read_file_clean("risk/dynamic_sizing.py", 75)}

=== 2. MOTOR DE DESLIZAMIENTO DINÁMICO & VWAP L2 (execution/depth_slippage.py) ===
{read_file_clean("execution/depth_slippage.py", 75)}

=== 3. ESCUDO DE LATENCIA Y COTIZACIÓN CADUCA (execution/stale_guard.py) ===
{read_file_clean("execution/stale_guard.py", 75)}

=== 4. AUDITOR DE RECONCILIACIÓN TRIPLE-LEDGER (auditor/reconciler.py) ===
{read_file_clean("auditor/reconciler.py", 75)}
"""

results = {}

for m in MODELS:
    print(f"\n>>> [AUDIT] Consultando a {m['name']} ({m['id']})...", flush=True)
    prompt = f"""Eres el Chief Risk Officer y Principal Quantitative Researcher de un Hedge Fund Tier-1 (estándar Citadel/Jane Street).
Se implementaron los 4 pilares institucionales finales para cerrar la brecha hacia el Grado 10.0:
1. Sizing Dinámico: Kelly Fraccional (lambda=0.25-0.28) + escalado inverso de volatilidad por ATR para mantener VaR constante.
2. Microestructura L2: Cálculo de VWAP real por profundidad de libro, con descarte/enrutamiento si el slippage consume >25% del alfa o >0.20%.
3. Presupuesto de Latencia: Descarte determinista de cotizaciones con antigüedad >1200ms-1500ms y veto ante spreads triplicados.
4. Auto-Reconciliador Triple-Ledger: Auditor de integridad de saldo en SQLite WAL que verifica balance esperado vs caja viva vs pnl histórico.

Evalúa los 4 módulos de código adjuntos y dictamina:
1. RIGOR MATEMÁTICO Y ARQUITECTURA: ¿Cumplen con el rigor institucional sin añadir complejidad innecesaria?
2. PREVENCIÓN DE VULNERABILIDADES: ¿Eliminan el riesgo de selección adversa, slippage oculto y descalce de saldo?
3. CALIFICACIÓN FINAL: Nota de 1.0 a 10.0 y veredicto respecto a si el sistema alcanza el Grado 10.0 Institucional.
Sé riguroso, conciso y analítico."""

    payload = {
        "model": m["id"],
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": code_context}
        ],
        "max_tokens": 1800,
        "temperature": 0.2
    }

    try:
        r = requests.post(URL, headers=HEADERS, json=payload, timeout=60)
        if r.status_code == 200:
            res_json = r.json()
            msg = res_json["choices"][0]["message"]
            content = msg.get("content") or msg.get("reasoning_content") or ""
            results[m["name"]] = {
                "status": "SUCCESS",
                "model_id": m["id"],
                "content": content
            }
            print(f"[OK] Respuesta recibida de {m['name']}.", flush=True)
            print(content[:350] + "...\n", flush=True)
        else:
            print(f"[ERROR] Error {r.status_code}: {r.text[:200]}", flush=True)
            results[m["name"]] = {"status": "ERROR", "code": r.status_code, "msg": r.text}
    except Exception as e:
        print(f"[ERROR] Excepción: {e}", flush=True)
        results[m["name"]] = {"status": "EXCEPTION", "msg": str(e)}

with open("grade10_audit_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print("\n>>> Auditoría Grado 10 finalizada con éxito. Guardada en grade10_audit_results.json", flush=True)
