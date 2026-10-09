import os
import json
import time
import shutil

log_dir = "paper_logs"
backup_dir = "paper_logs_backup_" + time.strftime("%Y%m%d_%H%M%S")
if os.path.exists(log_dir):
    shutil.copytree(log_dir, backup_dir)
    print("Backup creado con exito en:", backup_dir)
else:
    os.makedirs(log_dir, exist_ok=True)

# 1. Reset Portfolio State ($500.00 USDT limpios, 0 posiciones residuales)
portfolio_clean = {
    "cash": 500.0,
    "holdings": {},
    "longs": {},
    "pending_orders": {},
    "grids": {},
    "total_fees_paid": 0.0,
    "total_slippage_cost": 0.0,
    "total_realized_pnl_acc": 0.0,
    "wins": 0,
    "losses": 0,
    "total_trades": 0,
    "trades_since_eval": 0,
    "peak_equity": 500.0,
    "max_drawdown": 0.0
}
with open(os.path.join(log_dir, "portfolio_state.json"), "w", encoding="utf-8") as f:
    json.dump(portfolio_clean, f, indent=2)

# 2. Reset Brain State
brain_clean = {
    "generation": 1,
    "weights": {
        "w_volume": 1.6,
        "w_volatility": 1.5,
        "w_pullback": 2.0,
        "w_rsi": 1.4,
        "w_adx": 1.4
    },
    "learning_rate": 0.08,
    "min_score_required": 65.0,
    "sl_atr_mult": 2.5,
    "tp1_gain_pct": 2.2,
    "trailing_mult": 2.0,
    "evolution_history": [],
    "coin_blacklist_until": {}
}
with open(os.path.join(log_dir, "brain_state.json"), "w", encoding="utf-8") as f:
    json.dump(brain_clean, f, indent=2)

# 3. Reset Committee Deliberations
with open(os.path.join(log_dir, "committee_deliberations.json"), "w", encoding="utf-8") as f:
    json.dump([], f, indent=2)

# 4. Reset AI Trade Audits
with open(os.path.join(log_dir, "ai_trade_audits.json"), "w", encoding="utf-8") as f:
    json.dump([], f, indent=2)

# 5. Clean Trades CSV
trades_csv = os.path.join(log_dir, "trades.csv")
with open(trades_csv, "w", encoding="utf-8") as f:
    f.write("timestamp,symbol,strategy,side,price,amount,pnl,fee,slippage,extra_info,position_id,status\n")

# 6. Reset Equity History CSV
equity_csv = os.path.join(log_dir, "equity_history.csv")
with open(equity_csv, "w", encoding="utf-8") as f:
    f.write("timestamp,equity,cash,holdings_value,open_longs,realized_pnl_total,fees_paid,slippage_cost,max_drawdown\n")
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
    f.write(f"{now_iso},500.00,500.00,0.00,0,0.00,0.00,0.00,0.00\n")

# Clean PnL Audit and Live State
with open(os.path.join(log_dir, "pnl_audit.json"), "w", encoding="utf-8") as f:
    json.dump([], f, indent=2)

# 7. Clean System Memory con Arquitectura y Principios Institucionales Limpios
system_memory_clean = {
    "version": "4.0_AUTONOMOUS",
    "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
    "agent_skills": {
        "SENTINEL": {
            "name": "Centinela Macro y Noticias",
            "specialty": "Deteccion de regimen macro, noticias criticas y correlacion con BTC",
            "rules": [
                "Si hay cisnes negros regulatorios o liquidaciones abruptas en BTC, activar modo DEFENSIVO.",
                "Viento a favor de Bitcoin (BTC alcista sobre EMA50 4h) autoriza mayor conviccion en altcoins lideres.",
                "Noticias especificas de alta liquidez o catalizadores impulsan la probabilidad de exito."
            ]
        },
        "ANALYST": {
            "name": "Analista Tecnico y Order Flow",
            "specialty": "Diagnostico libre de estructura de mercado, LOB, Squeeze y momentum",
            "rules": [
                "Diagnosticar con criterio libre: identificar si el activo esta en tendencia explosiva, en rango lateral o en sobre-extension.",
                "Validar volumen institucional real (> $25M) y volatilidad viva (ATR >= 1.2%) para garantizar rotacion agil.",
                "Verificar soporte pasivo en el libro de ordenes (OBI positivo para Longs, negativo para Shorts)."
            ]
        },
        "RISK_CONTROLLER": {
            "name": "Jefe de Riesgo y Comite",
            "specialty": "Evaluacion de Asimetria Matematica (+EV) y Capital Preservation",
            "rules": [
                "Prohibido operar por FOMO o en activos planos sin volatilidad: el capital no debe quedar estancado.",
                "Exigir relacion riesgo/beneficio positiva (+EV) con Stop Loss holgado (2.5x ATR minimo) para no morir por mechas.",
                "Vetar operaciones con confluencia debil o sin confirmacion clara de volumen."
            ]
        },
        "SNIPER_EXECUTOR": {
            "name": "Francotirador de Ejecucion",
            "specialty": "Seleccion de la mejor tactica de orden segun la dinamica del activo",
            "rules": [
                "BREAKOUT_MARKET: Entrada inmediata a mercado cuando hay momentum fuerte, ruptura y urgencia.",
                "MAKER_LIMIT: Entrada pasiva en soporte/rango con micro-descuento para pagar 0% slippage y comisiones minimas.",
                "ESPERAR_RETESTEO: Paciencia tactica cuando el precio ya despego y conviene esperar el retroceso a confirmacion."
            ]
        }
    },
    "coin_lessons": {},
    "tuning_history": [],
    "regime_insights": [
        {"regime": "BULLISH_EXPANSION", "rule": "Priorizar setups de momentum y rupturas rapidas con volumen."},
        {"regime": "CHOPPY_RANGE", "rule": "Priorizar entradas Maker pasivas en soportes o esperar confirmacion clara."},
        {"regime": "BEARISH_BTC", "rule": "Maxima prudencia. Reducir tamano de posicion o buscar shorts en debilidad."}
    ],
    "binance_playbook": {
        "principles": [
            "Alta liquidez institucional obligatoria (> $25M USDT / 24h).",
            "Cero persecucion de crestas de ola.",
            "Preservacion de capital como prioridad sobre la cantidad de trades."
        ]
    }
}
with open(os.path.join(log_dir, "system_memory.json"), "w", encoding="utf-8") as f:
    json.dump(system_memory_clean, f, indent=2, ensure_ascii=False)

print("Sistema reseteado a limpio desde cero con $500.00 USDT!")
