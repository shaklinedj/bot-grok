import traceback
import requests
import json
from agent_committee import agent_committee, NVIDIA_NIM_URL, MODEL_NAME

opp = {
    'symbol': 'DOGE/USDT',
    'price': 0.095,
    'volume': 85000000,
    'score': 68.0,
    'stage': 'TRANSITION',
    'ker': 0.24,
    'obi': -0.05,
    'spread_pct': 0.01,
    'analysis': {'rsi_15m': 48.0, 'adx_1h': 26.5, 'dist_ema20': -0.15, 'macro_bias': 'BULLISH', 'features': {'rsi': 48.0, 'adx': 26.5, 'dist_ema20': -0.15}}
}
btc_macro = {'summary': 'BULLISH'}
news_context = {'sentiment': 'NEUTRAL', 'summary': 'Normal'}

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

memory_context = agent_committee._read_system_memory(symbol)

prompt = f"""Eres el COMITÉ CUANTITATIVO MULTI-AGENTE de una firma de trading cripto institucional.
Debes simular un debate colegiado rápido y riguroso entre 4 roles especializados para evaluar {symbol}.
NUNCA utilices respuestas prefabricadas. La decisión de operar o vetar, la dirección y el tipo de orden la toma EXCLUSIVAMENTE este comité.

{memory_context}

=== ESTADO ACTUAL DEL MERCADO Y DEL ACTIVO ===
- Activo: {symbol}
- Precio Actual: ${price} | Volumen 24h: ${volume:,.0f} USDT
- Score Arsenal Cuantitativo: {score:.1f} / 100
- Compresión de Volatilidad (TTM Squeeze): {stage}
- Eficiencia Kaufman (KER): {ker:.3f} (KER > 0.25 = tendencia definida; KER < 0.15 = ruido/lateral)
- Desbalance Libro de Órdenes (OBI): {obi:+.3f} (Positivo = Muro de compra; Negativo = Muro de venta)
- Spread Libro de Órdenes: {spread_pct:.3f}%
- RSI (15m): {rsi:.1f} | ADX (1h): {adx:.1f} | Distancia a EMA20: {dist_ema20:+.2f}%
- Régimen Macro BTC: {btc_macro.get('summary', 'Normal')} | Sesgo 4h: {analysis.get('macro_bias', 'NEUTRAL')}
- Sentimiento Noticias (Centinela): {news_context.get('sentiment', 'NEUTRAL')} | Resumen: {news_context.get('summary', 'Sin eventos críticos')}

=== ROLES QUE DEBEN DEBATIR ===
1. [CENTINELA MACRO]: Evalúa noticias y correlación con BTC.
2. [ANALISTA TÉCNICO]: Evalúa Squeeze, OBI, KER, RSI y propone si conviene LONG o SHORT o NEUTRAL.
3. [JEFE DE RIESGO]: Actúa como Abogado del Diablo. Aplica la memoria y reglas aprendidas del sistema. Decide si VETA (RECHAZADO) o APRUEBA.
4. [FRANCOTIRADOR EJECUCIÓN]: Si se aprueba, decide la TÁCTICA de orden: Selecciona OBLIGATORIAMENTE BREAKOUT_MARKET si el Score >= 60, hay impulso alcista/bajista o compresión lista para romper (garantiza entrada inmediata sin perder el trade); selecciona MAKER_LIMIT en el mejor bid solo si el mercado está en rango lateral sin tendencia; o ESPERAR_RETESTEO si está sobre-extendido.

Responde ÚNICAMENTE en formato JSON válido con la siguiente estructura exacta:
{{
  "debate": {{
    "centinela_macro": "Diagnóstico macro y de noticias en 1 oración.",
    "analista_tecnico": "Tesis técnica y dirección propuesta en 1 oración.",
    "jefe_riesgo": "Crítica de riesgo, memoria del sistema y si veta o no en 1 oración.",
    "jefe_ejecucion": "Justificación de táctica de entrada y tamaño en 1 oración."
  }},
  "decision": "APROBADO" o "RECHAZADO",
  "direccion": "LONG" o "SHORT" o "NEUTRAL",
  "tactica": "MAKER_LIMIT" o "BREAKOUT_MARKET" o "ESPERAR_RETESTEO",
  "multiplicador_capital": 0.2 a 1.0,
  "razon_clave": "Motivo concluyente del comité en menos de 15 palabras"
}}"""

headers = {
    "Authorization": f"Bearer {agent_committee.api_key}",
    "Content-Type": "application/json"
}
payload = {
    "model": MODEL_NAME,
    "messages": [{"role": "user", "content": prompt}],
    "temperature": 0.2,
    "max_tokens": 450
}

try:
    print("Calling NVIDIA...")
    resp = requests.post(NVIDIA_NIM_URL, headers=headers, json=payload, timeout=22)
    print("HTTP STATUS:", resp.status_code)
    print("RAW TEXT:\n", resp.text)
    raw_txt = resp.json()["choices"][0]["message"]["content"].strip()
    if "```json" in raw_txt:
        raw_txt = raw_txt.split("```json")[1].split("```")[0].strip()
    elif "```" in raw_txt:
        raw_txt = raw_txt.split("```")[1].split("```")[0].strip()
    parsed = json.loads(raw_txt)
    print("PARSED SUCCESS:\n", json.dumps(parsed, indent=2))
except Exception as e:
    traceback.print_exc()
