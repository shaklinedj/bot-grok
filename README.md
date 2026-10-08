# 🤖 Binance Spot Quantitative Trading Bot v11

Sistema institucional de trading algorítmico y cuantitativo en tiempo real para **Binance Spot** con **Malla Neutral Dinámica**, **Comité Multi-Agente con IA (NVIDIA NIM)** y **Dashboard Reactivo SPA**.

---

## ⚡ Características Principales

1. **🕸️ Malla Neutral Cuantitativa (Pionex-Style Adaptive Grid):**
   * Despliegue de órdenes límite simétricas centradas en el precio vivo.
   * **Supervisor Dinámico Adaptativo:** Monitorea la actividad de los escalones y comprime o expande el paso según la volatilidad del activo para forzar alta velocidad de rotación.
   * **Trailing Dinámico de Tendencia:** Si el precio rompe el rango con volumen sostenido, la malla recicla el capital y se desplaza automáticamente para no quedarse fuera del canal.

2. **🧠 Comité Multi-Agente con Inteligencia Artificial (NVIDIA NIM):**
   * Deliberación continua de agentes especializados (Arquitecto de Mallas, Centinela de Noticias, Auditor Forense de Operaciones y Meta-Model Machine Learning).
   * Integración con Llama 3.2 vía NVIDIA NIM API para análisis de sentimiento en tiempo real.

3. **📊 Dashboard SPA Reactivo en Tiempo Real:**
   * Cockpit visual servido localmente en `http://localhost:8888`.
   * **Resumen Global Macro de la Malla (Pionex-Style):** Visualización del capital comprometido, ganancia neta cosechada (Grid Profit), ROI acumulado, conteo de rebotes cerrados (100% Win Rate) y ganancia promedio por escalón.
   * **Medidor Interactivo de Rango (Range Meter):** Indicador visual en vivo de la posición del precio dentro del canal entre el piso y el techo.
   * Modal detallado con el historial de ejecuciones, balance de fees y comisiones.

4. **🛡️ Gestión Defensiva de Riesgo:**
   * Veto estricto anti-cresta (prohibido comprar en techos de ola).
   * Control de drawdown y balance libre protegido para reciclaje de liquidez.

---

## 🚀 Requisitos e Instalación

### 1. Clonar el repositorio
```bash
git clone https://github.com/shaklinedj/bot-grok.git
cd bot-grok
```

### 2. Instalar dependencias
```bash
pip install -r requirements.txt
# o instalar paquetes base:
pip install requests python-dotenv
```

### 3. Configurar variables de entorno
Copia la plantilla de ejemplo y configura tu API Key de NVIDIA:
```bash
cp .env.example .env
```
Edita `.env` y añade tu clave:
```env
NVIDIA_API_KEY=tu_clave_de_nvidia_nim_aqui
```

---

## 🎯 Ejecución

Para iniciar el bot en modo Paper Trading con el Dashboard en vivo:
```bash
python paper_trading_agent.py
```
Abre tu navegador en:
```
http://localhost:8888
```

---

## 📁 Estructura del Proyecto

* `paper_trading_agent.py`: Núcleo de ejecución cuantitativa, motor de la malla y servidor HTTP.
* `dashboard_spa.py`: Interfaz gráfica reactiva (HTML5 / Tailwind CSS / Vanilla JS).
* `agent_committee.py`: Deliberación multi-agente cuantitativa.
* `ai_auditor.py`: Auditor forense de operaciones con IA.
* `news_sentinel.py`: Centinela de noticias y análisis de sentimiento con NVIDIA NIM.
* `macro_radar.py`: Escáner de condiciones de mercado y régimen de volatilidad.
* `meta_labeling.py`: Filtrado de entradas mediante Machine Learning.
