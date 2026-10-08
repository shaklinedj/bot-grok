"""
news_sentinel.py — Centinela de Noticias y Catalizadores con IA de NVIDIA (NIM)
Monitorea feeds de noticias en tiempo real (CoinTelegraph, CoinDesk, Binance Announcements),
realiza inferencia cuantitativa mediante Llama-3.2 Vision en NVIDIA NIM,
y genera un escudo anti-cisne negro (Black-Swan Veto) para proteger el capital.
"""

import os
import time
import json
import threading
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List, Set
import requests
from dotenv import load_dotenv

load_dotenv()
DEFAULT_NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
NVIDIA_NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL_NAME = "meta/llama-3.2-11b-vision-instruct"

SENTIMENT_STATE_FILE = os.path.join(os.path.dirname(__file__), "paper_logs", "news_sentiment.json")


class NvidiaNewsSentinel:
    def __init__(self, api_key: str = None, poll_interval_sec: int = 600):
        self.api_key = api_key or os.environ.get("NVIDIA_API_KEY", DEFAULT_NVIDIA_API_KEY)
        self.poll_interval = poll_interval_sec
        self.last_update_ts = 0.0
        self.is_running = False
        
        # Estado en memoria
        self.blacklisted_symbols: Set[str] = set()
        self.market_sentiment: str = "NEUTRAL"
        self.summary_text: str = "Centinela de noticias activo en espera del primer escaneo."
        self.recent_alerts: List[Dict] = []
        self.last_error: str = ""
        
        self.load_state()

    def load_state(self):
        if os.path.exists(SENTIMENT_STATE_FILE):
            try:
                with open(SENTIMENT_STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.blacklisted_symbols = set(data.get("blacklisted_symbols", []))
                    self.market_sentiment = data.get("market_sentiment", "NEUTRAL")
                    self.summary_text = data.get("summary_text", "")
                    self.recent_alerts = data.get("recent_alerts", [])
                    self.last_update_ts = data.get("last_update_ts", 0.0)
            except Exception:
                pass

    def save_state(self):
        try:
            os.makedirs(os.path.dirname(SENTIMENT_STATE_FILE), exist_ok=True)
            payload = {
                "last_update": time.strftime("%Y-%m-%d %H:%M:%S"),
                "last_update_ts": self.last_update_ts,
                "market_sentiment": self.market_sentiment,
                "summary_text": self.summary_text,
                "blacklisted_symbols": list(self.blacklisted_symbols),
                "recent_alerts": self.recent_alerts[:10],
                "model": MODEL_NAME,
                "status": "ONLINE" if not self.last_error else f"ERROR: {self.last_error}"
            }
            with open(SENTIMENT_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"  [Error Guardar Estado Noticias] {e}", flush=True)

    def fetch_coin_news(self, symbol: str) -> List[str]:
        """Modo rápido: retorna sin realizar peticiones de red síncronas bloqueantes."""
        return []

    def fetch_latest_headlines(self) -> List[str]:
        """Extrae los titulares más recientes de CoinTelegraph RSS."""
        rss_urls = [
            "https://cointelegraph.com/rss",
            "https://www.coindesk.com/arc/outboundfeeds/rss/"
        ]
        headlines = []
        for url in rss_urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                with urllib.request.urlopen(req, timeout=6) as resp:
                    tree = ET.fromstring(resp.read())
                    for item in tree.findall(".//item")[:5]:
                        t_el = item.find("title")
                        if t_el is not None and t_el.text:
                            clean_t = t_el.text.strip()
                            if clean_t and clean_t not in headlines:
                                headlines.append(clean_t)
                if len(headlines) >= 4:
                    break
            except Exception:
                continue
        return headlines[:4]

    def analyze_headlines(self, headlines: List[str]) -> bool:
        """Envía los titulares a la API de NVIDIA NIM para clasificación de riesgo y veto."""
        if not headlines:
            return False

        prompt = f"""Eres el Centinela Cuantitativo de Noticias de un Bot de Trading de Criptomonedas Institucional.
Tu misión es proteger el capital identificando hackeos, exploits, demandas regulatorias, deslistados o eventos bajistas que justifiquen un VETO DE COMPRA.

Titulares recientes de última hora:
""" + "\n".join(f"- {h}" for h in headlines) + """

Responde ÚNICAMENTE un objeto JSON válido con este formato:
{
  "sentimiento_macro": "ALCISTA | BAJISTA | CAUTELA | NEUTRAL",
  "resumen_general": "resumen en 1 oración del impacto en el mercado",
  "alertas": [
    {
      "titular": "texto del titular",
      "activo": "SÍMBOLO (ej: NEAR, BTC, SOL) o 'GENERAL'",
      "riesgo": "CRITICO_VETO | ALTO | MEDIO | BAJO",
      "accion": "VETO_COMPRA | NEUTRAL | ALCISTA",
      "razon": "explicación concisa en español"
    }
  ]
}
"""

        payload = {
            "model": MODEL_NAME,
            "messages": [
                {"role": "system", "content": "Eres un analista de riesgo cripto. Responde ÚNICAMENTE JSON estricto sin markdown."},
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
            if r.status_code != 200:
                self.last_error = f"HTTP {r.status_code}: {r.text[:100]}"
                return False

            raw_text = r.json()["choices"][0]["message"]["content"].strip()
            # Limpiar posibles bloques markdown ```json ... ```
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
            raw_text = raw_text.strip()

            parsed = json.loads(raw_text)
            self.market_sentiment = parsed.get("sentimiento_macro", "NEUTRAL")
            self.summary_text = parsed.get("resumen_general", "Análisis completado.")
            
            alerts = parsed.get("alertas", [])
            new_blacklist = set()
            for al in alerts:
                act = str(al.get("activo", "")).upper().strip()
                risk = str(al.get("riesgo", "")).upper()
                action = str(al.get("accion", "")).upper()

                if act and act != "GENERAL":
                    if risk in ["CRITICO_VETO", "ALTO"] or "VETO" in action:
                        pair = f"{act}/USDT"
                        new_blacklist.add(pair)
                        print(f"  🚨 [VETO NOTICIAS NVIDIA] {pair} VETADO por riesgo '{risk}': {al.get('razon')}", flush=True)

            self.blacklisted_symbols = new_blacklist
            # Deduplicar alertas por titular para evitar tarjetas repetidas en el dashboard
            seen_titles = set()
            combined_alerts = []
            for al in alerts + self.recent_alerts:
                t_clean = str(al.get("titular", "")).strip().lower()
                if t_clean and t_clean not in seen_titles:
                    seen_titles.add(t_clean)
                    combined_alerts.append(al)

            self.recent_alerts = combined_alerts[:8]
            self.last_update_ts = time.time()
            self.last_error = ""
            self.save_state()
            return True

        except Exception as e:
            self.last_error = str(e)
            print(f"  [Error Inferencia NVIDIA NIM] {e}", flush=True)
            return False

    def scan_once(self):
        """Ejecuta una ronda de escaneo y análisis."""
        headlines = self.fetch_latest_headlines()
        if headlines:
            self.analyze_headlines(headlines)

    def is_symbol_blacklisted(self, symbol: str) -> tuple[bool, str]:
        """Comprueba si un símbolo tiene veto activo por noticias."""
        clean_sym = symbol.upper()
        if clean_sym in self.blacklisted_symbols:
            # Buscar razón
            base = clean_sym.split("/")[0]
            for al in self.recent_alerts:
                if str(al.get("activo", "")).upper() == base:
                    return True, al.get("razon", "Veto activo por noticias críticas.")
            return True, "Veto activo por riesgo detectado en noticias."
        return False, ""

    def start_background_worker(self):
        """Modo rápido: sin hilos de scraping en segundo plano."""
        self.is_running = False


# Instancia singleton para uso en el bot
news_sentinel = NvidiaNewsSentinel()


if __name__ == "__main__":
    print("Iniciando prueba manual del Centinela de Noticias NVIDIA NIM...")
    s = NvidiaNewsSentinel()
    s.scan_once()
    print("Sentimiento:", s.market_sentiment)
    print("Resumen:", s.summary_text)
    print("Blacklist:", s.blacklisted_symbols)
    print("Alertas:", len(s.recent_alerts))
