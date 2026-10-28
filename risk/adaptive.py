"""
Motor de Aprendizaje Adaptativo Cuantitativo y Autopsias Post-Trade.
Implementa una ventana móvil de los últimos 20 trades y una tasa de aprendizaje decreciente
para prevenir el sobreajuste (overfitting) y estabilizar la política de ejecución.
"""
import time
from typing import Dict, Any, List
from config import DEFAULT_SETTINGS, POST_STOP_COOLDOWN_S
from scoring.market_scanner import update_btc_context


def calculate_decaying_learning_rate(trade_count: int, base_lr: float = 0.10, decay_rate: float = 0.05) -> float:
    """
    Calcula la tasa de aprendizaje decreciente:
    eta_t = eta_0 / (1 + decay_rate * t)
    Garantiza que el bot converja hacia la estabilidad a medida que acumula historial estadístico.
    """
    return base_lr / (1.0 + decay_rate * max(0, trade_count))


def process_trade_autopsy_and_feedback(bot, tr, exit_price: float, net_pnl: float, reason: str, exit_fee: float):
    """
    Motor Dinámico de Autoaprendizaje V3 (Anti-Overfitting):
    1. Evalúa micro-métricas del trade individual (MFE, MAE, duración, régimen BTC).
    2. Consulta la ventana móvil de los últimos 20 trades en SQLite para confirmar si la causa es sistémica.
    3. Aplica ajustes con tasa de aprendizaje decreciente (eta_t).
    """
    now = time.time()
    duration_s = max(1.0, now - tr.entry_time)
    highest_p = getattr(tr, "highest_price", tr.entry_price)
    lowest_p = getattr(tr, "lowest_price", tr.entry_price)
    mfe_pct = (highest_p - tr.entry_price) / tr.entry_price * 100.0
    mae_pct = (lowest_p - tr.entry_price) / tr.entry_price * 100.0
    pnl_pct = (net_pnl / tr.capital * 100.0) if tr.capital > 0 else 0.0

    btc_ctx = update_btc_context()
    btc_regime = btc_ctx.get("regime", "NEUTRAL_TRANSITION")

    classification = "UNKNOWN"
    lesson = ""
    action = ""

    # 1. Diagnóstico micro del trade actual
    if net_pnl > 0:
        if "TARGET" in reason or pnl_pct >= 3.0:
            classification = "TARGET_HIT"
            lesson = f"Ruptura sólida en {tr.symbol} con expansión completa (+{pnl_pct:.2f}%). Cosecha óptima."
            action = "Mantener parámetros de convicción y celebrar la paciencia técnica."
        elif mfe_pct >= 2.0 and pnl_pct < 0.30:
            classification = "PREMATURE_CHOKE"
            lesson = f"El activo subió +{mfe_pct:.2f}% (MFE) pero cerró con +{pnl_pct:.2f}% (+${net_pnl:.2f}). Trailing/BE muy ajustado."
            action = "Candidato a aumentar holgura de trailing (evaluando ventana móvil)."
        elif "TRAILING" in reason:
            classification = "RUNNER_HARVESTED"
            lesson = f"Tendencia aprovechada (+{pnl_pct:.2f}%). Trailing Stop aseguró ganancias en retroceso."
            action = "Excelente ejecución de persecución de tendencia."
        else:
            classification = "BREAK_EVEN_EXIT"
            lesson = f"Cierre defensivo en coste protegido (+{pnl_pct:.2f}%). Capital preservado."
            action = "Continuar escaneo."
    else:
        if duration_s < 1500 and abs(mae_pct) < 1.0:
            classification = "NOISE_STOP_HUNT"
            lesson = f"Stop tocado en {duration_s/60:.0f}m con oscilación menor (-{abs(mae_pct):.2f}%). Ruido de mercado."
            action = "Candidato a elevar stop multiplier (evaluando ventana móvil)."
        elif btc_regime == "CHOP_COMPRESSION":
            classification = "CHOP_FALSE_BREAKOUT"
            lesson = f"Falsa ruptura en {tr.symbol} atrapada por compresión lateral de Bitcoin."
            action = "Activar cooldown de compresión y exigir Score A+."
        elif btc_regime == "BEARISH_DUMP":
            classification = "MACRO_BTC_DRAG"
            lesson = f"Venta masiva de Bitcoin arrastró a {tr.symbol}. Ruptura invalidada por macro."
            action = "Candado bajista macro activo."
        else:
            classification = "NORMAL_STOP_DEFENSIVE"
            lesson = f"Stop defensivo actuó según plan (-{abs(pnl_pct):.2f}%). Pérdida acotada."
            action = "Respetar cooldown y esperar siguiente configuración A+."

    # 2. Análisis estadístico sobre la Ventana Móvil de los últimos 20 trades
    recent_trades = bot.db.get_recent_trades(limit=20)
    window_count = len(recent_trades)
    total_lifetime_trades = bot.db.get_trade_count()
    lr = calculate_decaying_learning_rate(total_lifetime_trades)

    if window_count >= 5:
        wins_in_window = sum(1 for t in recent_trades if float(t.get("pnl", 0.0) or 0.0) > 0)
        winrate_window = (wins_in_window / window_count) * 100.0
        gross_wins = sum(float(t.get("pnl", 0.0)) for t in recent_trades if float(t.get("pnl", 0.0) or 0.0) > 0)
        gross_losses = sum(abs(float(t.get("pnl", 0.0))) for t in recent_trades if float(t.get("pnl", 0.0) or 0.0) < 0)
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else 9.99

        # Consulta autopsias recientes para patrones agregados
        recent_autopsies = bot.db.get_recent_autopsies(limit=20)
        premature_chokes = sum(1 for a in recent_autopsies if a.get("classification") == "PREMATURE_CHOKE")
        noise_stops = sum(1 for a in recent_autopsies if a.get("classification") == "NOISE_STOP_HUNT")

        # Regla 1: Asfixia recurrente de ganadores (> 25% de los trades recientes)
        if premature_chokes >= 3 or (classification == "PREMATURE_CHOKE" and premature_chokes >= 2):
            cur_trail = bot.settings.get("trail_distance_atr", 1.5)
            step = round(lr * 1.0, 3)
            new_trail = round(min(2.0, max(1.5, cur_trail + step)), 2)
            if new_trail != cur_trail:
                bot.settings["trail_distance_atr"] = new_trail
                bot.save_settings()
                action = f"Autoaprendizaje (Decay LR={lr:.3f}): Holgura Trailing ajustada a {new_trail}x ATR."

        # Regla 2: Ruido recurrente en stops (> 25% de los trades recientes)
        if noise_stops >= 3 or (classification == "NOISE_STOP_HUNT" and noise_stops >= 2):
            cur_stop = bot.settings.get("stop_atr_mult", 2.0)
            step = round(lr * 1.0, 3)
            new_stop = round(min(2.5, cur_stop + step), 2)
            if new_stop != cur_stop:
                bot.settings["stop_atr_mult"] = new_stop
                bot.save_settings()
                action = f"Autoaprendizaje (Decay LR={lr:.3f}): Multiplicador Stop ampliado a {new_stop}x ATR."

        # Regla 3: Régimen de bajo rendimiento sostenido (Winrate < 40%)
        if winrate_window < 40.0:
            cur_score = bot.settings.get("min_score", 82.0)
            step_score = round(lr * 10.0, 1)
            new_score = round(min(88.0, cur_score + step_score), 1)
            if new_score != cur_score:
                bot.settings["min_score"] = new_score
                bot.settings["post_stop_cooldown_s"] = min(1200, bot.settings.get("post_stop_cooldown_s", 900) + 60)
                bot.save_settings()
                action = f"Autoaprendizaje Defensivo (Winrate 20T: {winrate_window:.1f}%): Elevando Score a {new_score}+."

        # Regla 4: Régimen de alta tracción (Winrate > 60% y Profit Factor > 1.8)
        elif winrate_window > 60.0 and profit_factor > 1.8:
            cur_score = bot.settings.get("min_score", 82.0)
            step_score = round(lr * 5.0, 1)
            new_score = round(max(78.0, cur_score - step_score), 1)
            if new_score != cur_score:
                bot.settings["min_score"] = new_score
                bot.save_settings()
                action = f"Autoaprendizaje Expansivo (PF: {profit_factor:.2f}): Score flexibilizado a {new_score}+."
    else:
        # Menos de 5 trades en la ventana: no sobreajustar
        action = f"Muestra insuficiente ({window_count}/20 trades). Parámetros preservados para evitar sobreajuste."

    # 3. Registrar Autopsia en SQLite
    bot.db.log_autopsy(
        trade_id=tr.trade_id,
        symbol=tr.symbol,
        pnl=net_pnl,
        pnl_pct=pnl_pct,
        duration_s=duration_s,
        mfe_pct=mfe_pct,
        mae_pct=mae_pct,
        exit_reason=reason,
        classification=classification,
        btc_regime=btc_regime,
        lesson_learned=lesson,
        adaptive_action=action
    )
    bot.add_log(
        f"🔬 AUTOPSIA [{classification}] {tr.symbol}: PnL {net_pnl:+.4f} USDT ({pnl_pct:+.2f}%) | "
        f"MFE: +{mfe_pct:.2f}% | MAE: {mae_pct:.2f}% | LR: {lr:.3f} | {action}",
        "trade"
    )
