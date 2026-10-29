"""Plantillas HTML / UI para el Servidor Dashboard."""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>THE SWING SNIPER & PIONEX GRID - QUANT DASHBOARD</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700;800&family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-base: #0d1117;
            --card-bg: #161b22;
            --border: #30363d;
            --accent: #58a6ff;
            --green: #3fb950;
            --red: #f85149;
            --yellow: #d29922;
            --purple: #bc8cff;
            --text-main: #c9d1d9;
            --text-dim: #8b949e;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background: var(--bg-base);
            color: var(--text-main);
            font-family: 'Inter', -apple-system, sans-serif;
            padding: 24px;
        }
        .container { max-width: 1350px; margin: 0 auto; }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 16px;
            margin-bottom: 24px;
            flex-wrap: wrap;
            gap: 15px;
        }
        .title-block h1 {
            font-size: 22px;
            font-weight: 800;
            color: #ffffff;
            letter-spacing: -0.5px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .title-sub { font-size: 13px; color: var(--text-dim); margin-top: 4px; font-family: 'JetBrains Mono', monospace; }
        .badge-live {
            background: rgba(63, 185, 80, 0.15);
            color: var(--green);
            border: 1px solid var(--green);
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }
        .grid-2col {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 24px;
        }
        @media (max-width: 900px) { .grid-2col { grid-template-columns: 1fr; } }
        .card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
        }
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #21262d;
            padding-bottom: 12px;
            margin-bottom: 16px;
        }
        .card-title {
            font-size: 15px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .metric-box {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            gap: 12px;
            margin-bottom: 15px;
        }
        .metric {
            background: #0d1117;
            padding: 12px;
            border-radius: 8px;
            border: 1px solid #21262d;
        }
        .metric-label { font-size: 11px; color: var(--text-dim); text-transform: uppercase; font-weight: 600; }
        .metric-value { font-size: 18px; font-weight: 800; color: #ffffff; margin-top: 4px; font-family: 'JetBrains Mono', monospace; }
        
        table { width: 100%; border-collapse: collapse; font-family: 'JetBrains Mono', monospace; font-size: 12px; }
        th { text-align: left; padding: 10px 8px; color: var(--text-dim); border-bottom: 1px solid var(--border); font-size: 11px; }
        td { padding: 10px 8px; border-bottom: 1px solid #1c2128; }
        tr:hover { background: rgba(88, 166, 255, 0.04); }
        .tag { padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; display: inline-block; }
        .tag-green { background: rgba(63, 185, 80, 0.15); color: var(--green); border: 1px solid var(--green); }
        .tag-yellow { background: rgba(210, 153, 34, 0.15); color: var(--yellow); border: 1px solid var(--yellow); }
        .tag-gray { background: #21262d; color: var(--text-dim); }
        .terminal {
            background: #090d13;
            border: 1px solid #21262d;
            border-radius: 8px;
            padding: 12px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 11px;
            height: 160px;
            overflow-y: auto;
        }
        .log-row { margin-bottom: 4px; }
        .log-time { color: var(--text-dim); }
        .log-trade { color: var(--green); font-weight: 600; }
        .log-info { color: var(--text-main); }

        /* Faders & Sliders Panel de Control */
        .fader-group {
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 12px 14px;
            transition: border-color 0.2s;
        }
        .fader-group:hover {
            border-color: #58a6ff;
        }
        .fader-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }
        .fader-label {
            font-size: 12px;
            font-weight: 600;
            color: var(--text-main);
        }
        .fader-val {
            font-size: 13px;
            font-weight: 700;
            color: #58a6ff;
            font-family: 'JetBrains Mono', monospace;
        }
        .fader-sub {
            font-size: 10px;
            color: var(--text-dim);
            margin-top: 6px;
            line-height: 1.3;
        }
        input[type=range] {
            -webkit-appearance: none;
            width: 100%;
            background: #21262d;
            height: 6px;
            border-radius: 3px;
            outline: none;
            cursor: pointer;
        }
        input[type=range]::-webkit-slider-thumb {
            -webkit-appearance: none;
            appearance: none;
            width: 16px;
            height: 16px;
            border-radius: 50%;
            background: #f0883e;
            cursor: pointer;
            box-shadow: 0 0 6px rgba(240, 136, 62, 0.5);
            transition: transform 0.1s;
        }
        input[type=range]::-webkit-slider-thumb:hover {
            transform: scale(1.25);
        }
        .btn-toggle-auto {
            background: #1f6feb;
            border: 1px solid #388bfd;
            color: #ffffff;
            font-weight: 700;
            font-size: 11px;
            padding: 6px 14px;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s;
            font-family: 'JetBrains Mono', monospace;
        }
        .btn-toggle-auto:hover {
            background: #388bfd;
        }
        .btn-toggle-auto.off {
            background: #21262d;
            border-color: #30363d;
            color: #8b949e;
        }

        /* Botón de Historial en Header y Modales */
        .btn-history {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 5px 12px;
            background: #1c2128;
            border: 1px solid #30363d;
            border-radius: 6px;
            color: #58a6ff;
            font-size: 11px;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-history:hover {
            background: #30363d;
            border-color: #58a6ff;
            color: #ffffff;
            box-shadow: 0 0 10px rgba(88, 166, 255, 0.25);
        }
        
        /* Modal Glassmorphism */
        .modal-overlay {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(4, 7, 13, 0.85);
            backdrop-filter: blur(6px);
            -webkit-backdrop-filter: blur(6px);
            z-index: 9999;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .modal-overlay.active {
            display: flex;
        }
        .modal-box {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            width: 100%;
            max-width: 1100px;
            max-height: 88vh;
            display: flex;
            flex-direction: column;
            box-shadow: 0 20px 40px rgba(0,0,0,0.7);
            overflow: hidden;
            animation: modalFadeIn 0.2s ease-out;
        }
        @keyframes modalFadeIn {
            from { opacity: 0; transform: scale(0.97); }
            to { opacity: 1; transform: scale(1); }
        }
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 20px;
            border-bottom: 1px solid #21262d;
            background: #0d1117;
        }
        .modal-title {
            font-size: 15px;
            font-weight: 800;
            color: #ffffff;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .modal-close {
            background: transparent;
            border: none;
            color: #8b949e;
            font-size: 20px;
            cursor: pointer;
            padding: 4px 8px;
            border-radius: 4px;
            transition: all 0.15s;
        }
        .modal-close:hover {
            color: #f85149;
            background: rgba(248, 81, 73, 0.1);
        }
        .modal-toolbar {
            padding: 12px 20px;
            background: #11161d;
            border-bottom: 1px solid #21262d;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
        }
        .filter-group {
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
        }
        .filter-btn {
            background: #1c2128;
            border: 1px solid #30363d;
            color: #8b949e;
            padding: 5px 10px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
            font-family: 'JetBrains Mono', monospace;
            cursor: pointer;
            transition: all 0.15s;
        }
        .filter-btn:hover {
            color: #ffffff;
            border-color: #58a6ff;
        }
        .filter-btn.active {
            background: rgba(88, 166, 255, 0.18);
            border-color: #58a6ff;
            color: #58a6ff;
            font-weight: 700;
        }
        .search-input {
            background: #0d1117;
            border: 1px solid #30363d;
            color: #ffffff;
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 11px;
            font-family: 'JetBrains Mono', monospace;
            outline: none;
            min-width: 220px;
        }
        .search-input:focus {
            border-color: #58a6ff;
            box-shadow: 0 0 5px rgba(88, 166, 255, 0.3);
        }
        .modal-body {
            overflow-y: auto;
            flex: 1;
            padding: 0;
        }
        .modal-footer {
            padding: 12px 20px;
            background: #0d1117;
            border-top: 1px solid #21262d;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 11px;
            font-family: 'JetBrains Mono', monospace;
            color: #8b949e;
            flex-wrap: wrap;
            gap: 8px;
        }
        /* Canvas Tooltip */
        #equityTooltip {
            position: absolute;
            display: none;
            pointer-events: none;
            background: #161b22;
            border: 1px solid #58a6ff;
            border-radius: 6px;
            padding: 8px 12px;
            font-size: 11px;
            font-family: 'JetBrains Mono', monospace;
            color: #ffffff;
            box-shadow: 0 8px 24px rgba(0,0,0,0.8);
            z-index: 1000;
            white-space: nowrap;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- HEADER -->
        <div class="header">
            <div class="title-block">
                <h1>🦅 THE QUANT SNIPER & GRID DESK</h1>
                <div class="title-sub">Dual Architecture: Malla Spot Pionex (Real) + Asymmetric Swing 1H/4H (Paper)</div>
            </div>
            <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
                <button onclick="openHistoryModal()" class="btn-history">
                    📜 Historial Operaciones (<span id="btn-total-trades">--</span>)
                </button>
                <a href="/quantum" style="text-decoration: none; padding: 5px 12px; background: #131b2e; border: 1px solid #38bdf8; border-radius: 6px; color: #38bdf8; font-size: 11px; font-weight: bold; font-family: monospace; transition: all 0.2s;" target="_blank">⚛️ Comparador Cuántico (Monte Carlo) ↗</a>
                <span class="badge-live">● SISTEMA OPERATIVO</span>
                <span style="font-size: 12px; color: var(--text-dim); font-family: monospace;">Refresco 3s</span>
            </div>
        </div>

        <!-- PILAR 1 Y PILAR 2 CARDS -->
        <div class="grid-2col">
            <!-- PILAR 1: MALLA REAL PIONEX (DOGE) -->
            <div class="card" style="border-left: 4px solid var(--purple);">
                <div class="card-header">
                    <div class="card-title" style="color: var(--purple);">
                        <span>⚡ PILAR 1: MALLA PIONEX SPOT REAL (DOGE/USDT)</span>
                    </div>
                    <span class="tag tag-green">BOT EN EJECUCIÓN</span>
                </div>
                <div class="metric-box">
                    <div class="metric">
                        <div class="metric-label">Inversión Inicial</div>
                        <div class="metric-value" id="grid-invest">$69.71</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Beneficio Acumulado</div>
                        <div class="metric-value" style="color: var(--green);" id="grid-profit">+$1.84 USDT</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Arbitrajes Emparejados</div>
                        <div class="metric-value" id="grid-pairs">118</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Rango Activo</div>
                        <div class="metric-value" style="font-size: 14px;" id="grid-range">0.067 - 0.093</div>
                    </div>
                </div>
                <div style="font-size: 11px; color: var(--text-dim); font-family: monospace; line-height: 1.5;">
                    • Estado: <b style="color: #ffffff;">Reinversión Automática Activa</b> | Trailing-Up Activado (+5%).<br>
                    • Tu bot real en Pionex está 100% aislado y ganando dinero de la oscilación lateral.
                </div>
            </div>

            <!-- PILAR 2: SWING SNIPER (1H / 4H PAPER) -->
            <div class="card" style="border-left: 4px solid var(--accent);">
                <div class="card-header">
                    <div class="card-title" style="color: var(--accent);">
                        <span>🎯 PILAR 2: SWING SNIPER V2 (FUERZA RELATIVA & 15m BREAKOUT)</span>
                    </div>
                    <div style="display: flex; gap: 8px; align-items: center;">
                        <span class="tag tag-yellow" id="tier-badge">Mono-Sniper (&lt;$120)</span>
                        <span class="tag tag-green">INTERÉS COMPUESTO ACTIVO</span>
                    </div>
                </div>
                <div class="metric-box">
                    <div class="metric">
                        <div class="metric-label">Patrimonio Total (Equity)</div>
                        <div class="metric-value" id="swing-equity" style="color: #58a6ff;">$70.00</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Caja Disponible</div>
                        <div class="metric-value" id="swing-cash">$70.00</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">En Posición (Invertido)</div>
                        <div class="metric-value" id="swing-invested">$0.00</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">PnL Flotante (En Vivo)</div>
                        <div class="metric-value" id="swing-unrealized">$0.00 (0.00%)</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">PnL Realizado</div>
                        <div class="metric-value" id="swing-pnl">$0.00</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Trades Cerrados</div>
                        <div class="metric-value" id="swing-stats">0 (0W / 0L)</div>
                    </div>
                </div>
                <!-- POSICIÓN SWING ACTIVA -->
                <div id="active-box" style="margin-top: 10px;">
                    <div id="active-status"></div>
                </div>

                <!-- ÚLTIMO TRADE FINALIZADO -->
                <div id="last-trade-box" style="margin-top: 10px; background: #090d13; border: 1px solid #21262d; border-radius: 6px; padding: 8px 12px; font-family: 'JetBrains Mono', monospace; font-size: 11px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px;">
                    <span style="color: var(--text-dim); font-size: 10px; font-weight: 600;">🏆 ÚLTIMA OPERACIÓN FINALIZADA:</span>
                    <span id="last-trade-summary" style="color: #ffffff;">Consultando historial SQLite...</span>
                </div>

                <!-- CEREBRO ADAPTATIVO & AUTOPSIA POST-TRADE -->
                <div id="autopsy-box" style="margin-top: 10px; background: #0c1017; border: 1px solid #30363d; border-radius: 6px; padding: 10px 14px; font-family: 'JetBrains Mono', monospace; font-size: 11px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; flex-wrap: wrap; gap: 6px;">
                        <span style="color: #58a6ff; font-weight: 700;">🔬 CEREBRO ADAPTATIVO & AUTOPSIA POST-TRADE</span>
                        <span id="btc-regime-badge" class="tag tag-blue" style="font-size: 10px;">REGIMEN: CALCULANDO...</span>
                    </div>
                    <div id="autopsy-summary" style="color: #c9d1d9; font-size: 11px; line-height: 1.4;">
                        Analizando historial de 24 trades en SQLite. Próximo trade será clasificado automáticamente...
                    </div>
                </div>

                <!-- RADAR STATUS FEED -->
                <div style="margin-top: 8px; font-size: 11px; color: var(--text-dim); font-family: 'JetBrains Mono', monospace; display: flex; align-items: center; gap: 6px;">
                    <span style="color: #f0883e;">📡</span> <span id="radar-live-status">Iniciando radar...</span>
                </div>
            </div>
        </div>

        <!-- PANORAMA Y CURVA DE PATRIMONIO HISTÓRICA -->
        <div class="card" style="margin-bottom: 24px; border-left: 4px solid #38bdf8;">
            <div class="card-header" style="flex-wrap: wrap; gap: 10px;">
                <div class="card-title" style="color: #38bdf8;">
                    <span>📈 EVOLUCIÓN HISTÓRICA DEL PATRIMONIO (PANORAMA DESDE EL INICIO)</span>
                </div>
                <div style="display: flex; gap: 10px; align-items: center;">
                    <button onclick="openHistoryModal()" class="btn-history" style="padding: 4px 10px; font-size: 10px;">
                        🔍 Ver Lista de Movimientos
                    </button>
                    <span style="font-size: 11px; color: var(--text-dim); font-family: monospace;" id="chart-point-count">-- Cierres</span>
                </div>
            </div>
            
            <div class="metric-box" style="grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); margin-bottom: 12px;">
                <div class="metric" style="padding: 8px 12px;">
                    <div class="metric-label" style="font-size: 10px;">Capital Inicial</div>
                    <div class="metric-value" style="font-size: 14px;" id="pan-init">$70.00</div>
                </div>
                <div class="metric" style="padding: 8px 12px;">
                    <div class="metric-label" style="font-size: 10px;">Patrimonio Actual</div>
                    <div class="metric-value" style="font-size: 14px; color: #58a6ff;" id="pan-current">--</div>
                </div>
                <div class="metric" style="padding: 8px 12px;">
                    <div class="metric-label" style="font-size: 10px;">PnL Acumulado</div>
                    <div class="metric-value" style="font-size: 14px;" id="pan-pnl">--</div>
                </div>
                <div class="metric" style="padding: 8px 12px;">
                    <div class="metric-label" style="font-size: 10px;">Max Drawdown</div>
                    <div class="metric-value" style="font-size: 14px; color: #f85149;" id="pan-dd">--</div>
                </div>
                <div class="metric" style="padding: 8px 12px;">
                    <div class="metric-label" style="font-size: 10px;">Efectividad (Winrate)</div>
                    <div class="metric-value" style="font-size: 14px; color: #3fb950;" id="pan-winrate">--%</div>
                </div>
            </div>

            <!-- Canvas Container with Tooltip -->
            <div style="position: relative; width: 100%; height: 160px;">
                <canvas id="equityCanvas" style="width: 100%; height: 160px; display: block; border-radius: 6px; background: #0c1017; border: 1px solid #21262d;"></canvas>
                <div id="equityTooltip"></div>
            </div>

            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px; font-size: 10px; color: var(--text-dim); font-family: 'JetBrains Mono', monospace; flex-wrap: wrap; gap: 8px;">
                <div style="display: flex; gap: 14px;">
                    <span><span style="color: #38bdf8;">━</span> Curva de Patrimonio</span>
                    <span><span style="color: #8b949e; border-bottom: 1px dashed #8b949e;">┅</span> Base Inicial ($70.00)</span>
                    <span><span style="color: #3fb950;">●</span> Trade Ganador</span>
                    <span><span style="color: #f85149;">●</span> Trade Perdedor</span>
                </div>
                <div>💡 Pasa el cursor sobre los puntos para ver el detalle de cada trade.</div>
            </div>
        </div>

        <!-- CONSOLA DE CONTROL INTERACTIVA (FADERS & MODO AUTOMÁTICO ATR) -->
        <div class="card" style="margin-bottom: 24px; border-left: 4px solid #f0883e;">
            <div class="card-header" style="flex-wrap: wrap; gap: 12px;">
                <div class="card-title" style="color: #f0883e;">
                    <span>🎛️ CONSOLA DE CALIBRACIÓN EN VIVO (FADERS & GESTIÓN DE RIESGO)</span>
                </div>
                <div style="display: flex; gap: 10px; align-items: center;">
                    <span id="cfg-sync-badge" class="tag tag-green" style="font-size: 11px;">● SINCRONIZADO</span>
                    <button id="btn-auto-atr" onclick="toggleAutoAtr()" class="btn-toggle-auto">
                        🤖 MODO AUTOMÁTICO (ATR DINÁMICO): ON
                    </button>
                </div>
            </div>
            
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px;">
                <!-- Fader 1: Umbral Break-Even -->
                <div class="fader-group">
                    <div class="fader-header">
                        <span class="fader-label">🛡️ Umbral Break-Even:</span>
                        <span class="fader-val" id="val-be-trigger">+1.60%</span>
                    </div>
                    <input type="range" id="slider-be-trigger" min="0.5" max="3.5" step="0.1" value="1.6" oninput="updateFaderUI('be_trigger_pct', this.value)" onchange="sendSettingsUpdate()">
                    <div class="fader-sub">Ganancia requerida para subir stop a coste cero (+0.20%).</div>
                </div>

                <!-- Fader 2: Stop Loss ATR -->
                <div class="fader-group">
                    <div class="fader-header">
                        <span class="fader-label">🛑 Stop Loss (ATR 15m):</span>
                        <span class="fader-val" id="val-stop-atr">1.2x ATR</span>
                    </div>
                    <input type="range" id="slider-stop-atr" min="0.8" max="2.5" step="0.1" value="1.2" oninput="updateFaderUI('stop_atr_mult', this.value)" onchange="sendSettingsUpdate()">
                    <div class="fader-sub">Distancia inicial de protección calculada en base a volatilidad.</div>
                </div>

                <!-- Fader 3: Target Profit ATR -->
                <div class="fader-group">
                    <div class="fader-header">
                        <span class="fader-label">🎯 Target Profit (ATR 15m):</span>
                        <span class="fader-val" id="val-target-atr">3.0x ATR</span>
                    </div>
                    <input type="range" id="slider-target-atr" min="1.5" max="5.0" step="0.1" value="3.0" oninput="updateFaderUI('target_atr_mult', this.value)" onchange="sendSettingsUpdate()">
                    <div class="fader-sub">Toma de ganancia simétrica por volatilidad (R:R objetivo).</div>
                </div>

                <!-- Fader 4: Distancia Trailing ATR -->
                <div class="fader-group">
                    <div class="fader-header">
                        <span class="fader-label">📈 Distancia Trailing (ATR 15m):</span>
                        <span class="fader-val" id="val-trail-atr">1.5x ATR</span>
                    </div>
                    <input type="range" id="slider-trail-atr" min="0.5" max="2.5" step="0.1" value="1.5" oninput="updateFaderUI('trail_distance_atr', this.value)" onchange="sendSettingsUpdate()">
                    <div class="fader-sub">Holgura detrás del máximo para dejar correr ganancias hacia +3.0x ATR.</div>
                </div>

                <!-- Fader 5: Score Mínimo -->
                <div class="fader-group">
                    <div class="fader-header">
                        <span class="fader-label">⚡ Score Mínimo Entrada:</span>
                        <span class="fader-val" id="val-min-score">80 pts</span>
                    </div>
                    <input type="range" id="slider-min-score" min="50" max="95" step="1" value="80" oninput="updateFaderUI('min_score', this.value)" onchange="sendSettingsUpdate()">
                    <div class="fader-sub">Puntaje de convicción mínima (ruptura + volumen + RS + velas).</div>
                </div>

                <!-- Fader 6: Cooldown Post-Stop -->
                <div class="fader-group">
                    <div class="fader-header">
                        <span class="fader-label">⏱️ Cooldown Anti-Ametralladora:</span>
                        <span class="fader-val" id="val-cooldown">300 seg</span>
                    </div>
                    <input type="range" id="slider-cooldown" min="30" max="900" step="15" value="300" oninput="updateFaderUI('post_stop_cooldown_s', this.value)" onchange="sendSettingsUpdate()">
                    <div class="fader-sub">Tiempo de enfriamiento en el par tras tocar Stop Loss.</div>
                </div>
            </div>
        </div>

        <!-- RADAR MATRIX V2 -->
        <div class="card" style="margin-bottom: 24px;">
            <div class="card-header">
                <div class="card-title">
                    <span>📊 RADAR CUANTITATIVO V2: FUERZA RELATIVA & RUPTURAS 15m</span>
                </div>
                <span style="font-size: 11px; color: var(--text-dim); font-family: monospace;">Escáner de Todo Binance + Anti-Cuchillo + R:R &gt;= 2.0:1</span>
            </div>
            <div style="overflow-x: auto;">
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Par</th>
                            <th>Precio</th>
                            <th>RS vs BTC</th>
                            <th>Ruptura 15m</th>
                            <th>Vol Spike</th>
                            <th>Velas 15m</th>
                            <th>RSI 15m</th>
                            <th>Tendencia 1H</th>
                            <th>Target / Stop</th>
                            <th>R:R</th>
                            <th>Puntaje</th>
                            <th>Estado</th>
                        </tr>
                    </thead>
                    <tbody id="radar-tbody">
                        <tr><td colspan="13" style="text-align: center; color: var(--text-dim); padding: 20px;">Escaneando candidatos con Fuerza Relativa y Rupturas 15m...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- EVENT LOG STREAM -->
        <div class="card">
            <div class="card-header">
                <div class="card-title">
                    <span>⚡ REGISTRO DE EVENTOS & DISPAROS CUANTITATIVOS</span>
                </div>
            </div>
            <div class="terminal" id="terminal-feed">
                <div class="log-row"><span class="log-time">[--:--:--]</span> <span class="log-info">Iniciando terminal Swing Sniper...</span></div>
            </div>
        </div>

        <!-- MODAL HISTORIAL DE OPERACIONES (COMPACTO / VENTANA EMERGENTE) -->
        <div id="history-modal" class="modal-overlay" onclick="handleModalOverlayClick(event)">
            <div class="modal-box" onclick="event.stopPropagation()">
                <div class="modal-header">
                    <div class="modal-title">
                        <span>📜 HISTORIAL COMPLETO DE OPERACIONES REGISTRADAS</span>
                        <span class="tag tag-blue" id="modal-trade-count">0 Operaciones</span>
                    </div>
                    <button class="modal-close" onclick="closeHistoryModal()" title="Cerrar ventana">✕</button>
                </div>
                
                <div class="modal-toolbar">
                    <div class="filter-group">
                        <button class="filter-btn active" onclick="setHistoryFilter('all', this)">Todos</button>
                        <button class="filter-btn" onclick="setHistoryFilter('closed', this)">Solo Cierres (PnL)</button>
                        <button class="filter-btn" onclick="setHistoryFilter('win', this)">Ganadores 🟢</button>
                        <button class="filter-btn" onclick="setHistoryFilter('loss', this)">Perdedores 🔴</button>
                        <button class="filter-btn" onclick="setHistoryFilter('swing', this)">Swings</button>
                        <button class="filter-btn" onclick="setHistoryFilter('grid', this)">Mallas</button>
                    </div>
                    <input type="text" id="history-search" class="search-input" placeholder="🔍 Filtrar por par, modo o motivo..." oninput="filterHistoryTable()">
                </div>

                <div class="modal-body">
                    <table style="margin: 0;">
                        <thead style="position: sticky; top: 0; background: #161b22; z-index: 2;">
                            <tr>
                                <th style="width: 45px;">#ID</th>
                                <th>Fecha/Hora</th>
                                <th>Par</th>
                                <th>Modo</th>
                                <th>Lado</th>
                                <th>Precio</th>
                                <th>Capital</th>
                                <th>PnL Neto</th>
                                <th>Nota / Motivo</th>
                            </tr>
                        </thead>
                        <tbody id="history-tbody">
                            <tr><td colspan="9" style="text-align: center; color: var(--text-dim); padding: 24px;">Cargando historial de SQLite...</td></tr>
                        </tbody>
                    </table>
                </div>

                <div class="modal-footer">
                    <div>
                        Filtrados: <b id="modal-filtered-count" style="color: #ffffff;">--</b> de <span id="modal-total-count">--</span> registros
                    </div>
                    <div>
                        PnL Cierres: <b id="modal-sum-pnl" style="color: #ffffff;">$0.00</b> | Winrate: <b id="modal-sum-wr" style="color: #3fb950;">--%</b>
                    </div>
                    <button onclick="closeHistoryModal()" class="filter-btn" style="background: #21262d; color: #ffffff;">Cerrar [ESC]</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        let isUserDraggingFader = false;
        let currentSettings = { auto_atr_mode: true };

        function updateFaderUI(param, val) {
            isUserDraggingFader = true;
            if (param === 'be_trigger_pct') {
                document.getElementById('val-be-trigger').innerText = '+' + Number(val).toFixed(2) + '%';
            } else if (param === 'stop_atr_mult') {
                document.getElementById('val-stop-atr').innerText = Number(val).toFixed(1) + 'x ATR';
            } else if (param === 'target_atr_mult') {
                document.getElementById('val-target-atr').innerText = Number(val).toFixed(1) + 'x ATR';
            } else if (param === 'trail_distance_atr') {
                document.getElementById('val-trail-atr').innerText = Number(val).toFixed(1) + 'x ATR';
            } else if (param === 'min_score') {
                document.getElementById('val-min-score').innerText = Math.round(val) + ' pts';
            } else if (param === 'post_stop_cooldown_s') {
                document.getElementById('val-cooldown').innerText = Math.round(val) + ' seg';
            }
        }

        async function sendSettingsUpdate() {
            isUserDraggingFader = false;
            const payload = {
                be_trigger_pct: parseFloat(document.getElementById('slider-be-trigger').value) / 100.0,
                stop_atr_mult: parseFloat(document.getElementById('slider-stop-atr').value),
                target_atr_mult: parseFloat(document.getElementById('slider-target-atr').value),
                trail_distance_atr: parseFloat(document.getElementById('slider-trail-atr').value),
                min_score: parseFloat(document.getElementById('slider-min-score').value),
                post_stop_cooldown_s: parseInt(document.getElementById('slider-cooldown').value),
                auto_atr_mode: currentSettings.auto_atr_mode !== undefined ? currentSettings.auto_atr_mode : true
            };
            const badge = document.getElementById('cfg-sync-badge');
            if (badge) {
                badge.innerText = '⏳ GUARDANDO...';
                badge.className = 'tag tag-yellow';
            }
            try {
                const res = await fetch('/api/settings', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                if (res.ok) {
                    if (badge) {
                        badge.innerText = '✅ APLICADO';
                        badge.className = 'tag tag-green';
                        setTimeout(() => { if (badge) badge.innerText = '● SINCRONIZADO'; }, 2000);
                    }
                }
            } catch (err) {
                console.error("Error guardando settings:", err);
            }
        }

        async function toggleAutoAtr() {
            const newMode = !currentSettings.auto_atr_mode;
            const payload = { auto_atr_mode: newMode };
            if (newMode) {
                // Restablecer valores óptimos para Modo Automático ATR (Opción B)
                payload.be_trigger_pct = 0.016;
                payload.stop_atr_mult = 1.2;
                payload.target_atr_mult = 3.0;
                payload.trail_distance_atr = 1.5;
                payload.min_score = 80.0;
                payload.post_stop_cooldown_s = 300;
            }
            try {
                await fetch('/api/settings', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                updateDashboard();
            } catch (err) {
                console.error("Error cambiando modo auto ATR:", err);
            }
        }

        async function updateDashboard() {
            try {
                const res = await fetch('/api/status');
                const d = await res.json();

                // 0. Sincronizar Consola de Control (Faders y Modo Auto)
                if (d.settings) {
                    currentSettings = d.settings;
                    const btn = document.getElementById('btn-auto-atr');
                    if (btn) {
                        if (d.settings.auto_atr_mode) {
                            btn.innerText = '🤖 MODO AUTOMÁTICO (ATR DINÁMICO): ON';
                            btn.className = 'btn-toggle-auto';
                        } else {
                            btn.innerText = '🎚️ MODO MANUAL (CONTROL POR FADERS)';
                            btn.className = 'btn-toggle-auto off';
                        }
                    }

                    if (!isUserDraggingFader) {
                        const beVal = (d.settings.be_trigger_pct * 100.0).toFixed(1);
                        document.getElementById('slider-be-trigger').value = beVal;
                        document.getElementById('val-be-trigger').innerText = '+' + Number(beVal).toFixed(2) + '%';

                        document.getElementById('slider-stop-atr').value = d.settings.stop_atr_mult;
                        document.getElementById('val-stop-atr').innerText = Number(d.settings.stop_atr_mult).toFixed(1) + 'x ATR';

                        document.getElementById('slider-target-atr').value = d.settings.target_atr_mult;
                        document.getElementById('val-target-atr').innerText = Number(d.settings.target_atr_mult).toFixed(1) + 'x ATR';

                        document.getElementById('slider-trail-atr').value = d.settings.trail_distance_atr;
                        document.getElementById('val-trail-atr').innerText = Number(d.settings.trail_distance_atr).toFixed(1) + 'x ATR';

                        document.getElementById('slider-min-score').value = d.settings.min_score;
                        document.getElementById('val-min-score').innerText = Math.round(d.settings.min_score) + ' pts';

                        document.getElementById('slider-cooldown').value = d.settings.post_stop_cooldown_s;
                        document.getElementById('val-cooldown').innerText = Math.round(d.settings.post_stop_cooldown_s) + ' seg';
                    }
                }

                // 1. Malla Real
                if (d.real_grid) {
                    const g = d.real_grid;
                    document.getElementById('grid-invest').innerText = '$' + Number(g.investment || 69.71).toFixed(2);
                    document.getElementById('grid-profit').innerText = '+' + Number(g.total_profit_usdt || 1.84).toFixed(2) + ' USDT';
                    document.getElementById('grid-pairs').innerText = g.paired_count || 118;
                    document.getElementById('grid-range').innerText = (g.range_bottom || 0.067) + ' - ' + (g.range_top || 0.093);
                }

                // 2. Swing Paper
                const cash = Number(d.cash || 0);
                const equity = Number(d.equity || cash);
                const invested = Number(d.invested || 0);
                const unPnl = Number(d.unrealized_pnl || 0);
                const unPnlPct = Number(d.unrealized_pnl_pct || 0);
                const realPnl = Number(d.stats?.pnl || 0);

                document.getElementById('swing-equity').innerText = '$' + equity.toFixed(2);
                document.getElementById('swing-cash').innerText = '$' + cash.toFixed(2);
                document.getElementById('swing-invested').innerText = '$' + invested.toFixed(2);
                
                const unEl = document.getElementById('swing-unrealized');
                const unSign = unPnl >= 0 ? '+' : '';
                unEl.innerText = `${unSign}$${unPnl.toFixed(2)} (${unSign}${unPnlPct.toFixed(2)}%)`;
                unEl.style.color = unPnl >= 0 ? '#3fb950' : '#f85149';

                const pnlEl = document.getElementById('swing-pnl');
                pnlEl.innerText = (realPnl >= 0 ? '+' : '') + realPnl.toFixed(2) + ' USDT';
                pnlEl.style.color = realPnl >= 0 ? '#3fb950' : '#f85149';
                document.getElementById('swing-stats').innerText = `${d.stats?.total || 0} (${d.stats?.wins || 0}W / ${d.stats?.losses || 0}L)`;

                // Tier de Capital y Diversificación
                if (d.tier_mode) {
                    const tb = document.getElementById('tier-badge');
                    if (tb) {
                        tb.innerText = d.tier_mode;
                        tb.className = 'tag ' + (d.max_concurrent_trades >= 3 ? 'tag-green' : (d.max_concurrent_trades >= 2 ? 'tag-green' : 'tag-yellow'));
                    }
                }

                // Posiciones Activas (Multi-Trade / Diversificación al Unísono)
                const actEl = document.getElementById('active-status');
                const trades = d.active_trades || (d.active_trade ? [d.active_trade] : []);
                if (trades.length > 0) {
                    let tradesHtml = '';
                    trades.forEach(tr => {
                        let badge = '<span class="tag tag-yellow">🟡 RIESGO INICIAL CONTROLADO</span>';
                        if (tr.is_trailing_active) {
                            badge = '<span class="tag tag-green">📈 TRAILING PROFIT ACTIVO (ATR Chandelier)</span>';
                        } else if (tr.is_be_active) {
                            badge = '<span class="tag tag-green">🛡️ BREAK-EVEN ACTIVO (Riesgo Cero)</span>';
                        }
                        const liveP = Number(tr.current_price || tr.entry_price).toFixed(4);
                        const entP = Number(tr.entry_price).toFixed(4);
                        const tgtP = Number(tr.target_price).toFixed(4);
                        const stpP = Number(tr.stop_price).toFixed(4);
                        const highP = Number(tr.highest_price || tr.entry_price).toFixed(4);
                        const trPnl = Number(tr.unrealized_pnl || 0);
                        const trPct = Number(tr.unrealized_pnl_pct || 0);
                        const trPnlStr = (trPnl >= 0 ? '+' : '') + trPnl.toFixed(4) + ' USDT (' + (trPct >= 0 ? '+' : '') + trPct.toFixed(2) + '%)';
                        const trPnlColor = trPnl >= 0 ? '#3fb950' : '#f85149';
                        const stopDiffPct = ((Number(tr.stop_price) - Number(tr.entry_price)) / Number(tr.entry_price) * 100).toFixed(2);
                        const stopDiffSign = Number(stopDiffPct) >= 0 ? '+' : '';

                        tradesHtml += `
                        <div style="background:#161b22; border:1px solid #30363d; border-radius:8px; padding:12px; margin-bottom:12px;">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; border-bottom:1px solid #21262d; padding-bottom:6px;">
                                <span style="font-weight:bold; color:#58a6ff; font-size:13px;">🦅 POSICIÓN EN CURSO: ${tr.symbol}</span>
                                ${badge}
                            </div>
                            <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap:8px; margin-bottom:8px;">
                                <div><span style="color:var(--text-dim); font-size:10px;">PORTE (TAMAÑO):</span><br><b>${tr.amount} ${tr.symbol.split('/')[0]}</b> <span style="color:var(--text-dim); font-size:11px;">($${Number(tr.capital).toFixed(2)})</span></div>
                                <div><span style="color:var(--text-dim); font-size:10px;">PRECIO ENTRADA:</span><br><b>$${entP}</b></div>
                                <div><span style="color:var(--text-dim); font-size:10px;">PRECIO ACTUAL:</span><br><b style="color:#58a6ff;">$${liveP}</b> <span style="color:var(--text-dim); font-size:11px;">(Max: $${highP})</span></div>
                                <div><span style="color:var(--text-dim); font-size:10px;">PNL FLOTANTE:</span><br><b style="color:${trPnlColor};">${trPnlStr}</b></div>
                            </div>
                            <div style="background:#0d1117; border-radius:6px; padding:8px; display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; font-size:11px; border:1px solid #21262d;">
                                <div>🎯 <b>Target Dinámico:</b> <span style="color:#3fb950; font-weight:bold;">$${tgtP} (+${(tr.target_pct*100).toFixed(2)}%)</span></div>
                                <div>🛡️ <b>Stop Dinámico ATR:</b> <span style="color:${Number(stopDiffPct) >= 0 ? '#3fb950' : '#f85149'}; font-weight:bold;">$${stpP} (${stopDiffSign}${stopDiffPct}%)</span></div>
                                <div>📐 <b>R:R:</b> <span style="color:#3fb950; font-weight:bold;">${tr.rr_ratio}:1</span></div>
                                <div>🌊 <b>ATR 1H:</b> <span style="color:var(--text-main); font-weight:bold;">${tr.atr_pct}%</span></div>
                            </div>
                        </div>`;
                    });
                    actEl.innerHTML = tradesHtml;
                } else if (d.active_grid) {
                    const g = d.active_grid;
                    const liveP = Number(g.current_price || g.midpoint).toFixed(4);
                    const avgP = Number(g.average_entry || g.midpoint).toFixed(4);
                    const suppP = Number(g.channel_support).toFixed(4);
                    const resP = Number(g.channel_resistance).toFixed(4);
                    const killP = Number(g.kill_switch_price).toFixed(4);
                    const gPnl = Number(g.unrealized_pnl || 0);
                    const gPct = g.invested_capital > 0 ? (gPnl / g.invested_capital * 100) : 0;
                    const pnlCol = gPnl >= 0 ? '#3fb950' : '#f85149';
                    const pnlSign = gPnl >= 0 ? '+' : '';

                    let lvlsHtml = '';
                    (g.levels || []).forEach((lvl, i) => {
                        const statusColor = lvl.status === 'FILLED' ? '#3fb950' : '#8b949e';
                        const statusIcon = lvl.status === 'FILLED' ? '✅' : '⏳';
                        lvlsHtml += `<div style="background:#090d13; border:1px solid #21262d; border-radius:4px; padding:4px 8px; font-size:10px;">
                            ${statusIcon} <b>Nivel ${lvl.level_idx+1}:</b> $${Number(lvl.price).toFixed(4)} ($${Number(lvl.capital).toFixed(2)}) - <span style="color:${statusColor};">${lvl.status}</span>
                        </div>`;
                    });

                    actEl.innerHTML = `
                    <div style="background:#161b22; border:1px solid #d29922; border-radius:8px; padding:12px; margin-bottom:12px;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; border-bottom:1px solid #21262d; padding-bottom:6px; flex-wrap:wrap; gap:6px;">
                            <span style="font-weight:bold; color:#f0883e; font-size:13px;">🟡 MALLA ACOTADA EN CHOP: ${g.symbol}</span>
                            <span class="tag tag-yellow">Hurst H: ${g.hurst_exponent} (Reversión a la Media)</span>
                        </div>
                        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap:8px; margin-bottom:8px;">
                            <div><span style="color:var(--text-dim); font-size:10px;">INVENTARIO / CAPITAL:</span><br><b>${g.filled_count}/3 Niveles</b> <span style="color:var(--text-dim); font-size:11px;">($${Number(g.invested_capital).toFixed(2)} USDT)</span></div>
                            <div><span style="color:var(--text-dim); font-size:10px;">PRECIO MEDIO ENTRADA:</span><br><b>$${avgP}</b></div>
                            <div><span style="color:var(--text-dim); font-size:10px;">PRECIO ACTUAL:</span><br><b style="color:#58a6ff;">$${liveP}</b></div>
                            <div><span style="color:var(--text-dim); font-size:10px;">PNL FLOTANTE:</span><br><b style="color:${pnlCol};">${pnlSign}$${gPnl.toFixed(4)} (${pnlSign}${gPct.toFixed(2)}%)</b></div>
                        </div>
                        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:6px; margin-bottom:8px;">
                            ${lvlsHtml}
                        </div>
                        <div style="background:#0d1117; border-radius:6px; padding:8px; display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; font-size:11px; border:1px solid #21262d;">
                            <div>🎯 <b>Cosecha Techo (Resistencia):</b> <span style="color:#3fb950; font-weight:bold;">$${resP}</span></div>
                            <div>🛡️ <b>Piso Canal (Soporte):</b> <span style="color:#58a6ff; font-weight:bold;">$${suppP}</span></div>
                            <div>🛑 <b>Kill-Switch Estricto:</b> <span style="color:#f85149; font-weight:bold;">$${killP} (Cierre total a mercado)</span></div>
                        </div>
                    </div>`;
                } else {
                    actEl.innerHTML = `
                    <div style="background:#0d1117; border: 1px dashed #30363d; border-radius:8px; padding:12px; text-align:center;">
                        <div style="font-size:12px; font-weight:700; color:#8b949e; margin-bottom:3px;">
                            ⚪ SIN OPERACIÓN EN CURSO (100% EN CAJA: $${cash.toFixed(2)} USDT)
                        </div>
                        <div style="font-size:11px; color:var(--text-dim);">
                            Capital libre protegido. El radar está buscando confirmación de ruptura con volumen.
                        </div>
                    </div>`;
                }

                // 2.1 Resumen del Último Trade Cerrado
                const lastTrEl = document.getElementById('last-trade-summary');
                if (lastTrEl && d.last_closed_trade) {
                    const lt = d.last_closed_trade;
                    const pnlVal = Number(lt.pnl || 0);
                    const pnlSign = pnlVal >= 0 ? '+' : '';
                    const pnlCol = pnlVal >= 0 ? '#3fb950' : '#f85149';
                    const noteStr = lt.note ? ` | ${lt.note}` : '';
                    lastTrEl.innerHTML = `
                        <span style="font-weight:bold; color:#58a6ff;">${lt.symbol}</span> 
                        <span style="color:${pnlCol}; font-weight:bold;">${pnlSign}$${pnlVal.toFixed(4)} USDT</span> 
                        <span style="color:var(--text-dim); font-size:10px;">@ $${Number(lt.price).toFixed(4)}${noteStr}</span>
                    `;
                }

                // 2.2 Radar Scanner Status
                const radarLiveEl = document.getElementById('radar-live-status');
                if (radarLiveEl) {
                    radarLiveEl.innerText = d.status_msg || 'Escaneando Binance...';
                }

                // 2.3 Régimen Macro de Bitcoin y Autopsia Post-Trade
                const btcBadge = document.getElementById('btc-regime-badge');
                if (btcBadge && d.btc_context) {
                    const btc = d.btc_context;
                    if (btc.regime === 'BULLISH_EXPANSION') {
                        btcBadge.className = 'tag tag-green';
                        btcBadge.innerText = '🟢 BTC: EXPANSIÓN ALCISTA';
                    } else if (btc.regime === 'CHOP_COMPRESSION') {
                        btcBadge.className = 'tag tag-purple';
                        btcBadge.innerText = '🟡 BTC: COMPRESIÓN CHOP (Falsas Rupturas)';
                    } else if (btc.regime === 'BEARISH_DUMP') {
                        btcBadge.className = 'tag tag-red';
                        btcBadge.innerText = '🔴 BTC: CORRECCIÓN DUMP (BLOQUEO)';
                    } else {
                        btcBadge.className = 'tag tag-blue';
                        btcBadge.innerText = `🔵 BTC: ${btc.regime}`;
                    }
                }

                const autopsySummaryEl = document.getElementById('autopsy-summary');
                if (autopsySummaryEl) {
                    if (d.recent_autopsies && d.recent_autopsies.length > 0) {
                        const topA = d.recent_autopsies[0];
                        const pnlSign = Number(topA.pnl) >= 0 ? '+' : '';
                        const col = Number(topA.pnl) >= 0 ? '#3fb950' : '#f85149';
                        autopsySummaryEl.innerHTML = `
                            <div style="display:flex; justify-content:space-between; margin-bottom:4px; flex-wrap:wrap; gap:4px;">
                                <span><strong>Última Autopsia:</strong> <span style="color:#58a6ff;">${topA.symbol}</span> | <span style="color:${col}; font-weight:bold;">${pnlSign}$${Number(topA.pnl).toFixed(4)} USDT</span> | Clase: <span class="tag tag-purple" style="font-size:9px;">${topA.classification}</span></span>
                                <span style="color:var(--text-dim); font-size:10px;">MFE: +${Number(topA.mfe_pct).toFixed(2)}% | MAE: ${Number(topA.mae_pct).toFixed(2)}%</span>
                            </div>
                            <div style="color:#8b949e; font-size:10px;">💡 <em>${topA.lesson_learned}</em> &rarr; <span style="color:#58a6ff;">${topA.adaptive_action}</span></div>
                        `;
                    } else {
                        const btcRegimeDesc = (d.btc_context && d.btc_context.regime_desc) ? d.btc_context.regime_desc : 'Monitoreo activo.';
                        autopsySummaryEl.innerHTML = `<span style="color:#8b949e;">📡 Contexto BTC: <em>${btcRegimeDesc}</em> | Piso de Stop mínimo 1.20% activo para filtrar ruido.</span>`;
                    }
                }

                // Título de pestaña interactivo con PnL en vivo
                if (trades.length > 0) {
                    const topTr = trades[0];
                    const sign = (topTr.unrealized_pnl >= 0 ? '+' : '');
                    document.title = `🟢 ${topTr.symbol.split('/')[0]} (${sign}${Number(topTr.unrealized_pnl_pct || 0).toFixed(2)}%) | THE QUANT SNIPER`;
                } else {
                    document.title = `🦅 $${equity.toFixed(2)} | THE QUANT SNIPER`;
                }

                // 3. Radar Table V2 (Con resaltado si el activo está en posición abierta)
                const activeMap = {};
                trades.forEach(t => { activeMap[t.symbol] = t; });

                const tbody = document.getElementById('radar-tbody');
                if (tbody && d.radar_telemetry && d.radar_telemetry.length > 0) {
                    let rows = '';
                    d.radar_telemetry.forEach((c, idx) => {
                        const inPos = activeMap[c.symbol];
                        const rsSign = (c.rs_vs_btc >= 0 ? '+' : '');
                        const rsColor = c.rs_vs_btc >= 1.0 ? '#3fb950' : (c.rs_vs_btc >= 0 ? '#58a6ff' : '#f85149');
                        const brkTag = c.is_momentum_ignition ? '<span class="tag tag-purple" style="font-weight:bold; background:rgba(187,128,255,0.25); border:1px solid #bc8cff; color:#d2a8ff;">🚀 IGNICIÓN</span>' : (c.breakout ? '<span class="tag tag-green">RUPTURA</span>' : '<span class="tag tag-gray">NO</span>');
                        const volColor = c.vol_spike >= 1.3 ? '#3fb950' : (c.vol_spike >= 1.0 ? '#d29922' : '#8b949e');
                        const candleTag = c.double_green ? '<span style="color:#3fb950; font-weight:600;">2 Verdes</span>' : (c.is_green ? '<span style="color:#3fb950;">1 Verde</span>' : '<span style="color:#f85149;">Roja</span>');
                        const trendTag = c.trend_1h ? '<span class="tag tag-green">ALCISTA</span>' : '<span class="tag tag-gray">BAJISTA</span>';
                        
                        let statusBadge = `<span class="tag ${c.is_momentum_ignition ? 'tag-purple' : (c.trigger_ready ? 'tag-green' : (c.score >= 50 ? 'tag-yellow' : 'tag-gray'))}">${c.status}</span>`;
                        let trStyle = '';
                        if (inPos) {
                            const pnlSign = inPos.unrealized_pnl >= 0 ? '+' : '';
                            statusBadge = `<span class="tag tag-green" style="font-weight:bold; background:rgba(63,185,80,0.3);">🦅 EN POSICIÓN (${pnlSign}${Number(inPos.unrealized_pnl_pct).toFixed(2)}%)</span>`;
                            trStyle = 'style="background: rgba(88, 166, 255, 0.15); font-weight: bold; border-left: 3px solid #58a6ff;"';
                        }
                        
                        rows += `<tr ${trStyle}>
                            <td>${idx + 1}</td>
                            <td><b>${c.symbol.split('/')[0]}</b></td>
                            <td>$${Number(c.price).toFixed(4)}</td>
                            <td style="color:${rsColor}; font-weight:bold;">${rsSign}${c.rs_vs_btc}pp</td>
                            <td>${brkTag}</td>
                            <td style="color:${volColor}; font-weight:bold;">${c.vol_spike}x</td>
                            <td>${candleTag}</td>
                            <td><span style="color:${c.rsi_15m >= 40 && c.rsi_15m <= 65 ? '#3fb950' : '#c9d1d9'}">${c.rsi_15m}</span></td>
                            <td>${trendTag}</td>
                            <td>+${c.target_pct}% / -${c.stop_pct}%</td>
                            <td style="color:#3fb950; font-weight:bold;">${c.rr_ratio} : 1</td>
                            <td><b>${c.score}</b></td>
                            <td>${statusBadge}</td>
                        </tr>`;
                    });
                    tbody.innerHTML = rows;
                }

                // 4. Logs (Eventos más recientes arriba de todo con badge)
                const term = document.getElementById('terminal-feed');
                if (term && d.events && d.events.length > 0) {
                    let logHtml = '';
                    d.events.forEach((l, idx) => {
                        const cl = l.type === 'trade' ? 'log-trade' : 'log-info';
                        const badge = idx === 0 ? '<span class="tag tag-green" style="font-size:9px; padding:1px 4px; margin-right:6px;">ÚLTIMO</span>' : '';
                        logHtml += `<div class="log-row">${badge}<span class="log-time">[${l.time}]</span> <span class="${cl}">${l.text}</span></div>`;
                    });
                    term.innerHTML = logHtml;
                }
            } catch (e) {
                console.error("Dashboard poll error:", e);
            }

            // Refresco periódico del historial (cada 9 segundos)
            historyPollCycle++;
            if (!fullHistory || historyPollCycle % 3 === 0) {
                loadHistoryData();
            }
        }

        // ==========================================
        // GESTIÓN DE HISTORIAL Y CURVA DE PATRIMONIO
        // ==========================================
        let fullHistory = null;
        let activeHistoryFilter = 'all';
        let chartDataPoints = [];
        let historyPollCycle = 0;

        async function loadHistoryData() {
            try {
                const res = await fetch('/api/history');
                if (!res.ok) return;
                fullHistory = await res.json();
                
                // Actualizar contador en botón de Header
                const totalBtnCount = document.getElementById('btn-total-trades');
                if (totalBtnCount && fullHistory.trades) {
                    totalBtnCount.innerText = fullHistory.trades.length;
                }

                // Renderizar Curva de Patrimonio Panorama
                if (fullHistory.equity_curve && fullHistory.equity_curve.length > 0) {
                    renderEquityChart(fullHistory.equity_curve);
                    updatePanoramaStats(fullHistory);
                }

                // Si el modal está abierto, sincronizar su tabla
                const modal = document.getElementById('history-modal');
                if (modal && modal.classList.contains('active')) {
                    renderHistoryTable();
                }
            } catch (err) {
                console.error("Error al cargar historial:", err);
            }
        }

        function updatePanoramaStats(data) {
            const curve = data.equity_curve || [];
            if (curve.length === 0) return;
            const initEq = 70.0;
            const lastPt = curve[curve.length - 1];
            const currEq = lastPt.equity;
            const netPnl = currEq - initEq;
            const pnlPct = (netPnl / initEq) * 100.0;

            // Calcular Max Drawdown histórico
            let peak = initEq;
            let maxDd = 0.0;
            curve.forEach(pt => {
                if (pt.equity > peak) peak = pt.equity;
                const dd = (pt.equity - peak) / peak * 100.0;
                if (dd < maxDd) maxDd = dd;
            });

            // Winrate y estadísticas de trades cerrados
            let wins = 0;
            let closedCount = 0;
            curve.slice(1).forEach(pt => {
                closedCount++;
                if (pt.pnl > 0) wins++;
            });
            const wr = closedCount > 0 ? (wins / closedCount * 100.0).toFixed(1) : '0.0';

            const initEl = document.getElementById('pan-init');
            if (initEl) initEl.innerText = '$' + initEq.toFixed(2);

            const curEl = document.getElementById('pan-current');
            if (curEl) {
                curEl.innerText = '$' + currEq.toFixed(2);
                curEl.style.color = currEq >= initEq ? '#3fb950' : '#58a6ff';
            }

            const pnlEl = document.getElementById('pan-pnl');
            if (pnlEl) {
                const sign = netPnl >= 0 ? '+' : '';
                pnlEl.innerText = `${sign}$${netPnl.toFixed(2)} (${sign}${pnlPct.toFixed(1)}%)`;
                pnlEl.style.color = netPnl >= 0 ? '#3fb950' : '#f85149';
            }

            const ddEl = document.getElementById('pan-dd');
            if (ddEl) ddEl.innerText = maxDd.toFixed(1) + '%';

            const wrEl = document.getElementById('pan-winrate');
            if (wrEl) wrEl.innerText = `${wr}% (${wins}W / ${closedCount - wins}L)`;

            const countEl = document.getElementById('chart-point-count');
            if (countEl) countEl.innerText = `${closedCount} Cierres Registrados`;
        }

        function renderEquityChart(curve) {
            const canvas = document.getElementById('equityCanvas');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            const rect = canvas.getBoundingClientRect();
            if (rect.width === 0) return;

            const dpr = window.devicePixelRatio || 1;
            canvas.width = rect.width * dpr;
            canvas.height = rect.height * dpr;
            ctx.scale(dpr, dpr);

            const w = rect.width;
            const h = rect.height;
            const padLeft = 55;
            const padRight = 20;
            const padTop = 20;
            const padBottom = 25;
            const plotW = w - padLeft - padRight;
            const plotH = h - padTop - padBottom;

            ctx.clearRect(0, 0, w, h);
            if (curve.length === 0) return;

            let equities = curve.map(p => p.equity);
            let minE = Math.min(...equities, 60.0);
            let maxE = Math.max(...equities, 76.0);
            const margin = (maxE - minE) * 0.12 || 2.0;
            minE -= margin;
            maxE += margin;

            function getX(i) {
                if (curve.length === 1) return padLeft + plotW / 2;
                return padLeft + (i / (curve.length - 1)) * plotW;
            }
            function getY(eq) {
                return padTop + (1 - (eq - minE) / (maxE - minE)) * plotH;
            }

            chartDataPoints = curve.map((pt, i) => ({
                x: getX(i),
                y: getY(pt.equity),
                data: pt
            }));

            // Cuadrícula y etiquetas del Eje Y
            const steps = 4;
            ctx.font = '10px "JetBrains Mono", monospace';
            ctx.fillStyle = '#6e7681';
            ctx.textAlign = 'right';
            ctx.textBaseline = 'middle';
            for (let s = 0; s <= steps; s++) {
                const val = minE + (s / steps) * (maxE - minE);
                const y = getY(val);
                ctx.strokeStyle = '#21262d';
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(padLeft, y);
                ctx.lineTo(w - padRight, y);
                ctx.stroke();
                ctx.fillText('$' + val.toFixed(1), padLeft - 6, y);
            }

            // Línea Base $70.00
            const y70 = getY(70.0);
            if (y70 >= padTop && y70 <= padTop + plotH) {
                ctx.strokeStyle = 'rgba(201, 209, 217, 0.45)';
                ctx.setLineDash([4, 4]);
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(padLeft, y70);
                ctx.lineTo(w - padRight, y70);
                ctx.stroke();
                ctx.setLineDash([]);
                ctx.fillStyle = 'rgba(201, 209, 217, 0.7)';
                ctx.textAlign = 'left';
                ctx.fillText('Base $70.00', w - padRight - 65, y70 - 7);
            }

            // Degradado bajo la curva
            const grad = ctx.createLinearGradient(0, padTop, 0, padTop + plotH);
            grad.addColorStop(0, 'rgba(56, 189, 248, 0.35)');
            grad.addColorStop(1, 'rgba(56, 189, 248, 0.01)');

            ctx.beginPath();
            ctx.moveTo(chartDataPoints[0].x, padTop + plotH);
            chartDataPoints.forEach(pt => ctx.lineTo(pt.x, pt.y));
            ctx.lineTo(chartDataPoints[chartDataPoints.length - 1].x, padTop + plotH);
            ctx.closePath();
            ctx.fillStyle = grad;
            ctx.fill();

            // Línea continua de Patrimonio
            ctx.strokeStyle = '#38bdf8';
            ctx.lineWidth = 2.2;
            ctx.lineJoin = 'round';
            ctx.lineCap = 'round';
            ctx.beginPath();
            chartDataPoints.forEach((pt, i) => {
                if (i === 0) ctx.moveTo(pt.x, pt.y);
                else ctx.lineTo(pt.x, pt.y);
            });
            ctx.stroke();

            // Puntos de Cierre (Verde Ganador / Rojo Perdedor)
            chartDataPoints.forEach((pt, i) => {
                ctx.beginPath();
                if (i === 0) {
                    ctx.arc(pt.x, pt.y, 3, 0, Math.PI * 2);
                    ctx.fillStyle = '#8b949e';
                    ctx.fill();
                } else {
                    const isWin = pt.data.pnl > 0;
                    ctx.arc(pt.x, pt.y, 4, 0, Math.PI * 2);
                    ctx.fillStyle = isWin ? '#3fb950' : '#f85149';
                    ctx.fill();
                    ctx.strokeStyle = '#0d1117';
                    ctx.lineWidth = 1.5;
                    ctx.stroke();
                }
            });
        }

        // Configuración de Hover Tooltip en Canvas
        function initEquityCanvasEvents() {
            const canvas = document.getElementById('equityCanvas');
            const tooltip = document.getElementById('equityTooltip');
            if (!canvas || !tooltip) return;

            canvas.addEventListener('mousemove', (e) => {
                if (!chartDataPoints || chartDataPoints.length === 0) return;
                const rect = canvas.getBoundingClientRect();
                const mouseX = e.clientX - rect.left;
                const mouseY = e.clientY - rect.top;

                let nearest = null;
                let minDist = 25;
                chartDataPoints.forEach(pt => {
                    const dist = Math.hypot(pt.x - mouseX, pt.y - mouseY);
                    if (dist < minDist) {
                        minDist = dist;
                        nearest = pt;
                    }
                });

                if (nearest) {
                    const d = nearest.data;
                    const sign = d.pnl >= 0 ? '+' : '';
                    const col = d.pnl > 0 ? '#3fb950' : (d.pnl < 0 ? '#f85149' : '#8b949e');
                    const tradeIdStr = d.id ? `#${d.id} ` : '';
                    tooltip.innerHTML = `
                        <div style="font-weight:bold; color:#58a6ff; margin-bottom:2px;">
                            ${tradeIdStr}${d.symbol} <span style="font-size:10px; color:var(--text-dim);">(${d.time})</span>
                        </div>
                        <div style="display:flex; justify-content:space-between; gap:12px;">
                            <span>Patrimonio: <b style="color:#ffffff;">$${Number(d.equity).toFixed(2)}</b></span>
                            <span>PnL: <b style="color:${col};">${sign}$${Number(d.pnl).toFixed(4)}</b></span>
                        </div>
                        ${d.note ? `<div style="color:var(--text-dim); font-size:10px; margin-top:2px; max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:normal;">${d.note}</div>` : ''}
                    `;
                    tooltip.style.display = 'block';

                    let left = nearest.x + 12;
                    if (left + 240 > rect.width) left = nearest.x - 250;
                    let top = nearest.y - 20;
                    if (top < 0) top = 10;
                    tooltip.style.left = left + 'px';
                    tooltip.style.top = top + 'px';
                } else {
                    tooltip.style.display = 'none';
                }
            });

            canvas.addEventListener('mouseleave', () => {
                tooltip.style.display = 'none';
            });
        }

        window.addEventListener('resize', () => {
            if (fullHistory && fullHistory.equity_curve) {
                renderEquityChart(fullHistory.equity_curve);
            }
        });

        // CONTROL DEL MODAL
        function openHistoryModal() {
            const modal = document.getElementById('history-modal');
            if (modal) {
                modal.classList.add('active');
                document.body.style.overflow = 'hidden';
                loadHistoryData();
                renderHistoryTable();
            }
        }

        function closeHistoryModal() {
            const modal = document.getElementById('history-modal');
            if (modal) {
                modal.classList.remove('active');
                document.body.style.overflow = '';
            }
        }

        function handleModalOverlayClick(e) {
            if (e.target && e.target.id === 'history-modal') {
                closeHistoryModal();
            }
        }

        window.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeHistoryModal();
        });

        function setHistoryFilter(filter, btn) {
            activeHistoryFilter = filter;
            const buttons = document.querySelectorAll('.modal-toolbar .filter-btn');
            buttons.forEach(b => b.classList.remove('active'));
            if (btn) btn.classList.add('active');
            renderHistoryTable();
        }

        function filterHistoryTable() {
            renderHistoryTable();
        }

        function renderHistoryTable() {
            if (!fullHistory || !fullHistory.trades) return;
            const tbody = document.getElementById('history-tbody');
            if (!tbody) return;

            const query = (document.getElementById('history-search')?.value || '').toLowerCase().trim();
            const trades = fullHistory.trades;

            let filtered = trades.filter(t => {
                const pnl = Number(t.pnl || 0);
                const side = (t.side || '').toUpperCase();
                const mode = (t.mode || '').toUpperCase();
                const note = (t.note || '').toLowerCase();
                const symbol = (t.symbol || '').toLowerCase();

                if (activeHistoryFilter === 'closed' && side !== 'SELL' && pnl === 0) return false;
                if (activeHistoryFilter === 'win' && pnl <= 0) return false;
                if (activeHistoryFilter === 'loss' && pnl >= 0) return false;
                if (activeHistoryFilter === 'swing' && mode !== 'PAPER_SWING' && !note.includes('swing')) return false;
                if (activeHistoryFilter === 'grid' && mode !== 'BOUNDED_GRID' && !note.includes('malla') && !note.includes('grid')) return false;

                if (query) {
                    const matchText = `${t.id} ${symbol} ${side} ${mode} ${note}`.toLowerCase();
                    if (!matchText.includes(query)) return false;
                }
                return true;
            });

            const countBadge = document.getElementById('modal-trade-count');
            if (countBadge) countBadge.innerText = `${trades.length} Operaciones`;
            const totEl = document.getElementById('modal-total-count');
            if (totEl) totEl.innerText = trades.length;
            const filtEl = document.getElementById('modal-filtered-count');
            if (filtEl) filtEl.innerText = filtered.length;

            let sumPnl = 0.0;
            let wins = 0;
            let closes = 0;
            filtered.forEach(t => {
                const pnl = Number(t.pnl || 0);
                if (t.side === 'SELL' || pnl !== 0) {
                    sumPnl += pnl;
                    closes++;
                    if (pnl > 0) wins++;
                }
            });
            const wr = closes > 0 ? (wins / closes * 100.0).toFixed(1) : '0.0';
            const sumPnlEl = document.getElementById('modal-sum-pnl');
            if (sumPnlEl) {
                const sign = sumPnl >= 0 ? '+' : '';
                sumPnlEl.innerText = `${sign}$${sumPnl.toFixed(4)} USDT`;
                sumPnlEl.style.color = sumPnl >= 0 ? '#3fb950' : '#f85149';
            }
            const wrEl = document.getElementById('modal-sum-wr');
            if (wrEl) wrEl.innerText = `${wr}% (${wins}W / ${closes - wins}L)`;

            if (filtered.length === 0) {
                tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; color:var(--text-dim); padding:24px;">No se encontraron operaciones con los filtros aplicados.</td></tr>`;
                return;
            }

            let html = '';
            filtered.forEach(t => {
                const pnl = Number(t.pnl || 0);
                const hasPnl = t.side === 'SELL' || pnl !== 0;
                const pnlCol = pnl > 0 ? '#3fb950' : (pnl < 0 ? '#f85149' : '#8b949e');
                const pnlSign = pnl >= 0 ? '+' : '';
                const pnlStr = hasPnl ? `<b style="color:${pnlCol};">${pnlSign}$${pnl.toFixed(4)}</b>` : `<span style="color:var(--text-dim);">-</span>`;
                
                const sideBadge = t.side === 'BUY' ? '<span class="tag tag-green">BUY</span>' : '<span class="tag tag-yellow">SELL</span>';
                const modeBadge = (t.mode === 'BOUNDED_GRID' || (t.note || '').includes('Malla'))
                    ? '<span class="tag tag-purple">MALLA</span>'
                    : '<span class="tag tag-blue">SWING</span>';

                const ts = t.timestamp ? t.timestamp.replace('T', ' ').substring(0, 16) : '--';

                html += `<tr>
                    <td style="color:var(--text-dim); font-size:11px;">#${t.id}</td>
                    <td style="font-size:11px; color:#c9d1d9;">${ts}</td>
                    <td><b style="color:#ffffff;">${t.symbol}</b></td>
                    <td>${modeBadge}</td>
                    <td>${sideBadge}</td>
                    <td>$${Number(t.price).toFixed(4)}</td>
                    <td style="color:var(--text-dim);">$${Number(t.capital || 0).toFixed(2)}</td>
                    <td>${pnlStr}</td>
                    <td style="font-size:11px; color:#8b949e; max-width:320px; word-break:break-word;">${t.note || '--'}</td>
                </tr>`;
            });
            tbody.innerHTML = html;
        }

        // Inicializar eventos de tooltip y carga inicial
        initEquityCanvasEvents();
        loadHistoryData();
        setInterval(updateDashboard, 3000);
        updateDashboard();
    </script>
</body>
</html>
"""


