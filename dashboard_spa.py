# -*- coding: utf-8 -*-
"""
Dashboard SPA Reactivo de Alto Rendimiento para Paper Trading Bot v11.
Arquitectura Single Page Application (SPA) con streaming dinámico JSON cada 1000ms.
Incluye Cockpit de Control Predictivo PID, Squeeze de Volatilidad, Flujo Concentrado y Curva SVG.
"""

import json
from typing import Optional, Dict

def get_dashboard_spa_html(initial_state: Optional[Dict] = None) -> str:
    preload_tag = f"<script>window.__INITIAL_STATE__ = {json.dumps(initial_state).replace('</', r'<\/')};</script>" if initial_state else ""
    return HTML_TEMPLATE.replace("<!-- PRELOAD_TAG -->", preload_tag)

HTML_TEMPLATE = """<!DOCTYPE html>


<html lang="es" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Binance Spot Paper Trading Bot v11 — Control Predictivo PID & Flujo Concentrado</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            brand: { 500: '#10b981', 600: '#059669' },
            darkbg: '#0b0f19',
            cardbg: '#111827',
            cardborder: '#1f2937'
          }
        }
      }
    }
  </script>
  <style>
    body { background-color: #0b0f19; color: #c9d1d9; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
    .card { background-color: #111827; border: 1px solid #1f2937; border-radius: 12px; }
    .badge-launchpad { background-color: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }
    .badge-coiling { background-color: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); }
    .badge-crest { background-color: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); }
    .badge-runner { background-color: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.4); }
    @keyframes pulse-fast {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.3; }
    }
    .animate-pulse-fast { animation: pulse-fast 1.2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }
  </style>
</head>
<body class="p-3 md:p-6 antialiased">
  <div class="max-w-7xl mx-auto space-y-5">
    
    <!-- Top Header Bar -->
    <div class="card p-4 md:p-5 flex flex-wrap items-center justify-between gap-4 border-l-4 border-l-emerald-500 shadow-xl">
      <div class="flex items-center gap-3.5">
        <div id="conn-dot" class="h-3.5 w-3.5 rounded-full bg-emerald-500 animate-pulse-fast"></div>
        <div>
          <div class="flex items-center gap-2 flex-wrap">
            <h1 class="text-xl md:text-2xl font-black text-white tracking-tight">Binance Spot Grid Bot</h1>
            <span class="text-xs bg-emerald-500/20 text-emerald-400 font-bold px-2.5 py-0.5 rounded-full border border-emerald-500/30">
              ⚡ MALLA DINÁMICA CENTRADA
            </span>
            <span class="text-xs bg-purple-500/20 text-purple-300 font-bold px-2.5 py-0.5 rounded-full border border-purple-500/30">
              🎯 COSECHA CONTINUA EN VIVO
            </span>
          </div>
          <p class="text-xs text-gray-400 mt-1 flex items-center gap-2">
            <span>Escalones Dinámicos 0.45% - 0.70%</span>
            <span>•</span>
            <span>Modo Paciente en Caídas</span>
            <span>•</span>
            <span>Micro-Cosecha Instantánea Maker</span>
          </p>
        </div>
      </div>
      <div class="flex items-center gap-2.5 text-xs font-mono">
        <div class="bg-gray-900/90 px-3 py-1.5 rounded-lg border border-gray-800 text-gray-300 flex items-center gap-2.5">
          <span id="header-cycle" class="text-gray-200">Ciclo #--</span>
          <span>•</span>
          <span id="header-gen" class="text-purple-400 font-bold">Gen #--</span>
          <span>•</span>
          <span id="header-time" class="text-gray-400">--:--:--</span>
          <span>•</span>
          <span id="conn-status" class="text-emerald-400 font-bold">CONECTADO</span>
        </div>
        <button onclick="toggleAllTradesModal()" class="bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-bold px-3 py-1.5 rounded-lg border border-emerald-400/50 shadow-lg flex items-center gap-1.5 transition-all shadow-emerald-500/20">
          <span>📊</span>
          <span id="btn-trades-text">Ver Operaciones</span>
        </button>
        <a href="/office" target="_blank" class="bg-gradient-to-r from-indigo-600 to-cyan-600 hover:from-indigo-500 hover:to-cyan-500 text-white font-bold px-3 py-1.5 rounded-lg border border-indigo-400/40 shadow-lg flex items-center gap-1.5 transition-all">
          <span>🏢</span>
          <span>Oficina Virtual</span>
        </a>
      </div>
    </div>

    <!-- Main Financials Bar (5 KPIs) -->
    <div class="grid grid-cols-2 lg:grid-cols-5 gap-3.5">
      <div class="card p-4 border-t-2 border-t-emerald-500">
        <div class="text-[11px] text-gray-400 uppercase font-bold tracking-wider">Equity Total</div>
        <div class="text-2xl md:text-3xl font-extrabold mt-1 text-white flex items-baseline gap-1">
          <span id="kpi-equity">$0.00</span>
          <span class="text-xs text-gray-500 font-medium">USDT</span>
        </div>
        <div id="kpi-equity-pct" class="text-xs font-semibold mt-1 text-emerald-400">+0.00% (Base: $80.00)</div>
      </div>

      <div class="card p-4 border-t-2 border-t-blue-500">
        <div class="text-[11px] text-gray-400 uppercase font-bold tracking-wider">Efectivo Líquido</div>
        <div class="text-2xl md:text-3xl font-extrabold mt-1 text-emerald-400 flex items-baseline gap-1">
          <span id="kpi-cash">$0.00</span>
          <span class="text-xs text-gray-500 font-medium">USDT</span>
        </div>
        <div id="kpi-cash-detail" class="text-xs text-gray-400 mt-1">Disponible para compras</div>
      </div>

      <div class="card p-4 border-t-2 border-t-indigo-500">
        <div class="text-[11px] text-gray-400 uppercase font-bold tracking-wider">Capital en Malla</div>
        <div class="text-2xl md:text-3xl font-extrabold mt-1 text-white flex items-baseline gap-1">
          <span id="kpi-holdings">$0.00</span>
          <span class="text-xs text-gray-500 font-medium">USDT</span>
        </div>
        <div id="kpi-slots" class="text-xs text-indigo-400 font-medium mt-1">1 Malla Activa Desplegada</div>
      </div>

      <div class="card p-4 border-t-2 border-t-yellow-500">
        <div class="text-[11px] text-gray-400 uppercase font-bold tracking-wider">Cosecha Malla Viva</div>
        <div class="text-2xl md:text-3xl font-extrabold mt-1 font-mono flex items-baseline gap-1">
          <span id="kpi-unrealized-val">$0.0000</span>
          <span class="text-xs text-gray-500 font-medium">USDT</span>
        </div>
        <div id="kpi-unrealized-pct" class="text-xs font-semibold mt-1 text-gray-400">0.00% flotante</div>
      </div>

      <div class="card p-4 border-t-2 border-t-purple-500">
        <div class="text-[11px] text-gray-400 uppercase font-bold tracking-wider">PnL Realizado Total</div>
        <div class="text-2xl md:text-3xl font-extrabold mt-1 font-mono text-emerald-400 flex items-baseline gap-1">
          <span id="kpi-realized-val">+$0.0000</span>
          <span class="text-xs text-gray-500 font-medium">USDT</span>
        </div>
        <div id="kpi-winrate" class="text-xs text-purple-400 font-semibold mt-1">Win Rate: 0% (0W / 0L)</div>
      </div>
    </div>

    <!-- 1. SECCIÓN PRINCIPAL: MALLA CUANTITATIVA ACTIVA EN VIVO -->
    <div class="space-y-3">
      <div class="flex items-center justify-between">
        <h2 class="text-sm uppercase font-black tracking-wider text-purple-400 flex items-center gap-2">
          <span>🕸️</span>
          <span>Malla Cuantitativa Activa (Operación en Tiempo Real)</span>
        </h2>
        <span class="text-xs text-gray-400 font-mono">Supervisor y Cosecha Automática Activos ⚡</span>
      </div>
      <div id="grids-container" class="space-y-4">
        <!-- Inyectado por JS -->
      </div>
    </div>

    <!-- 2. AUDITORÍA PnL POR TRADE / MALLA (Ciclos Completos) -->
    <div class="card p-5 space-y-3 border-l-4 border-l-emerald-500">
      <div class="flex items-center justify-between flex-wrap gap-2">
        <div class="flex items-center gap-2">
          <span>💰</span>
          <h3 class="text-xs uppercase font-black tracking-wider text-emerald-400">Auditoría PnL por Trade (Ciclos Completos de Entrada a Cierre)</h3>
        </div>
        <span class="text-xs text-gray-400 font-mono">Desglose transparente: Resultados netos de cada ciclo</span>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs">
          <thead>
            <tr class="text-gray-400 border-b border-gray-800 font-mono text-[11px]">
              <th class="pb-2.5">HORA CIERRE</th>
              <th class="pb-2.5">PAR</th>
              <th class="pb-2.5">RESULTADO</th>
              <th class="pb-2.5">ENTRADA</th>
              <th class="pb-2.5">SALIDA</th>
              <th class="pb-2.5">PNL NETO</th>
              <th class="pb-2.5">FEE + SLIP</th>
              <th class="pb-2.5">DURACIÓN</th>
              <th class="pb-2.5 text-right">MOTIVO DE SALIDA</th>
            </tr>
          </thead>
          <tbody id="audit-tbody" class="divide-y divide-gray-800/60 font-mono">
            <!-- Filas inyectadas por JS -->
          </tbody>
        </table>
      </div>
    </div>

    <!-- 3. GRÁFICO SVG INTERACTIVO DE CURVA DE EQUITY -->
    <div class="card p-5">
      <div class="flex items-center justify-between mb-3">
        <div class="flex items-center gap-2">
          <span class="text-emerald-400">📈</span>
          <h3 class="text-xs uppercase font-black tracking-wider text-gray-300">Evolución de Equity en Vivo</h3>
        </div>
        <div class="text-xs font-mono text-gray-400 flex items-center gap-3">
          <span>Mín: <strong id="chart-min" class="text-red-400">$0.00</strong></span>
          <span>Máx: <strong id="chart-max" class="text-emerald-400">$0.00</strong></span>
          <span>Actual: <strong id="chart-curr" class="text-white">$0.00</strong></span>
        </div>
      </div>
      <div class="w-full h-36 bg-gray-950/70 rounded-lg p-2 border border-gray-800/80 relative flex items-center">
        <svg id="equity-svg" class="w-full h-full overflow-visible" preserveAspectRatio="none" viewBox="0 0 600 100">
          <defs>
            <linearGradient id="equity-grad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#10b981" stop-opacity="0.35" />
              <stop offset="100%" stop-color="#10b981" stop-opacity="0.0" />
            </linearGradient>
          </defs>
          <path id="svg-area" d="" fill="url(#equity-grad)" />
          <path id="svg-line" d="" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </div>
    </div>

    <!-- 4. RADAR ESCÁNER DE OPORTUNIDADES DEL MERCADO -->
    <div class="card p-5 space-y-3">
      <div class="flex items-center justify-between flex-wrap gap-2">
        <div class="flex items-center gap-2">
          <span>🛰️</span>
          <h3 class="text-xs uppercase font-black tracking-wider text-gray-300">Radar Escáner de Oportunidades (Próximas Rotaciones de Malla)</h3>
        </div>
        <span class="text-xs text-gray-400">Filtro de Liquidez &ge; $15M + Rango Saludable</span>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs">
          <thead>
            <tr class="text-gray-400 border-b border-gray-800 font-mono text-[11px]">
              <th class="pb-2.5">SÍMBOLO</th>
              <th class="pb-2.5">PRECIO ACTUAL</th>
              <th class="pb-2.5">DIRECCIÓN & LÍMITE</th>
              <th class="pb-2.5">SCORE ARSENAL</th>
              <th class="pb-2.5">SESGO MACRO 4H</th>
              <th class="pb-2.5">SQUEEZE TTM</th>
              <th class="pb-2.5">OBV / KER</th>
              <th class="pb-2.5 text-right">VOLUMEN 24H</th>
            </tr>
          </thead>
          <tbody id="scanner-tbody" class="divide-y divide-gray-800/60 font-mono">
            <!-- Filas inyectadas por JS -->
          </tbody>
        </table>
      </div>
    </div>

    <!-- CONTENEDORES LEGACY MANTENIDOS EN OCULTO (Zero Errores de JS) -->
    <div class="hidden" style="display:none;" aria-hidden="true">
      <div id="pid-p-metric"></div>
      <div id="pid-i-metric"></div>
      <div id="pid-d-metric"></div>
      <div id="pid-acc-metric"></div>
      <div id="param-next-trade"></div>
      <div id="param-pct-badge"></div>
      <div id="param-slots"></div>
      <div id="param-tp1-pct"></div>
      <div id="param-min-score"></div>
      <div id="pending-limits-section"></div>
      <div id="pending-limits-container"></div>
      <div id="positions-count-badge"></div>
      <div id="positions-container"></div>
      <div id="btc-regime-badge"></div>
      <div id="macro-btc-price"></div>
      <div id="macro-btc-change"></div>
      <div id="macro-btc-ema50"></div>
      <div id="macro-btc-adx"></div>
      <div id="macro-btc-summary"></div>
      <div id="news-status-badge"></div>
      <div id="news-sentiment-badge"></div>
      <div id="news-update-time"></div>
      <div id="news-veto-count"></div>
      <div id="news-summary-text"></div>
      <div id="news-alerts-container"></div>
      <div id="meta-samples-badge"></div>
      <div id="meta-labeling-container"></div>
      <div id="self-eval-container"></div>
    </div>

    <!-- Cajita de Tendencias & Pulso de Convicción Multi-Agente (Limpio & Compacto) -->
    <div class="card p-4 border-l-4 border-l-indigo-500 bg-gradient-to-r from-gray-900 via-gray-900/90 to-indigo-950/30">
      <div class="flex items-center justify-between flex-wrap gap-3">
        <div class="flex items-center gap-3">
          <div class="h-9 w-9 rounded-lg bg-indigo-500/20 border border-indigo-500/40 flex items-center justify-center text-lg">
            ⚡
          </div>
          <div>
            <div class="text-[10px] text-gray-400 font-bold uppercase tracking-wider">Pulso de Mercado & Agentes IA</div>
            <div id="ai-pulse-summary" class="text-sm font-bold text-white mt-0.5 flex items-center gap-2">
              <span class="inline-block w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
              <span id="ai-pulse-title">Analizando radar dinámico...</span>
            </div>
          </div>
        </div>

        <div class="flex items-center gap-2">
          <div id="ai-pulse-chips" class="flex items-center gap-1.5 flex-wrap font-mono text-[11px]">
            <!-- Inyectado por JS: Moneda líder, sesgo y táctica -->
          </div>
          <button onclick="toggleAiLogsModal()" class="px-3 py-1.5 rounded-lg bg-indigo-600/30 hover:bg-indigo-600/50 border border-indigo-500/40 text-indigo-200 text-xs font-mono font-semibold transition-all flex items-center gap-1.5 shadow-sm">
            <span>📜</span>
            <span>Ver Logs y Auditorías</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Modal / Drawer Emergente Opcional para Logs de Agentes & Auditoría Forense -->
    <div id="ai-logs-modal" class="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm hidden flex items-center justify-center p-4">
      <div class="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-4xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
        <div class="p-4 border-b border-gray-800 flex items-center justify-between bg-gray-950/80">
          <div class="flex items-center gap-2">
            <span class="text-lg">🏛️</span>
            <h3 class="text-sm font-bold text-white uppercase tracking-wider">Historial de Deliberaciones y Auditorías Forenses IA</h3>
          </div>
          <button onclick="toggleAiLogsModal()" class="text-gray-400 hover:text-white text-lg font-mono px-2 py-1 rounded hover:bg-gray-800 transition-colors">✕</button>
        </div>
        
        <div class="p-4 overflow-y-auto space-y-4">
          <!-- Deliberaciones de Comité -->
          <div class="space-y-2">
            <div class="flex items-center justify-between">
              <span class="text-xs font-bold uppercase text-indigo-400 font-mono">Debates del Comité Multi-Agente</span>
              <span class="text-[10px] text-gray-500 font-mono">Últimas deliberaciones registradas</span>
            </div>
            <div id="committee-deliberations-container" class="space-y-2">
              <!-- Inyectado por JS -->
            </div>
          </div>

          <!-- Auditorías Forenses -->
          <div class="space-y-2 pt-3 border-t border-gray-800">
            <div class="flex items-center justify-between">
              <span class="text-xs font-bold uppercase text-cyan-400 font-mono">Auditoría Forense Post-Trade</span>
              <span class="text-[10px] text-gray-500 font-mono">Diagnóstico de trades cerrados</span>
            </div>
            <div id="ai-audits-container" class="space-y-2">
              <!-- Inyectado por JS -->
            </div>
          </div>
        </div>

        <div class="p-3 border-t border-gray-800 bg-gray-950/60 flex justify-end">
          <button onclick="toggleAiLogsModal()" class="px-4 py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-200 rounded text-xs font-mono">Cerrar</button>
        </div>
      </div>
    </div>

    <!-- Modal Emergente Completo: Libro de Todas las Operaciones & Auditoría Financiera -->
    <div id="all-trades-modal" class="fixed inset-0 z-50 bg-black/85 backdrop-blur-md hidden flex items-center justify-center p-3 sm:p-5" style="display: none;">
      <div class="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-5xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden relative">
        <!-- Cabecera del Modal -->
        <div class="p-4 border-b border-gray-800 flex items-center justify-between bg-gray-950/90">
          <div class="flex items-center gap-3">
            <span class="text-2xl">📊</span>
            <div>
              <h3 class="text-base font-black text-white tracking-wide uppercase">Libro Completo de Operaciones & Desglose Financiero</h3>
              <p class="text-xs text-gray-400 font-mono">Registro detallado de cada orden de compra y venta ejecutada por el sistema</p>
            </div>
          </div>
          <button onclick="toggleAllTradesModal()" class="text-gray-400 hover:text-white text-xl font-mono px-3 py-1 rounded-lg hover:bg-gray-800 transition-colors">✕</button>
        </div>

        <!-- Banner de Suma de Ganancias y Pérdidas -->
        <div class="p-4 bg-gray-950/60 border-b border-gray-800/80 grid grid-cols-2 sm:grid-cols-4 gap-3 font-mono text-center">
          <div class="bg-gray-900/80 p-3 rounded-xl border border-emerald-500/30">
            <div class="text-[10px] text-gray-400 uppercase font-bold">Total Ganancias Cosechadas</div>
            <div id="modal-sum-wins" class="text-lg sm:text-xl font-black text-emerald-400 mt-0.5">+$0.00 USDT</div>
            <div id="modal-count-wins" class="text-[10px] text-emerald-500/80">0 operaciones en ganancia</div>
          </div>
          <div class="bg-gray-900/80 p-3 rounded-xl border border-rose-500/30">
            <div class="text-[10px] text-gray-400 uppercase font-bold">Total Pérdidas Registradas</div>
            <div id="modal-sum-losses" class="text-lg sm:text-xl font-black text-rose-400 mt-0.5">-$0.00 USDT</div>
            <div id="modal-count-losses" class="text-[10px] text-rose-500/80">0 operaciones en pérdida</div>
          </div>
          <div class="bg-gray-900/80 p-3 rounded-xl border border-cyan-500/30">
            <div class="text-[10px] text-gray-400 uppercase font-bold">PnL Neto Realizado</div>
            <div id="modal-net-pnl" class="text-lg sm:text-xl font-black text-white mt-0.5">+$0.00 USDT</div>
            <div id="modal-winrate" class="text-[10px] text-cyan-300">Win Rate: 0.0%</div>
          </div>
          <div class="bg-gray-900/80 p-3 rounded-xl border border-purple-500/30">
            <div class="text-[10px] text-gray-400 uppercase font-bold">Comisiones Binance (Fees)</div>
            <div id="modal-total-fees" class="text-lg sm:text-xl font-black text-purple-300 mt-0.5">$0.00 USDT</div>
            <div class="text-[10px] text-gray-500">Tarifa 0.1% Spot</div>
          </div>
        </div>

        <!-- Tabla Completa con Scroll Interno -->
        <div class="p-4 overflow-y-auto flex-1 space-y-2">
          <div class="flex justify-between items-center mb-1">
            <span class="text-xs font-bold uppercase text-gray-400 font-mono">Listado Completo de Operaciones (Ordenadas por Fecha Reciente)</span>
            <span id="modal-total-records-badge" class="text-xs bg-gray-800 text-gray-300 px-2 py-0.5 rounded font-mono">0 operaciones</span>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead>
                <tr class="text-gray-400 border-b border-gray-800 font-mono text-[11px]">
                  <th class="pb-2">HORA</th>
                  <th class="pb-2">PAR</th>
                  <th class="pb-2">ACCIÓN</th>
                  <th class="pb-2">PRECIO</th>
                  <th class="pb-2">CANTIDAD</th>
                  <th class="pb-2">PNL NETO</th>
                  <th class="pb-2">COMISIÓN</th>
                  <th class="pb-2 text-right">ESTRATEGIA / NOTA</th>
                </tr>
              </thead>
              <tbody id="modal-trades-tbody" class="divide-y divide-gray-800/60 font-mono">
                <!-- Inyectado dinámicamente por JS -->
              </tbody>
            </table>
          </div>
        </div>

        <!-- Pie del Modal -->
        <div class="p-3 border-t border-gray-800 bg-gray-950/80 flex items-center justify-between text-xs font-mono text-gray-400">
          <span>Actualizado en tiempo real automáticamente</span>
          <button onclick="toggleAllTradesModal()" class="px-4 py-1.5 bg-gray-800 hover:bg-gray-700 text-white rounded-lg font-bold transition-all">Cerrar</button>
        </div>
      </div>
    </div>

    <!-- Historial Detallado de Operaciones Cerradas / Parciales -->
    <div class="card p-5 space-y-3">
      <div class="flex items-center justify-between flex-wrap gap-2">
        <div class="flex items-center gap-2">
          <span>📋</span>
          <h3 class="text-xs uppercase font-black tracking-wider text-gray-300">Libro de Órdenes & Trades Realizados</h3>
        </div>
        <span class="text-xs text-gray-400 font-mono">Auditoría con Ganancias Netas, Comisiones y Deslizamiento</span>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs">
          <thead>
            <tr class="text-gray-400 border-b border-gray-800 font-mono text-[11px]">
              <th class="pb-2.5">HORA EJECUCIÓN</th>
              <th class="pb-2.5">PAR</th>
              <th class="pb-2.5">ACCIÓN / EVENTO</th>
              <th class="pb-2.5">PRECIO</th>
              <th class="pb-2.5">CANTIDAD</th>
              <th class="pb-2.5">PNL NETO</th>
              <th class="pb-2.5">FEE + SLIP</th>
              <th class="pb-2.5 text-right">DETALLE / MOTIVO</th>
            </tr>
          </thead>
          <tbody id="trades-tbody" class="divide-y divide-gray-800/60 font-mono">
            <!-- Filas inyectadas por JS -->
          </tbody>
        </table>
      </div>
    </div>

  </div>

  <!-- PRELOAD_TAG -->
  <!-- Script Reactivo SPA -->
  <script>


    let pollInterval = 1000;
    let failCount = 0;

    async function fetchState() {
      const endpoints = [
        'http://localhost:8888/api/state',
        'http://127.0.0.1:8888/api/state',
        '/api/state',
        'live_state.json'
      ];

      let res = null;
      for (const ep of endpoints) {
        try {
          res = await fetch(ep, { cache: 'no-store' });
          if (res && res.ok) break;
        } catch (e) {}
      }

      try {
        if (!res || !res.ok) {
          throw new Error('HTTP ' + (res ? res.status : 'No Response'));
        }

        const data = await res.json();
        updateUI(data);

        document.getElementById('conn-dot').className = 'h-3.5 w-3.5 rounded-full bg-emerald-500 animate-pulse-fast';
        document.getElementById('conn-status').innerText = 'CONECTADO EN VIVO';
        document.getElementById('conn-status').className = 'text-emerald-400 font-bold';
        failCount = 0;
      } catch (err) {
        failCount++;
        if (failCount > 3) {
          document.getElementById('conn-dot').className = 'h-3.5 w-3.5 rounded-full bg-amber-500';
          document.getElementById('conn-status').innerText = 'CONECTANDO A :8888...';
          document.getElementById('conn-status').className = 'text-amber-400 font-bold';
        }
      } finally {
        setTimeout(fetchState, pollInterval);
      }
    }


    function updateUI(data) {
      if (!data) return;

      // Header
      document.getElementById('header-cycle').innerText = 'Ciclo #' + (data.cycle || 0);
      document.getElementById('header-gen').innerText = 'Gen #' + (data.generation || 1);
      if (data.timestamp) {
        const timePart = data.timestamp.split('T')[1]?.split('.')[0] || '';
        document.getElementById('header-time').innerText = timePart;
      }

      // KPIs
      const equity = Number(data.equity || 80.0);
      const initCap = Number(data.initial_capital || 80.0);
      const eqPct = ((equity / initCap) - 1) * 100;
      
      const kpiEq = document.getElementById('kpi-equity');
      kpiEq.innerText = '$' + equity.toFixed(2);

      const kpiEqPct = document.getElementById('kpi-equity-pct');
      const sign = eqPct >= 0 ? '+' : '';
      kpiEqPct.innerText = sign + eqPct.toFixed(2) + '% (Base: $' + initCap.toFixed(2) + ')';
      kpiEqPct.className = 'text-xs font-semibold mt-1 ' + (eqPct >= 0 ? 'text-emerald-400' : 'text-rose-400');

      document.getElementById('kpi-cash').innerText = '$' + Number(data.cash || 0).toFixed(2);
      document.getElementById('kpi-holdings').innerText = '$' + Number(data.holdings_val || 0).toFixed(2);

      const posList = data.positions || [];
      const riskPositions = posList.filter(p => !p.tp1_hit);
      const freeRunners = posList.filter(p => p.tp1_hit);
      const pendingCount = (data.pending_limit_orders || []).length;
      const gridCount = (data.grids || []).length;
      document.getElementById('kpi-slots').innerText = gridCount > 0 ? (gridCount + ' Malla Activa Desplegada') : 'Sin mallas activas';
      if (document.getElementById('positions-count-badge')) {
        document.getElementById('positions-count-badge').innerText = gridCount + ' mallas activas';
      }

      // Params - Capital IA Autónomo (dinámico)
      const cashAvail = Number(data.cash || 0);
      document.getElementById('param-next-trade').innerText = '$' + cashAvail.toFixed(2) + ' USDT';
      const lastPct = Number(data.last_agent_pct || 0);
      if (lastPct > 0) {
        document.getElementById('param-pct-badge').innerText = 'IA usó ' + lastPct.toFixed(0) + '% última vez';
      }
      const slotsEl = document.getElementById('param-slots');
      if (slotsEl) slotsEl.innerText = totalOccupied + ' / 3 máx';

      const unrealVal = Number(data.unrealized_pnl || 0);
      const unrealPct = Number(data.unrealized_pct || 0);
      const kpiUnrealVal = document.getElementById('kpi-unrealized-val');
      kpiUnrealVal.innerText = (unrealVal >= 0 ? '+' : '') + unrealVal.toFixed(4);
      kpiUnrealVal.className = 'text-2xl md:text-3xl font-extrabold mt-1 font-mono flex items-baseline gap-1 ' + (unrealVal >= 0 ? 'text-emerald-400' : 'text-rose-400');
      
      const kpiUnrealPct = document.getElementById('kpi-unrealized-pct');
      kpiUnrealPct.innerText = (unrealPct >= 0 ? '+' : '') + unrealPct.toFixed(2) + '% flotante';
      kpiUnrealPct.className = 'text-xs font-semibold mt-1 ' + (unrealPct >= 0 ? 'text-emerald-400' : 'text-rose-400');

      // PnL Realizado
      const realVal = Number(data.realized_pnl || 0);
      const kpiRealVal = document.getElementById('kpi-realized-val');
      kpiRealVal.innerText = (realVal >= 0 ? '+' : '') + realVal.toFixed(4);
      kpiRealVal.className = 'text-2xl md:text-3xl font-extrabold mt-1 font-mono flex items-baseline gap-1 ' + (realVal >= 0 ? 'text-emerald-400' : 'text-rose-400');

      const wr = Number(data.win_rate || 0);
      const wins = data.wins || 0;
      const losses = data.losses || 0;
      document.getElementById('kpi-winrate').innerText = 'Win Rate: ' + wr.toFixed(1) + '% (' + wins + 'W / ' + losses + 'L)';

      // Params dinámicos TP1 y Score
      document.getElementById('param-tp1-pct').innerText = '+' + Number(data.tp1_gain_pct || 1.6).toFixed(2) + '%';
      document.getElementById('param-min-score').innerText = Number(data.min_score || 42.0).toFixed(1) + ' pts';

      // Posiciones Activas
      renderPositions(posList);
      renderGrids(data.grids || [], data);

      // Órdenes Límite Pendientes
      renderPendingLimits(data.pending_limit_orders || []);

      // SVG Equity Curve
      renderChart(data.equity_history || []);

      // Radar Macro 4h/1d
      renderMacroRadar(data.btc_macro || {});

      // Radar Escáner
      renderScanner(data.scanner_opportunities || []);

      // Pulso de Tendencias y Agentes (Cajita Compacta en Vivo)
      renderAiPulse(data);

      // Meta-Labeling Gatekeeper (Centinela Cuantitativo)
      renderMetaLabeling(data.meta_model || {});

      // Auto-evaluación
      renderSelfEval(data.self_eval || {});

      // Auditoría PnL por Trade
      renderPnlAudit(data.pnl_audit || []);

      // Auditor Forense de Trades con IA (NVIDIA NIM) y Memoria Adaptativa
      renderAiAudits(data.ai_audits || [], data.active_parameters || {}, data.system_memory || {});

      // Deliberaciones del Comité Multi-Agente
      renderCommitteeDeliberations(data.committee_deliberations || []);

      // Trades
      renderTrades(data.recent_trades || []);
    }

    
    function renderGrids(grids, data = {}) {
      const container = document.getElementById('grids-container');
      if (!container) return;
      if (!grids || grids.length === 0) {
        container.innerHTML = `
          <div class="col-span-full card p-8 text-center border-dashed border-gray-800">
            <div class="text-3xl mb-2">🕸️</div>
            <div class="text-gray-300 font-bold">Sin Mallas Activas</div>
            <p class="text-xs text-gray-500 mt-1">El Arquitecto IA está buscando volatilidad en rangos.</p>
          </div>
        `;
        return;
      }
      
      let html = '';
      for (const g of grids) {
        const lines = g.lines || [];
        const buys = lines.filter(l => l.side === 'buy' && l.active).sort((a,b) => b.price - a.price); // Descending
        const sells = lines.filter(l => l.side === 'sell' && l.active).sort((a,b) => b.price - a.price); // Descending
        const currentPrice = g.current_price || g.grid_lower;

        // Métricas EXCLUSIVAS de ESTA MALLA ABIERTA (Solo la Operación en Curso)
        const gridProfit = Number(g.realized_pnl) || 0;
        const capTotal = Number(g.capital_total) || 57.43;
        const gridRoiPct = capTotal > 0 ? ((gridProfit / capTotal) * 100) : 0;
        const gridFloating = Number(g.unrealized_pnl) || 0;
        const gridNetProfit = gridProfit + gridFloating;
        const gridNetRoi = capTotal > 0 ? ((gridNetProfit / capTotal) * 100) : 0;
        const gridFills = Number(g.fills_count) || (Number(g.dynamic_adjustments_count) || 0);
        const avgPerFill = gridFills > 0 ? (gridProfit / gridFills) : 0;
        const rangeSpread = Number(g.grid_upper) - Number(g.grid_lower);
        const rangePct = rangeSpread > 0 ? Math.min(100, Math.max(0, ((currentPrice - Number(g.grid_lower)) / rangeSpread) * 100)) : 50;
        const capPerLine = Number(g.capital_per_line) || (capTotal / Math.max(1, (g.grid_lines || 9)));
        const statusMsg = g.status_msg || "Cosechando en Rango Dinámico";
        const tickTime = (data && data.timestamp) ? data.timestamp.split('T')[1]?.split('.')[0] : '';
        
        // Generar filas para la cuadrícula de ventas (Rojas)
        let sellsCards = '';
        for (let i = 0; i < sells.length; i++) {
            const l = sells[i];
            const distPct = ((l.price - currentPrice) / currentPrice * 100).toFixed(2);
            const isNext = (i === sells.length - 1); // Más cercana
            const orderValUsdt = (Number(l.price) * Number(l.amount)).toFixed(2);
            
            sellsCards += `
            <div class="bg-[#131722] p-2.5 rounded-lg border ${isNext ? 'border-rose-500 shadow-md shadow-rose-500/20 bg-rose-950/25 ring-1 ring-rose-500/50' : 'border-gray-800/80 hover:border-gray-700'} flex flex-col justify-between transition-all">
                <div class="flex justify-between items-center text-[10px] mb-1">
                    <span class="text-rose-400 font-black tracking-wider flex items-center gap-1">
                      <span class="w-1.5 h-1.5 rounded-full bg-rose-500"></span>SELL
                    </span>
                    ${isNext ? '<span class="bg-rose-500/30 text-rose-300 px-1.5 py-0.5 rounded text-[8px] font-black animate-pulse border border-rose-500/40">⚡ PRÓXIMA</span>' : ''}
                </div>
                <div class="text-sm font-black text-white font-mono">$${Number(l.price).toFixed(6)}</div>
                <div class="text-[10px] text-gray-400 font-mono mt-1 space-y-0.5 bg-gray-950/40 p-1 rounded">
                    <div class="flex justify-between">
                        <span class="text-gray-500">Monto:</span>
                        <span class="text-emerald-400 font-bold">$${orderValUsdt}</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-gray-500">Tokens:</span>
                        <span class="text-gray-300 font-semibold">${Number(l.amount).toFixed(1)}</span>
                    </div>
                    <div class="flex justify-between border-t border-gray-800/60 pt-0.5 mt-0.5">
                        <span class="text-gray-500">Falta:</span>
                        <span class="text-rose-300 font-bold">+${distPct}%</span>
                    </div>
                </div>
            </div>`;
        }

        // Generar filas para la cuadrícula de compras (Azules)
        let buysCards = '';
        for (let i = 0; i < buys.length; i++) {
            const l = buys[i];
            const distPct = ((currentPrice - l.price) / currentPrice * 100).toFixed(2);
            const isNext = (i === 0); // Más cercana
            const orderValUsdt = (Number(l.price) * Number(l.amount)).toFixed(2);
            
            buysCards += `
            <div class="bg-[#131722] p-2.5 rounded-lg border ${isNext ? 'border-cyan-500 shadow-md shadow-cyan-500/20 bg-cyan-950/25 ring-1 ring-cyan-500/50' : 'border-gray-800/80 hover:border-gray-700'} flex flex-col justify-between transition-all">
                <div class="flex justify-between items-center text-[10px] mb-1">
                    <span class="text-cyan-400 font-black tracking-wider flex items-center gap-1">
                      <span class="w-1.5 h-1.5 rounded-full bg-cyan-400"></span>BUY
                    </span>
                    ${isNext ? '<span class="bg-cyan-500/30 text-cyan-300 px-1.5 py-0.5 rounded text-[8px] font-black animate-pulse border border-cyan-500/40">⚡ PRÓXIMA</span>' : ''}
                </div>
                <div class="text-sm font-black text-white font-mono">$${Number(l.price).toFixed(6)}</div>
                <div class="text-[10px] text-gray-400 font-mono mt-1 space-y-0.5 bg-gray-950/40 p-1 rounded">
                    <div class="flex justify-between">
                        <span class="text-gray-500">Monto:</span>
                        <span class="text-emerald-400 font-bold">$${orderValUsdt}</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-gray-500">Tokens:</span>
                        <span class="text-gray-300 font-semibold">${Number(l.amount).toFixed(1)}</span>
                    </div>
                    <div class="flex justify-between border-t border-gray-800/60 pt-0.5 mt-0.5">
                        <span class="text-gray-500">Falta:</span>
                        <span class="text-cyan-300 font-bold">-${distPct}%</span>
                    </div>
                </div>
            </div>`;
        }
        
        html += `
        <div class="card p-5 border-l-4 border-l-purple-500 relative overflow-hidden group hover:border-l-purple-400 transition-colors space-y-4">
          <!-- 1. Cabecera Macro con Estado y Precio Vivo -->
          <div class="flex flex-wrap justify-between items-start gap-4 pb-3 border-b border-gray-800/80">
            <div>
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-2xl font-black text-white tracking-tight">${g.symbol}</span>
                <span class="text-xs bg-purple-500/20 text-purple-300 font-mono font-bold px-2 py-0.5 rounded border border-purple-500/30">MALLA CUANTITATIVA ACTIVA</span>
                <span class="text-[11px] bg-emerald-500/10 text-emerald-400 font-mono font-semibold px-2 py-0.5 rounded border border-emerald-500/20 flex items-center gap-1">
                  <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>${statusMsg}
                </span>
              </div>
              <div class="text-xs font-mono text-gray-400 mt-1 flex flex-wrap gap-4">
                <span>Piso: <strong class="text-white">$${Number(g.grid_lower).toFixed(6)}</strong></span>
                <span>Techo: <strong class="text-white">$${Number(g.grid_upper).toFixed(6)}</strong></span>
                <span>Paso Dinámico: <strong class="text-purple-300">${(Number(g.step_pct)*100).toFixed(2)}%</strong></span>
              </div>
            </div>
            
            <!-- Bloque de Precio Vivo Binance con Indicador de Pulso -->
            <div class="flex items-center gap-3">
              <div class="text-right bg-blue-950/40 border border-blue-500/50 rounded-lg px-4 py-2">
                <div class="text-[10px] text-blue-300 font-bold uppercase tracking-wider flex items-center justify-end gap-1.5">
                  <span class="w-2 h-2 rounded-full bg-emerald-400 animate-ping inline-block"></span>
                  Precio Binance Vivo
                </div>
                <div class="text-xl font-black text-white font-mono">$${Number(currentPrice).toFixed(6)}</div>
                <div class="text-[9px] text-gray-400 font-mono mt-0.5">Actualizado: ${tickTime || 'en vivo'}</div>
              </div>
            </div>
          </div>

          <!-- 2. RESUMEN EXCLUSIVO DE ESTA OPERACIÓN (Estilo Pionex Open Grid) -->
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-gray-950/70 p-3.5 rounded-xl border border-purple-500/30 shadow-inner">
            <div class="border-r border-gray-800/80 pr-2">
              <div class="text-[10px] text-gray-400 uppercase font-mono font-bold">Valor en Mercado (Tokens)</div>
              <div class="text-lg font-black font-mono text-white">$${(Number(g.market_value) || capTotal).toFixed(2)} <span class="text-xs text-gray-400 font-normal">USDT</span></div>
              <div class="text-[10px] text-gray-500 font-mono">${g.tokens_held || ''} ${g.symbol.split('/')[0]} en órdenes vivas</div>
            </div>
            
            <div class="border-r border-gray-800/80 pr-2">
              <div class="text-[10px] text-gray-400 uppercase font-mono font-bold flex items-center gap-1">
                <span>Cosecha en Esta Malla</span>
                <span class="text-[9px] bg-emerald-500/20 text-emerald-300 px-1 rounded font-bold">GRID PROFIT</span>
              </div>
              <div class="text-lg font-black font-mono text-emerald-400">+$${gridProfit.toFixed(4)} <span class="text-xs bg-emerald-500/20 text-emerald-300 px-1.5 py-0.5 rounded font-bold">+${gridRoiPct.toFixed(2)}%</span></div>
              <div class="text-[10px] text-emerald-500/80 font-mono">${gridFills} fills en esta operación</div>
            </div>

            <div class="border-r border-gray-800/80 pr-2">
              <div class="text-[10px] text-gray-400 uppercase font-mono font-bold flex items-center gap-1">
                <span>Flotante de Tokens</span>
                <span class="text-[9px] bg-blue-500/20 text-blue-300 px-1 rounded font-bold">FLOATING</span>
              </div>
              <div class="text-lg font-black font-mono ${gridFloating >= 0 ? 'text-emerald-400' : 'text-rose-400'}">${gridFloating >= 0 ? '+' : ''}$${gridFloating.toFixed(4)}</div>
              <div class="text-[10px] text-gray-500 font-mono">${sells.length} órdenes esperando rebote</div>
            </div>

            <div>
              <div class="text-[10px] text-gray-400 uppercase font-mono font-bold flex items-center gap-1">
                <span>PnL Neto Operación</span>
                <span class="text-[9px] bg-purple-500/20 text-purple-300 px-1 rounded font-bold">TOTAL MALLA</span>
              </div>
              <div class="text-lg font-black font-mono ${gridNetProfit >= 0 ? 'text-emerald-400' : 'text-amber-400'}">${gridNetProfit >= 0 ? '+' : ''}$${gridNetProfit.toFixed(4)} <span class="text-xs px-1.5 py-0.5 rounded font-bold bg-gray-800 text-gray-300">${gridNetRoi >= 0 ? '+' : ''}${gridNetRoi.toFixed(2)}%</span></div>
              <div class="text-[10px] text-cyan-400/80 font-mono">Cosecha + Valor de Tokens</div>
            </div>
          </div>

          <!-- 3. Medidor Visual de Rango del Canal (Range Meter) -->
          <div class="bg-gray-950/50 p-3 rounded-xl border border-gray-800 space-y-1.5 font-mono text-xs">
            <div class="flex justify-between items-center text-[11px] text-gray-400">
              <span>Piso Malla: <strong class="text-cyan-300">$${Number(g.grid_lower).toFixed(6)}</strong></span>
              <span class="text-purple-300 font-bold bg-purple-950/60 px-2 py-0.5 rounded border border-purple-800/40">
                Posición en Rango: ${rangePct.toFixed(1)}% | En Canal Óptimo ⚡
              </span>
              <span>Techo Malla: <strong class="text-rose-300">$${Number(g.grid_upper).toFixed(6)}</strong></span>
            </div>
            <div class="w-full bg-gray-900 h-2.5 rounded-full overflow-hidden relative border border-gray-800">
              <div class="bg-gradient-to-r from-cyan-500 via-purple-500 to-rose-500 h-full w-full opacity-60"></div>
              <!-- Puntero del precio actual en vivo -->
              <div class="absolute top-0 bottom-0 w-2.5 bg-white rounded-full shadow-lg shadow-white transform -translate-x-1/2 border border-gray-900" style="left: ${rangePct}%;"></div>
            </div>
            <div class="flex justify-between text-[10px] text-gray-500">
              <span class="text-cyan-400 font-semibold">🟢 Zona de Compras (${buys.length} órdenes vivas)</span>
              <span class="text-rose-400 font-semibold">Zona de Ventas (${sells.length} órdenes vivas) 🔻</span>
            </div>
          </div>
          
          <!-- 4. Cuadrícula de Micro-Órdenes en Vivo -->
          <div class="space-y-4 pt-1">
            <!-- Sección de Ventas Abajo de Techo -->
            <div>
              <div class="text-xs font-bold text-rose-400 uppercase tracking-wider mb-2 flex items-center justify-between">
                <span class="flex items-center gap-1.5">🔻 Órdenes de Venta Límite (${sells.length} activas esperando subida)</span>
                <span class="text-[10px] font-mono text-gray-500">Cosecha automáticas</span>
              </div>
              <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">
                ${sellsCards || '<div class="text-xs text-gray-500 col-span-full">Sin ventas activas</div>'}
              </div>
            </div>

            <!-- Sección de Compras Arriba de Piso -->
            <div>
              <div class="text-xs font-bold text-cyan-400 uppercase tracking-wider mb-2 flex items-center justify-between">
                <span class="flex items-center gap-1.5">🟢 Órdenes de Compra Límite (${buys.length} activas esperando bajada)</span>
                <span class="text-[10px] font-mono text-gray-500">Recompras automáticas</span>
              </div>
              <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">
                ${buysCards || '<div class="text-xs text-gray-500 col-span-full">Sin compras activas</div>'}
              </div>
            </div>
          </div>
          
          <div class="pt-3 border-t border-gray-800/80 text-xs text-gray-400 flex justify-between font-mono">
            <span>Inversión en la Malla: <strong class="text-white">$${capTotal.toFixed(2)} USDT</strong></span>
            <span>Total de Escalones Vivos: <strong class="text-purple-300">${buys.length + sells.length} órdenes</strong></span>
          </div>
        </div>`;
      }
      container.innerHTML = html;
    }
    function renderPositions(positions) {
      const container = document.getElementById('positions-container');
      if (!positions || positions.length === 0) {
        container.innerHTML = `
          <div class="col-span-full card p-8 text-center border-dashed border-gray-800">
            <div class="text-3xl mb-2">⚡</div>
            <div class="text-gray-300 font-bold">Sin posiciones activas en este momento</div>
            <p class="text-xs text-gray-500 mt-1">El escáner predictivo está evaluando el mercado para entrar en el próximo launchpad.</p>
          </div>
        `;
        return;
      }

      let html = '';
      for (const pos of positions) {
        const isProfit = (pos.floating_pnl || 0) >= 0;
        const pnlColor = isProfit ? 'text-emerald-400' : 'text-rose-400';
        const sign = isProfit ? '+' : '';
        const pctSign = (pos.floating_pct || 0) >= 0 ? '+' : '';

        const maxGain = Number(pos.max_gain_pct || 0).toFixed(2);
        const tp1Badge = pos.tp1_hit 
          ? '<span class="text-[10px] bg-emerald-500/20 text-emerald-300 font-bold px-2 py-0.5 rounded border border-emerald-500/40">🎯 TP1 COBRADO</span>'
          : '<span class="text-[10px] bg-gray-800 text-gray-400 px-2 py-0.5 rounded">BUSCANDO TP1</span>';
        
        const beBadge = pos.break_even_activated 
          ? '<span class="text-[10px] bg-cyan-500/20 text-cyan-300 font-bold px-2 py-0.5 rounded border border-cyan-500/40">🛡️ BREAK-EVEN ACTIVO</span>'
          : '';

        const isShort = (pos.side === 'short' || (pos.strategy && pos.strategy.includes('short')));
        const sideBadge = isShort
          ? '<span class="text-[10px] bg-rose-500/20 text-rose-300 font-bold px-2 py-0.5 rounded border border-rose-500/30">SHORT 📉</span>'
          : '<span class="text-[10px] bg-emerald-500/20 text-emerald-300 font-bold px-2 py-0.5 rounded border border-emerald-500/30">LONG 📈</span>';

        html += `
          <div class="card p-5 border-l-4 ${isProfit ? 'border-l-emerald-500' : 'border-l-amber-500'} bg-gray-900/60 shadow-lg relative overflow-hidden">
            <div class="flex items-center justify-between mb-3">
              <div class="flex items-center gap-2">
                <span class="text-lg font-black text-white font-mono">${pos.symbol}</span>
                ${sideBadge}
              </div>
              <div class="flex items-center gap-1.5 flex-wrap">
                ${tp1Badge}
                ${beBadge}
              </div>
            </div>

            <!-- Precios & Capital -->
            <div class="grid grid-cols-3 gap-2 text-xs font-mono mb-3 bg-gray-950/70 p-2.5 rounded-lg border border-gray-800/80">
              <div>
                <span class="text-[10px] text-gray-500 block uppercase">Entrada</span>
                <span class="text-gray-200 font-bold">$${Number(pos.entry_price).toFixed(5)}</span>
              </div>
              <div>
                <span class="text-[10px] text-gray-500 block uppercase">Precio Actual</span>
                <span class="text-white font-bold">$${Number(pos.current_price).toFixed(5)}</span>
              </div>
              <div>
                <span class="text-[10px] text-gray-500 block uppercase">Capital Vivo</span>
                <span class="text-emerald-400 font-bold">$${Number(pos.capital_current || pos.capital).toFixed(2)} USDT</span>
                ${pos.tp1_hit ? `<span class="text-[9px] text-emerald-400 block font-bold">(85% Runner Libre)</span>` : ''}
              </div>
            </div>

            <!-- Floating PnL Highlight -->
            <div class="flex items-center justify-between p-3 rounded-lg bg-gray-950/90 border border-gray-800 mb-3">
              <div>
                <span class="text-[10px] text-gray-400 uppercase font-bold tracking-wider">Ganancia / Pérdida Flotante</span>
                <div class="text-xl font-black font-mono ${pnlColor}">
                  ${sign}$${Number(pos.floating_pnl).toFixed(4)} USDT
                </div>
              </div>
              <div class="text-right">
                <span class="text-[10px] text-gray-400 uppercase font-bold tracking-wider">Retorno Flotante</span>
                <div class="text-lg font-extrabold font-mono ${pnlColor}">
                  ${pctSign}${Number(pos.floating_pct).toFixed(2)}%
                </div>
              </div>
            </div>

            <!-- Niveles de Salida Seguros -->
            <div class="flex justify-between items-center text-xs font-mono text-gray-300 mb-2">
              <span class="text-gray-400">Stop Loss Seguro: <strong class="text-cyan-300">$${Number(pos.stop_loss).toFixed(5)}</strong></span>
              <span class="text-gray-400">TP1 Objetivo: <strong class="text-emerald-400">$${Number(pos.tp1_price).toFixed(5)}</strong></span>
            </div>

            <div class="text-[11px] text-gray-400 font-mono mt-2 bg-gray-950/50 p-2 rounded border border-gray-800/60">
              ${pos.status_msg || 'Monitoreando dinámicamente...'} (Pico máx: +${maxGain}%)
            </div>
          </div>
        `;
      }
      container.innerHTML = html;
    }

    function renderChart(history) {
      if (!history || history.length < 2) return;
      const minVal = Math.min(...history);
      const maxVal = Math.max(...history);
      const currVal = history[history.length - 1];

      document.getElementById('chart-min').innerText = '$' + minVal.toFixed(2);
      document.getElementById('chart-max').innerText = '$' + maxVal.toFixed(2);
      document.getElementById('chart-curr').innerText = '$' + currVal.toFixed(2);

      const range = (maxVal - minVal) || 1.0;
      const w = 600;
      const h = 100;
      const pad = 10;

      let points = [];
      for (let i = 0; i < history.length; i++) {
        const x = (i / (history.length - 1)) * w;
        const normY = (history[i] - minVal) / range;
        const y = (h - pad) - (normY * (h - 2 * pad));
        points.push(`${x.toFixed(1)},${y.toFixed(1)}`);
      }

      const polylineD = 'M ' + points.join(' L ');
      document.getElementById('svg-line').setAttribute('d', polylineD);

      const areaD = `${polylineD} L ${w},${h} L 0,${h} Z`;
      document.getElementById('svg-area').setAttribute('d', areaD);
    }

    function renderMacroRadar(macroData) {
      if (!macroData) return;
      const badge = document.getElementById('btc-regime-badge');
      const pEl = document.getElementById('macro-btc-price');
      const cEl = document.getElementById('macro-btc-change');
      const emaEl = document.getElementById('macro-btc-ema50');
      const adxEl = document.getElementById('macro-btc-adx');
      const sumEl = document.getElementById('macro-btc-summary');

      if (badge && macroData.regime) {
        const reg = macroData.regime;
        let badgeColor = 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30';
        if (reg.includes('BEARISH')) badgeColor = 'bg-rose-500/20 text-rose-300 border-rose-500/30';
        else if (reg.includes('CHOP')) badgeColor = 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30';
        else if (reg.includes('PULLBACK')) badgeColor = 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30';
        badge.className = `font-bold px-2 py-0.5 rounded border ${badgeColor}`;
        badge.innerText = reg;
      }

      if (pEl && macroData.price) pEl.innerText = '$' + Number(macroData.price).toLocaleString();
      if (cEl && macroData.change_24h !== undefined) {
        const chg = Number(macroData.change_24h);
        cEl.innerText = (chg >= 0 ? '+' : '') + chg.toFixed(2) + '% (24h)';
        cEl.className = 'text-[11px] font-bold ' + (chg >= 0 ? 'text-emerald-400' : 'text-rose-400');
      }
      if (emaEl && macroData.ema50_4h) emaEl.innerText = '$' + Number(macroData.ema50_4h).toLocaleString();
      if (adxEl && macroData.adx_4h) adxEl.innerText = Number(macroData.adx_4h).toFixed(1);
      if (sumEl && macroData.summary) sumEl.innerText = macroData.summary;
    }

    function renderNewsSentinel(newsData) {}

    function renderScanner(opportunities) {
      const tbody = document.getElementById('scanner-tbody');
      if (!opportunities || opportunities.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="py-4 text-center text-gray-500">Escaneando candidatos con Arsenal Cuantitativo y Macro 4h...</td></tr>';
        return;
      }

      let html = '';
      for (const op of opportunities) {
        const an = op.analysis || {};
        const score = Number(op.score || 0).toFixed(1);
        const currP = Number(op.price || 0).toFixed(4);
        const limitP = Number(op.limit_buy_price || an.limit_buy_price || op.price).toFixed(4);
        const macroBias = op.macro_bias || an.macro_bias || 'NEUTRAL';
        const sqRatio = Number(an.sq_ratio !== undefined ? an.sq_ratio : 1.0).toFixed(2);
        const sqState = an.squeeze_state || op.stage || 'COILING';
        const obvSlope = Number(an.obv_slope !== undefined ? an.obv_slope : 0.0).toFixed(2);
        const ker = Number(an.ker !== undefined ? an.ker : 0.35).toFixed(2);
        const obi = Number(op.obi !== undefined ? op.obi : (an.lob ? an.lob.obi : 0.0));
        const obiStr = (obi >= 0 ? '+' : '') + obi.toFixed(2);
        const volM = (Number(op.volume || 0) / 1000000).toFixed(1);

        let macroBadge = 'bg-gray-800 text-gray-300';
        if (macroBias === 'BULLISH') macroBadge = 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30';
        else if (macroBias === 'RETEST_SUPPORT') macroBadge = 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30';
        else if (macroBias === 'BEARISH') macroBadge = 'bg-rose-500/20 text-rose-300 border border-rose-500/30';

        const cleanSym = (op.symbol || '').replace('/', '_');
        const binanceUrl = `https://www.binance.com/en/trade/${cleanSym}`;

        const rec = an.recommendation || 'skip';
        let dirBadge = '<span class="text-[10px] text-gray-500 font-mono">OBSERVANDO</span>';
        if (rec === 'long') {
          dirBadge = '<span class="text-[10px] bg-emerald-500/20 text-emerald-300 font-bold px-1.5 py-0.5 rounded border border-emerald-500/30">LONG ↗</span>';
        } else if (rec === 'short') {
          dirBadge = '<span class="text-[10px] bg-rose-500/20 text-rose-300 font-bold px-1.5 py-0.5 rounded border border-rose-500/30">SHORT ↘</span>';
        }

        html += `
          <tr class="hover:bg-gray-800/40 transition-colors">
            <td class="py-2.5 font-bold"><a href="${binanceUrl}" target="_blank" class="underline text-indigo-300 hover:text-white">${op.symbol} ↗</a></td>
            <td class="py-2.5 text-gray-300">$${currP}</td>
            <td class="py-2.5"><div class="flex items-center gap-1.5">${dirBadge} <span class="text-cyan-300 font-bold">$${limitP}</span></div></td>
            <td class="py-2.5 text-emerald-400 font-bold">${score}</td>
            <td class="py-2.5"><span class="px-2 py-0.5 rounded text-[10px] font-bold ${macroBadge}">${macroBias}</span></td>
            <td class="py-2.5 text-purple-300">${sqState} (${sqRatio})</td>
            <td class="py-2.5 text-gray-300 text-[11px]">OBV: ${obvSlope} | KER: ${ker} | <span class="${obi >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold'}">OBI: ${obiStr}</span></td>
            <td class="py-2.5 text-right text-gray-400">$${volM}M</td>
          </tr>
        `;
      }
      tbody.innerHTML = html;
    }

    function renderTrades(trades) {
      const tbody = document.getElementById('trades-tbody');
      if (!trades || trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="py-4 text-center text-gray-500">Sin operaciones recientes registradas</td></tr>';
        return;
      }

      let html = '';
      for (const t of trades.slice(0, 15)) {
        const timePart = t.timestamp ? t.timestamp.split('T')[1]?.split('.')[0] : '--:--:--';
        const isBuy = t.side === 'buy';
        let actionBadge = '';
        if (isBuy) {
          actionBadge = '<span class="text-[10px] bg-emerald-500/20 text-emerald-300 font-bold px-2 py-0.5 rounded border border-emerald-500/30">🟢 APERTURA</span>';
        } else if (t.strategy && t.strategy.includes('tp1') || t.status === 'PARTIAL_CLOSED') {
          actionBadge = '<span class="text-[10px] bg-blue-500/20 text-blue-300 font-bold px-2 py-0.5 rounded border border-blue-500/30">🎯 COBRO TP1</span>';
        } else {
          actionBadge = '<span class="text-[10px] bg-purple-500/20 text-purple-300 font-bold px-2 py-0.5 rounded border border-purple-500/30">🔒 CIERRE FINAL</span>';
        }

        const pnl = Number(t.pnl || 0);
        let pnlDisplay = '<span class="text-gray-500">-</span>';
        if (!isBuy) {
          const pnlColor = pnl >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold';
          pnlDisplay = `<span class="${pnlColor}">${pnl >= 0 ? '+' : ''}$${pnl.toFixed(4)}</span>`;
        }

        const feeSlip = '$' + (Number(t.fee || 0) + Number(t.slippage || 0)).toFixed(4);

        html += `
          <tr class="hover:bg-gray-800/40 transition-colors">
            <td class="py-2.5 text-gray-300 font-bold">${timePart}</td>
            <td class="py-2.5 font-bold text-white">${t.symbol}</td>
            <td class="py-2.5">${actionBadge}</td>
            <td class="py-2.5 text-gray-300">$${Number(t.price).toFixed(5)}</td>
            <td class="py-2.5 text-gray-400">${Number(t.amount).toFixed(4)}</td>
            <td class="py-2.5">${pnlDisplay}</td>
            <td class="py-2.5 text-gray-500">${feeSlip}</td>
            <td class="py-2.5 text-right text-gray-300">${t.extra_info || t.strategy}</td>
          </tr>
        `;
      }
      tbody.innerHTML = html;
      
      // Guardar en variable global para el modal
      window.__ALL_TRADES__ = trades || [];
      renderModalTrades(window.__ALL_TRADES__);
    }

    function toggleAllTradesModal() {
      const modal = document.getElementById('all-trades-modal');
      if (modal) {
        if (modal.style.display === 'none' || modal.classList.contains('hidden')) {
          modal.style.display = 'flex';
          modal.classList.remove('hidden');
          if (window.__ALL_TRADES__) {
            renderModalTrades(window.__ALL_TRADES__);
          }
        } else {
          modal.style.display = 'none';
          modal.classList.add('hidden');
        }
      }
    }

    function renderModalTrades(trades) {
      const tbody = document.getElementById('modal-trades-tbody');
      if (!tbody) return;
      if (!trades || trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="py-6 text-center text-gray-500 font-mono">No hay operaciones registradas aún</td></tr>';
        return;
      }

      let sumWins = 0.0;
      let countWins = 0;
      let sumLosses = 0.0;
      let countLosses = 0;
      let sumFees = 0.0;

      let html = '';
      for (const t of trades) {
        const timePart = t.timestamp ? (t.timestamp.includes('T') ? t.timestamp.split('T')[1].split('.')[0] : t.timestamp) : '--:--:--';
        const isBuy = (t.side === 'buy');
        const pnl = Number(t.pnl || 0);
        const fee = Number(t.fee || 0) + Number(t.slippage || 0);
        sumFees += fee;

        let actionBadge = '';
        if (isBuy) {
          actionBadge = '<span class="text-[10px] bg-emerald-500/20 text-emerald-300 font-bold px-2 py-0.5 rounded border border-emerald-500/30">🟢 COMPRA</span>';
        } else {
          if (pnl > 0) {
            actionBadge = '<span class="text-[10px] bg-emerald-500/30 text-emerald-300 font-bold px-2 py-0.5 rounded border border-emerald-500/50">🎯 VENTA GANANCIA</span>';
            sumWins += pnl;
            countWins++;
          } else if (pnl < 0) {
            actionBadge = '<span class="text-[10px] bg-rose-500/30 text-rose-300 font-bold px-2 py-0.5 rounded border border-rose-500/50">🛑 VENTA PÉRDIDA</span>';
            sumLosses += Math.abs(pnl);
            countLosses++;
          } else {
            actionBadge = '<span class="text-[10px] bg-gray-800 text-gray-400 font-bold px-2 py-0.5 rounded">⚪ VENTA NEUTRA</span>';
          }
        }

        let pnlDisplay = '<span class="text-gray-500">-</span>';
        if (!isBuy) {
          const pnlColor = pnl > 0 ? 'text-emerald-400 font-bold' : (pnl < 0 ? 'text-rose-400 font-bold' : 'text-gray-400');
          pnlDisplay = `<span class="${pnlColor}">${pnl > 0 ? '+' : ''}$${pnl.toFixed(4)}</span>`;
        }

        html += `
          <tr class="hover:bg-gray-800/40 transition-colors">
            <td class="py-2 text-gray-400 font-mono">${timePart}</td>
            <td class="py-2 font-bold text-white">${t.symbol}</td>
            <td class="py-2">${actionBadge}</td>
            <td class="py-2 text-gray-300 font-mono">$${Number(t.price).toFixed(5)}</td>
            <td class="py-2 text-gray-400 font-mono">${Number(t.amount).toFixed(4)}</td>
            <td class="py-2 font-mono">${pnlDisplay}</td>
            <td class="py-2 text-gray-500 font-mono">$${fee.toFixed(4)}</td>
            <td class="py-2 text-right text-gray-300 font-mono text-[11px]">${t.extra_info || t.strategy}</td>
          </tr>
        `;
      }

      tbody.innerHTML = html;

      // Actualizar tarjetas de resumen del Modal
      const totalTradesCount = countWins + countLosses;
      const netPnl = sumWins - sumLosses;
      const winRate = totalTradesCount > 0 ? (countWins / totalTradesCount * 100) : 100.0;

      const modalSumWins = document.getElementById('modal-sum-wins');
      const modalCountWins = document.getElementById('modal-count-wins');
      const modalSumLosses = document.getElementById('modal-sum-losses');
      const modalCountLosses = document.getElementById('modal-count-losses');
      const modalNetPnl = document.getElementById('modal-net-pnl');
      const modalWinrate = document.getElementById('modal-winrate');
      const modalTotalFees = document.getElementById('modal-total-fees');
      const modalTotalRecords = document.getElementById('modal-total-records-badge');

      if (modalSumWins) modalSumWins.innerText = `+$${sumWins.toFixed(4)} USDT`;
      if (modalCountWins) modalCountWins.innerText = `${countWins} ventas en ganancia`;
      if (modalSumLosses) modalSumLosses.innerText = `-$${sumLosses.toFixed(4)} USDT`;
      if (modalCountLosses) modalCountLosses.innerText = `${countLosses} ventas en pérdida`;
      if (modalNetPnl) {
        modalNetPnl.innerText = `${netPnl >= 0 ? '+' : ''}$${netPnl.toFixed(4)} USDT`;
        modalNetPnl.className = `text-lg sm:text-xl font-black mt-0.5 ${netPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`;
      }
      if (modalWinrate) modalWinrate.innerText = `Win Rate Real: ${winRate.toFixed(1)}%`;
      if (modalTotalFees) modalTotalFees.innerText = `$${sumFees.toFixed(4)} USDT`;
      if (modalTotalRecords) modalTotalRecords.innerText = `${trades.length} operaciones registradas`;
      
      const btnText = document.getElementById('btn-trades-text');
      if (btnText) btnText.innerText = `Ver Todas las Operaciones (${trades.length})`;
    }

    function renderPendingLimits(limits) {
      const container = document.getElementById('pending-limits-container');
      const section = document.getElementById('pending-limits-section');
      if (!container || !section) return;
      if (!limits || limits.length === 0) {
        section.classList.add('hidden');
        return;
      }
      section.classList.remove('hidden');
      let html = '';
      for (const o of limits) {
        const isShortOrder = (o.side === 'short');
        const orderBadge = isShortOrder
          ? '<span class="text-[10px] bg-rose-500/20 text-rose-300 font-bold px-2 py-0.5 rounded border border-rose-500/40">VENTA LÍMITE SHORT (MAKER) 📉</span>'
          : '<span class="text-[10px] bg-cyan-500/20 text-cyan-300 font-bold px-2 py-0.5 rounded border border-cyan-500/40">COMPRA LÍMITE LONG (MAKER) 📈</span>';

        html += `
          <div class="card p-3.5 bg-gradient-to-r ${isShortOrder ? 'from-rose-950/70 to-gray-900 border-rose-500/40' : 'from-cyan-950/70 to-gray-900 border-cyan-500/40'} border rounded-lg flex items-center justify-between flex-wrap gap-3 shadow-lg">
            <div class="flex items-center gap-3">
              <span class="text-xl">${isShortOrder ? '📉' : '🎯'}</span>
              <div>
                <div class="flex items-center gap-2">
                  <span class="font-black text-white font-mono text-sm">${o.symbol}</span>
                  ${orderBadge}
                </div>
                <div class="text-xs text-gray-400 mt-0.5 font-mono">
                  Precio Límite: <strong class="${isShortOrder ? 'text-rose-300' : 'text-cyan-300'}">$${Number(o.limit_price).toFixed(5)}</strong>
                  (Actual: $${Number(o.current_price).toFixed(5)} | Distancia: <span class="text-yellow-400">${Number(o.distance_pct).toFixed(2)}%</span>)
                </div>
              </div>
            </div>
            <div class="flex items-center gap-4 text-xs font-mono">
              <div>
                <span class="text-gray-500 text-[10px] block uppercase">Capital</span>
                <span class="text-white font-bold">$${Number(o.capital).toFixed(2)} USDT</span>
              </div>
              <div>
                <span class="text-gray-500 text-[10px] block uppercase">Deslizamiento</span>
                <span class="text-emerald-400 font-bold">$0.00 (Maker Pasivo)</span>
              </div>
              <div class="text-right">
                <span class="text-gray-500 text-[10px] block uppercase">Expiración</span>
                <span class="text-amber-400 font-bold countdown-timer" data-sec="${o.remaining_sec}">${o.remaining_sec}s</span>
              </div>
            </div>
          </div>
        `;
      }
      container.innerHTML = html;
    }

    // Local ticking for countdowns
    setInterval(() => {
      const timers = document.querySelectorAll('.countdown-timer');
      timers.forEach(t => {
        let sec = parseInt(t.getAttribute('data-sec'), 10);
        if (!isNaN(sec) && sec > 0) {
          sec--;
          t.setAttribute('data-sec', sec);
          if (sec === 0) {
            t.innerText = 'EXPIRANDO...';
            t.className = 'text-rose-400 font-bold countdown-timer animate-pulse-fast';
          } else {
            t.innerText = sec + 's';
          }
        }
      });
    }, 1000);

    function renderSelfEval(evalData) {
      const container = document.getElementById('self-eval-container');
      if (!container) return;
      const report = evalData.report || {};
      const recs = evalData.recommendations || {};
      const overall = report.overall || {};
      const friction = report.friction || {};
      const exitReasons = report.by_exit_reason || {};

      const wr = Number(overall.win_rate !== undefined ? overall.win_rate * 100 : 0).toFixed(1);
      const pf = Number(overall.profit_factor || 0).toFixed(2);
      const exp = Number(overall.expectancy || 0).toFixed(4);
      const totalFric = Number(friction.total_friction_cost || 0).toFixed(2);
      const nTrades = report.n_trades || 0;

      let recsListHtml = '';
      const recKeys = Object.keys(recs);
      if (recKeys.length === 0) {
        recsListHtml = '<li class="text-emerald-400">✅ Todos los parámetros operando dentro de los límites de riesgo saludables.</li>';
      } else {
        for (const k of recKeys) {
          const v = recs[k];
          if (Array.isArray(v)) {
            for (const item of v) {
              recsListHtml += `<li class="text-amber-300">⚠️ ${item}</li>`;
            }
          } else {
            recsListHtml += `<li class="text-amber-300">⚠️ ${v}</li>`;
          }
        }
      }

      let exitBreakdownHtml = '';
      for (const [reason, pct] of Object.entries(exitReasons)) {
        const p = (Number(pct) * 100).toFixed(0);
        exitBreakdownHtml += `<span class="bg-gray-800/80 px-2 py-0.5 rounded text-[10px] text-gray-300">${reason}: <strong class="text-white">${p}%</strong></span> `;
      }

      container.innerHTML = `
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center mb-4">
          <div class="bg-gray-950/80 p-3 rounded-lg border border-gray-800">
            <div class="text-[10px] text-gray-400 font-bold uppercase">Win Rate (Últ. ${nTrades})</div>
            <div class="text-lg font-black font-mono ${Number(wr) >= 50 ? 'text-emerald-400' : 'text-amber-400'} mt-0.5">${wr}%</div>
            <div class="text-[10px] text-gray-500">Muestra rodante</div>
          </div>
          <div class="bg-gray-950/80 p-3 rounded-lg border border-gray-800">
            <div class="text-[10px] text-gray-400 font-bold uppercase">Esperanza (EV / Trade)</div>
            <div class="text-lg font-black font-mono ${Number(exp) >= 0 ? 'text-emerald-400' : 'text-rose-400'} mt-0.5">${Number(exp) >= 0 ? '+' : ''}$${exp}</div>
            <div class="text-[10px] text-gray-500">Expectativa neta</div>
          </div>
          <div class="bg-gray-950/80 p-3 rounded-lg border border-gray-800">
            <div class="text-[10px] text-gray-400 font-bold uppercase">Arrastre Fricción</div>
            <div class="text-lg font-black font-mono text-rose-400 mt-0.5">$${totalFric}</div>
            <div class="text-[10px] text-gray-500">Comisiones + Slippage</div>
          </div>
          <div class="bg-gray-950/80 p-3 rounded-lg border border-gray-800">
            <div class="text-[10px] text-gray-400 font-bold uppercase">Profit Factor</div>
            <div class="text-lg font-black font-mono ${Number(pf) >= 1.2 ? 'text-emerald-400' : 'text-yellow-400'} mt-0.5">${pf}</div>
            <div class="text-[10px] text-gray-500">Ganancias / Pérdidas</div>
          </div>
        </div>
        <div class="bg-gray-950/70 p-3 rounded-lg border border-gray-800 text-xs space-y-2">
          <div class="flex items-center justify-between flex-wrap gap-2">
            <span class="font-bold text-gray-300">Desglose de Salidas:</span>
            <div class="flex items-center gap-1.5 flex-wrap">${exitBreakdownHtml || '<span class="text-gray-500">Esperando ciclos</span>'}</div>
          </div>
          <div class="pt-2 border-t border-gray-800/80">
            <span class="font-bold text-gray-300 block mb-1">Diagnóstico & Auto-Adaptaciones Algorítmicas:</span>
            <ul class="space-y-1 pl-4 list-disc text-[11px] font-mono">${recsListHtml}</ul>
          </div>
        </div>
      `;
    }

    function renderPnlAudit(auditList) {
      const tbody = document.getElementById('audit-tbody');
      if (!tbody) return;
      if (!auditList || auditList.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="py-4 text-center text-gray-500">Sin ciclos completos auditados aún</td></tr>';
        return;
      }
      let html = '';
      for (const c of auditList) {
        const isLive = c.is_open || (c.exit_time && c.exit_time.includes('EN VIVO'));
        const timePart = isLive ? '<span class="text-emerald-400 font-bold animate-pulse">⚡ EN VIVO</span>' : (c.exit_time ? (c.exit_time.includes('T') ? c.exit_time.split('T')[1]?.split('.')[0] : c.exit_time) : '--:--');
        const isWin = Number(c.net_pnl) > 0;
        const isBE = Number(c.net_pnl) === 0;
        const pnlColor = isWin ? 'text-emerald-400 font-bold' : (isBE ? 'text-gray-400' : 'text-rose-400 font-bold');
        const pnlSign = Number(c.net_pnl) > 0 ? '+' : '';

        let badgeClass = isLive ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40 animate-pulse' : (isWin ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40' : (isBE ? 'bg-gray-800 text-gray-400' : 'bg-rose-500/20 text-rose-300 border-rose-500/40'));

        html += `
          <tr class="hover:bg-gray-800/40 transition-colors font-mono">
            <td class="py-2.5 text-gray-400">${timePart}</td>
            <td class="py-2.5 font-bold text-white">${c.symbol}</td>
            <td class="py-2.5"><span class="px-2 py-0.5 rounded text-[10px] font-bold border ${badgeClass}">${c.verdict}</span></td>
            <td class="py-2.5 text-gray-300">$${Number(c.entry_price).toFixed(5)}</td>
            <td class="py-2.5 text-gray-300">$${Number(c.exit_price).toFixed(5)}</td>
            <td class="py-2.5 ${pnlColor}">${pnlSign}$${Number(c.net_pnl).toFixed(4)}</td>
            <td class="py-2.5 text-gray-400">$${(Number(c.fees || 0) + Number(c.slippage || 0)).toFixed(4)}</td>
            <td class="py-2.5 text-gray-400">${Number(c.hold_duration_min || 0).toFixed(1)}m</td>
            <td class="py-2.5 text-right text-gray-300">${c.exit_reason}</td>
          </tr>
        `;
      }
      tbody.innerHTML = html;
    }

    function renderAiAudits(audits, activeParams, memoryData) {
      const container = document.getElementById('ai-audits-container');
      if (!container) return;

      let headerHtml = '';
      if (activeParams) {
        headerHtml = `
          <div class="bg-gray-950/80 p-3 rounded-lg border border-cyan-500/30 flex items-center justify-between flex-wrap gap-2 text-xs font-mono mb-3">
            <div class="flex items-center gap-2">
              <span class="text-cyan-400 font-bold uppercase text-[11px]">⚙️ Parámetros Activos Adaptados:</span>
              <span class="bg-gray-800 text-gray-200 px-2 py-0.5 rounded border border-gray-700">SL ATR: <strong class="text-cyan-300">${Number(activeParams.sl_atr_mult || 2.2).toFixed(2)}x</strong></span>
              <span class="bg-gray-800 text-gray-200 px-2 py-0.5 rounded border border-gray-700">Score Mín: <strong class="text-yellow-300">${Number(activeParams.min_score || 65).toFixed(1)} pts</strong></span>
              <span class="bg-gray-800 text-gray-200 px-2 py-0.5 rounded border border-gray-700">TP1: <strong class="text-emerald-300">+${Number(activeParams.tp1_pct || 2.42).toFixed(2)}%</strong></span>
            </div>
            <div class="text-[10px] text-gray-400 font-sans">
              Memoria: <strong class="text-cyan-300">${Object.keys((memoryData && memoryData.coin_lessons) || {}).length}</strong> monedas catalogadas
            </div>
          </div>
        `;
      }

      const tuningList = (memoryData && memoryData.tuning_history) || [];
      let tuningBannerHtml = '';
      if (tuningList.length > 0) {
        const lastTune = tuningList[tuningList.length - 1];
        tuningBannerHtml = `
          <div class="bg-cyan-950/40 p-2.5 rounded-lg border border-cyan-500/40 font-mono text-[11px] text-cyan-200 flex items-center justify-between flex-wrap gap-2 mb-3">
            <div class="flex items-center gap-2">
              <span>⚡</span>
              <span><strong>Último Ajuste del Auditor (${lastTune.timestamp}):</strong> ${lastTune.parameter} (${lastTune.old_value} -> ${lastTune.new_value})</span>
            </div>
            <span class="text-gray-300 font-sans text-xs italic">${lastTune.reason || ''}</span>
          </div>
        `;
      }

      if (!audits || audits.length === 0) {
        container.innerHTML = headerHtml + tuningBannerHtml + '<div class="p-3 text-center text-gray-500 font-mono text-xs">Esperando cierre de posiciones para emitir diagnósticos forenses con IA de NVIDIA...</div>';
        return;
      }

      // Deduplicar auditorías por (symbol + timestamp)
      const seenAudits = new Set();
      const uniqueAudits = [];
      for (const a of audits.slice().reverse()) {
        const sig = `${a.symbol}_${a.timestamp}_${a.pnl}`;
        if (!seenAudits.has(sig)) {
          seenAudits.add(sig);
          uniqueAudits.push(a);
        }
      }

      let html = headerHtml + tuningBannerHtml;
      for (const a of uniqueAudits) {
        const isWin = a.is_win;
        const pnlColor = isWin ? 'text-emerald-400' : 'text-rose-400';
        const cardBorder = isWin ? 'border-emerald-500/30 bg-emerald-950/20' : 'border-rose-500/30 bg-rose-950/20';
        const badgeColor = isWin ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40' : 'bg-rose-500/20 text-rose-300 border-rose-500/40';

        html += `
          <div class="p-3.5 rounded-lg border ${cardBorder} font-mono text-xs space-y-2 mb-2">
            <div class="flex items-center justify-between flex-wrap gap-2">
              <div class="flex items-center gap-2">
                <span class="font-bold text-white text-sm">${a.symbol}</span>
                <span class="text-[10px] px-2 py-0.5 rounded border font-bold ${badgeColor}">${isWin ? 'WIN 🎯' : 'LOSS 🛑'} (${a.calidad || 'EVALUADO'})</span>
                <span class="text-gray-400 text-[11px]">${a.timestamp || ''}</span>
              </div>
              <div class="flex items-center gap-3">
                <span class="${pnlColor} font-black text-sm">${Number(a.pnl) >= 0 ? '+' : ''}$${Number(a.pnl).toFixed(4)} USDT</span>
                <span class="bg-gray-800 text-gray-300 text-[10px] px-2 py-0.5 rounded">Calidad: ${a.puntaje || 7}/10</span>
              </div>
            </div>
            <div class="bg-gray-950/70 p-2.5 rounded border border-gray-800/80 font-sans text-xs text-gray-300 leading-relaxed">
              <strong class="text-cyan-300 block mb-0.5 font-mono text-[11px]">DIAGNÓSTICO FORENSE:</strong>
              ${a.diagnostico || 'Sin diagnóstico disponible.'}
            </div>
            <div class="bg-purple-950/30 p-2 rounded border border-purple-800/40 font-sans text-xs text-purple-200">
              <strong class="text-purple-300 font-mono text-[10px] uppercase">💡 Lección Cuantitativa:</strong>
              ${a.leccion || 'Mantener disciplina.'}
            </div>
          </div>
        `;
      }
      container.innerHTML = html;
    }

    function renderCommitteeDeliberations(deliberations) {
      const container = document.getElementById('committee-deliberations-container');
      if (!container) return;

      if (!deliberations || deliberations.length === 0) {
        container.innerHTML = `
          <div class="p-3 text-center text-gray-500 font-mono text-xs">
            El Comité Multi-Agente (Analista, Jefe de Riesgo, Francotirador) está en sesión; esperando candidatos filtrados (Score &ge; 65)...
          </div>
        `;
        return;
      }

      let html = '';
      for (const d of deliberations.slice().reverse()) {
        const isApproved = d.decision === 'APROBADO';
        const borderCol = isApproved ? 'border-indigo-500/40 bg-indigo-950/20' : 'border-rose-500/30 bg-rose-950/20';
        const badgeCol = isApproved ? 'bg-indigo-500/20 text-indigo-300 border-indigo-500/40' : 'bg-rose-500/20 text-rose-300 border-rose-500/40';

        const dir = (d.direccion || 'LONG').toUpperCase();
        const dirBadge = dir === 'SHORT'
          ? '<span class="bg-rose-500/20 text-rose-300 border border-rose-500/40 text-[10px] px-2 py-0.5 rounded font-bold">SHORT 📉</span>'
          : (dir === 'LONG'
            ? '<span class="bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 text-[10px] px-2 py-0.5 rounded font-bold">LONG 📈</span>'
            : '<span class="bg-gray-800 text-gray-400 text-[10px] px-2 py-0.5 rounded font-bold">NEUTRAL ⚪</span>');

        const debate = d.debate || {};
        const mult = (Number(d.multiplicador_capital || 1) * 100).toFixed(0);

        html += `
          <div class="p-3.5 rounded-lg border ${borderCol} font-mono text-xs space-y-2 mb-2">
            <div class="flex items-center justify-between flex-wrap gap-2">
              <div class="flex items-center gap-2">
                <span class="font-bold text-white text-sm">${d.symbol}</span>
                <span class="text-[10px] px-2 py-0.5 rounded border font-bold ${badgeCol}">${d.decision}</span>
                ${dirBadge}
                <span class="bg-gray-800 text-gray-300 text-[10px] px-2 py-0.5 rounded">Táctica: ${d.tactica || 'MAKER_LIMIT'}</span>
                <span class="text-gray-400 text-[11px]">${d.timestamp || ''}</span>
              </div>
              <div class="flex items-center gap-2 text-[11px]">
                <span class="text-gray-400">Asignación Convicción:</span>
                <strong class="text-emerald-400">${mult}% Capital</strong>
              </div>
            </div>

            <!-- Diálogo del Debate Multi-Agente (4 Roles) -->
            <div class="space-y-1.5 pt-1 text-[11px] font-sans">
              ${debate.centinela_macro ? `
              <div class="bg-gray-950/70 p-2 rounded border border-gray-800 flex items-start gap-2">
                <span class="bg-purple-500/20 text-purple-300 px-1.5 py-0.5 rounded text-[10px] font-mono font-bold shrink-0">🛡️ CENTINELA MACRO</span>
                <span class="text-gray-300">${debate.centinela_macro}</span>
              </div>` : ''}
              <div class="bg-gray-950/70 p-2 rounded border border-gray-800 flex items-start gap-2">
                <span class="bg-blue-500/20 text-blue-300 px-1.5 py-0.5 rounded text-[10px] font-mono font-bold shrink-0">📊 ANALISTA TÉCNICO</span>
                <span class="text-gray-300">${debate.analista_tecnico || debate.analista || 'Analizando confluencia técnica...'}</span>
              </div>
              <div class="bg-gray-950/70 p-2 rounded border border-gray-800 flex items-start gap-2">
                <span class="bg-amber-500/20 text-amber-300 px-1.5 py-0.5 rounded text-[10px] font-mono font-bold shrink-0">⚖️ JEFE DE RIESGO</span>
                <span class="text-gray-300">${debate.jefe_riesgo || 'Evaluando contra memoria del sistema...'}</span>
              </div>
              ${debate.jefe_ejecucion ? `
              <div class="bg-gray-950/70 p-2 rounded border border-gray-800 flex items-start gap-2">
                <span class="bg-cyan-500/20 text-cyan-300 px-1.5 py-0.5 rounded text-[10px] font-mono font-bold shrink-0">🎯 FRANCOTIRADOR</span>
                <span class="text-gray-300">${debate.jefe_ejecucion}</span>
              </div>` : ''}
              <div class="bg-indigo-950/50 p-2 rounded border border-indigo-500/30 flex items-start gap-2 text-indigo-200">
                <span class="bg-indigo-500/30 text-indigo-300 px-1.5 py-0.5 rounded text-[10px] font-mono font-bold shrink-0">🏛️ CONSENSO FINAL</span>
                <span>${d.razon_clave || debate.decision_consensuada || ''}</span>
              </div>
            </div>
          </div>
        `;
      }
      container.innerHTML = html;
    }

    function renderMetaLabeling(metaData) {
      const container = document.getElementById('meta-labeling-container');
      const badge = document.getElementById('meta-samples-badge');
      if (!container) return;

      const samples = metaData.samples_count || 0;
      const lastTrained = metaData.last_trained_at || 'Calibrado con Priors';
      const decisions = metaData.recent_decisions || [];
      const weights = metaData.feature_weights || {};

      if (badge) {
        badge.innerText = `${samples} trades aprendidos (${lastTrained})`;
      }

      let decisionsHtml = '';
      if (decisions.length === 0) {
        decisionsHtml = '<tr><td colspan="7" class="py-3 text-center text-gray-500 font-mono">Esperando señales del Modelo Primario para evaluar...</td></tr>';
      } else {
        for (const d of decisions.slice().reverse()) {
          const isVeto = d.veto;
          const badgeClass = isVeto ? 'bg-rose-500/20 text-rose-300 border-rose-500/40' : 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40';
          const badgeText = isVeto ? '🛑 VETO' : '✅ APROBADO';
          const probColor = Number(d.prob) >= 0.55 ? 'text-emerald-400' : 'text-amber-400';

          decisionsHtml += `
            <tr class="hover:bg-gray-800/40 transition-colors font-mono">
              <td class="py-2 text-gray-400">${d.time}</td>
              <td class="py-2 font-bold text-white">${d.symbol}</td>
              <td class="py-2"><span class="px-2 py-0.5 rounded text-[10px] font-bold border ${badgeClass}">${badgeText}</span></td>
              <td class="py-2 ${probColor} font-bold">${d.prob_pct}</td>
              <td class="py-2 text-cyan-300">${d.multiplier > 0 ? d.multiplier + 'x' : '-'}</td>
              <td class="py-2 text-gray-400">KER: ${Number(d.ker || 0).toFixed(2)}</td>
              <td class="py-2 text-right text-gray-300 text-[11px]">${d.reason}</td>
            </tr>
          `;
        }
      }

      let weightsHtml = '';
      for (const [name, w] of Object.entries(weights)) {
        const wVal = Number(w);
        const color = wVal > 0 ? 'text-emerald-400' : (wVal < 0 ? 'text-rose-400' : 'text-gray-400');
        weightsHtml += `<span class="bg-gray-950/70 border border-gray-800/80 px-2 py-1 rounded text-[10px] font-mono text-gray-300">${name}: <strong class="${color}">${wVal > 0 ? '+' : ''}${wVal}</strong></span> `;
      }

      container.innerHTML = `
        <div class="space-y-3">
          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead>
                <tr class="text-gray-400 border-b border-gray-800 font-mono text-[11px]">
                  <th class="pb-2">HORA</th>
                  <th class="pb-2">PAR</th>
                  <th class="pb-2">DECISIÓN NIVEL 2</th>
                  <th class="pb-2">P(ÉXITO)</th>
                  <th class="pb-2">BET SIZE</th>
                  <th class="pb-2">EFICIENCIA</th>
                  <th class="pb-2 text-right">ARGUMENTO QUANT</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-800/60 font-mono">
                ${decisionsHtml}
              </tbody>
            </table>
          </div>
          <div class="pt-2 border-t border-gray-800/80">
            <span class="text-[10px] uppercase font-bold text-gray-400 tracking-wider block mb-1.5 font-mono">Pesos Activos del Meta-Modelo ($W_i$ optimizados L-BFGS-B):</span>
            <div class="flex items-center gap-1.5 flex-wrap">${weightsHtml}</div>
          </div>
        </div>
      `;
    }

    function toggleAiLogsModal() {
      const modal = document.getElementById('ai-logs-modal');
      if (modal) {
        modal.classList.toggle('hidden');
      }
    }

    function renderAiPulse(data) {
      const titleEl = document.getElementById('ai-pulse-title');
      const chipsEl = document.getElementById('ai-pulse-chips');
      if (!titleEl || !chipsEl) return;

      const deliberations = data.committee_deliberations || [];
      const opps = data.scanner_opportunities || [];
      const btc = data.btc_macro || {};
      const news = data.news_sentinel || {};

      let lastDelib = deliberations.length > 0 ? deliberations[deliberations.length - 1] : null;

      if (lastDelib) {
        const isApp = lastDelib.decision === 'APROBADO';
        const color = isApp ? 'text-emerald-400' : 'text-amber-300';
        const icon = isApp ? '🟢' : '🛑';
        titleEl.innerHTML = `${icon} <strong class="${color}">${lastDelib.symbol}</strong>: ${lastDelib.razon_clave || lastDelib.decision} (${lastDelib.timestamp || ''})`;
        
        const dirBadge = lastDelib.direccion === 'SHORT'
          ? '<span class="bg-rose-500/20 text-rose-300 border border-rose-500/40 px-2 py-0.5 rounded font-bold">SHORT ↘</span>'
          : '<span class="bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 px-2 py-0.5 rounded font-bold">LONG ↗</span>';

        const tactBadge = `<span class="bg-gray-800 text-gray-200 px-2 py-0.5 rounded border border-gray-700">${lastDelib.tactica || 'MAKER'}</span>`;
        const btcBadge = `<span class="bg-indigo-500/20 text-indigo-300 px-2 py-0.5 rounded border border-indigo-500/30">BTC: ${btc.trend || 'NORMAL'}</span>`;
        const newsBadge = `<span class="bg-purple-500/20 text-purple-300 px-2 py-0.5 rounded border border-purple-500/30">Noticias: ${news.sentiment || 'NEUTRAL'}</span>`;

        chipsEl.innerHTML = `${dirBadge} ${tactBadge} ${btcBadge} ${newsBadge}`;
      } else if (opps.length > 0) {
        const best = opps[0];
        titleEl.innerHTML = `🔭 Radar enfocado en <strong class="text-indigo-300">${best.symbol}</strong> (Score: ${Number(best.score).toFixed(1)} pts) | En espera de deliberación`;
        chipsEl.innerHTML = `<span class="bg-emerald-500/20 text-emerald-300 px-2 py-0.5 rounded border border-emerald-500/30">Candidato #1: ${best.symbol}</span>`;
      } else {
        titleEl.innerHTML = `🧭 Escaneando pares de alta liquidez en Binance...`;
        chipsEl.innerHTML = `<span class="bg-gray-800 text-gray-400 px-2 py-0.5 rounded">Filtro $25M+ activo</span>`;
      }
    }

    // Pre-cargar estado inicial si existe
    if (window.__INITIAL_STATE__) {
      updateUI(window.__INITIAL_STATE__);
    }

    // Iniciar polling
    fetchState();
  </script>

</body>
</html>
"""
