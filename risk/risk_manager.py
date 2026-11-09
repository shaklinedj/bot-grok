"""
Módulo de Gestión de Riesgo Activo, Trailing Stop, Break-Even y Salidas Asimétricas.
"""
import time
from typing import List
from config import (
    exchange,
    FEE_RATE,
    POST_STOP_COOLDOWN_S,
    TURBO_FAST_BE_PCT,
    TURBO_TIME_STOP_S
)
from risk.adaptive import process_trade_autopsy_and_feedback


def manage_active_swing_trade(bot):
    """
    Monitorea trades activos con Trailing Ágil (1.5x ATR), Break-Even dinámico,
    salidas asimétricas y emparejamiento determinístico de parent_trade_id.
    """
    if not bot.active_trades:
        bot.status_msg = "Sin posiciones. Escáner V2 buscando rupturas con fuerza relativa..."
        return

    for tr in list(bot.active_trades.values()):
        sym = tr.symbol
        try:
            ticker = exchange.fetch_ticker(sym)
            curr_p = float(ticker.get("last", 0.0) or 0.0)
        except Exception:
            continue

        if curr_p <= 0:
            continue

        gain_pct = (curr_p - tr.entry_price) / tr.entry_price

        tr.current_price = curr_p
        tr.highest_price = max(getattr(tr, "highest_price", tr.entry_price), curr_p)
        tr.lowest_price = min(getattr(tr, "lowest_price", tr.entry_price), curr_p)
        tr.unrealized_pnl = (curr_p - tr.entry_price) * tr.amount
        tr.unrealized_pnl_pct = gain_pct * 100.0

        atr_val_abs = tr.entry_price * (tr.atr_pct / 100.0)

        # 1. Break-Even: Dinámico por ATR + Spread L2 o Acelerado en Modo Turbo x2
        is_turbo_trade = getattr(tr, "is_turbo", False)
        spread_pct = getattr(tr, "spread_pct", 0.0010) or 0.0010
        if is_turbo_trade:
            be_threshold = TURBO_FAST_BE_PCT + spread_pct  # +0.80% + spread en precio
            be_stop = max(0.0025, spread_pct * 1.5)        # Asegura comisiones y spread
            mode_lbl = "TURBO x2 FAST"
        elif getattr(bot, "settings", {}).get("auto_atr_mode", True):
            base_be = getattr(bot, "settings", {}).get("be_trigger_pct", 0.0150)
            be_threshold = max(base_be + spread_pct, (tr.atr_pct / 100.0) * 0.90 + spread_pct)
            be_stop = max(getattr(bot, "settings", {}).get("be_stop_pct", 0.0020), spread_pct * 1.5)
            mode_lbl = "AUTO ATR + SPREAD"
        else:
            base_be = getattr(bot, "settings", {}).get("be_trigger_pct", 0.0150)
            be_threshold = base_be + spread_pct
            be_stop = max(getattr(bot, "settings", {}).get("be_stop_pct", 0.0020), spread_pct * 1.5)
            mode_lbl = "MANUAL + SPREAD"

        if not tr.is_be_active and gain_pct >= be_threshold:
            tr.is_be_active = True
            new_stop = round(tr.entry_price * (1.0 + be_stop), 6)
            if new_stop > tr.stop_price:
                tr.stop_price = new_stop
                bot.add_log(
                    f"🛡️ BREAK-EVEN [{mode_lbl}] en {sym}: +{gain_pct*100:.2f}% (Umbral {be_threshold*100:.2f}%). "
                    f"Stop -> ${new_stop:.4f} (+{be_stop*100:.2f}%). Riesgo CERO.",
                    "trade"
                )
                bot.save_state()

        # 1.5 Salida Rápida por Time-Stop en Modo Turbo (25 minutos sin continuación)
        duration_s = time.time() - tr.entry_time
        if is_turbo_trade and duration_s >= TURBO_TIME_STOP_S and gain_pct < 0.012:
            gross_pnl = (curr_p - tr.entry_price) * tr.amount
            exit_fee = (curr_p * tr.amount) * FEE_RATE
            net_pnl = gross_pnl - tr.entry_fee - exit_fee
            bot.cash += (tr.capital + net_pnl)
            pnl_pct = (net_pnl / tr.capital * 100.0) if tr.capital > 0 else 0.0
            reason = f"⏱️ TIME-STOP TURBO A+ ({duration_s/60:.0f}m): Salida rápida para evitar desgaste"
            bot.add_log(f"{reason} en {sym} @ ${curr_p:.4f} | PnL: {net_pnl:+.4f} USDT ({pnl_pct:+.2f}%)", "trade")
            bot.db.log_trade(
                symbol=sym,
                side="SELL",
                price=curr_p,
                amount=tr.amount,
                capital=tr.capital,
                pnl=net_pnl,
                fee=exit_fee,
                order_id=tr.trade_id,
                target_price=tr.target_price,
                stop_price=tr.stop_price,
                note=reason,
                parent_trade_id=tr.trade_id
            )
            process_trade_autopsy_and_feedback(bot, tr, curr_p, net_pnl, reason, exit_fee)
            bot.cooldowns[sym] = time.time() + 300
            bot.active_trades.pop(sym, None)
            bot.save_state()
            continue

        # 1.8 COSECHA ESCALONADA ASIMÉTRICA:
        # TP1 (50% al +1.5R): Asegura caja y blinda el stop a +0.5R (Free Roll).
        # TP2 (25% al +3.0R): Asegura el pico intermedio (75% total asegurado).
        # Moonbag (25% final): Runner sin techo que se exprime con Trailing Stop Acelerado.
        r_gain = gain_pct / max(tr.stop_pct, 0.005)

        # TP1: 50% al +1.5R (~ +2.4%)
        if not getattr(tr, "tp1_hit", False) and r_gain >= 1.50 and tr.amount > 0:
            partial_amount = round(tr.amount * 0.50, 4)
            partial_cap = round(tr.capital * 0.50, 2)
            if partial_amount > 0 and partial_cap > 0:
                gross_partial_pnl = (curr_p - tr.entry_price) * partial_amount
                partial_exit_fee = (curr_p * partial_amount) * FEE_RATE
                partial_entry_fee = tr.entry_fee * 0.50
                net_partial_pnl = gross_partial_pnl - partial_entry_fee - partial_exit_fee

                bot.cash += (partial_cap + net_partial_pnl)
                tr.amount -= partial_amount
                tr.capital -= partial_cap
                tr.entry_fee -= partial_entry_fee
                tr.tp1_hit = True

                # Lock-in de Ganancia: Stop a +0.5R por encima de la entrada
                lockin_stop = round(tr.entry_price * (1.0 + (tr.stop_pct * 0.50)), 6)
                if lockin_stop > tr.stop_price:
                    tr.stop_price = lockin_stop
                    tr.is_be_active = True

                reason_tp1 = f"💰 TP1 PARCIAL 50% (+1.5R | +{gain_pct*100:.2f}%): Asegurado a caja"
                bot.add_log(
                    f"{reason_tp1} en {sym} @ ${curr_p:.4f} | PnL: +${net_partial_pnl:.4f} USDT. "
                    f"Stop Runner en ${lockin_stop:.4f} (+0.5R). Posición en FREE ROLL.",
                    "trade"
                )
                bot.db.log_trade(
                    symbol=sym,
                    side="SELL",
                    price=curr_p,
                    amount=partial_amount,
                    capital=partial_cap,
                    pnl=net_partial_pnl,
                    fee=partial_exit_fee,
                    order_id=f"{tr.trade_id}_TP1",
                    target_price=tr.target_price,
                    stop_price=tr.stop_price,
                    note=reason_tp1,
                    parent_trade_id=tr.trade_id
                )
                bot.save_state()

        # TP2: 25% del total original (50% de lo que queda) al +3.0R (~ +4.5%)
        if getattr(tr, "tp1_hit", False) and not getattr(tr, "tp2_hit", False) and r_gain >= 3.00 and tr.amount > 0:
            partial_amount_2 = round(tr.amount * 0.50, 4)
            partial_cap_2 = round(tr.capital * 0.50, 2)
            if partial_amount_2 > 0 and partial_cap_2 > 0:
                gross_partial_pnl_2 = (curr_p - tr.entry_price) * partial_amount_2
                partial_exit_fee_2 = (curr_p * partial_amount_2) * FEE_RATE
                partial_entry_fee_2 = tr.entry_fee * 0.50
                net_partial_pnl_2 = gross_partial_pnl_2 - partial_entry_fee_2 - partial_exit_fee_2

                bot.cash += (partial_cap_2 + net_partial_pnl_2)
                tr.amount -= partial_amount_2
                tr.capital -= partial_cap_2
                tr.entry_fee -= partial_entry_fee_2
                tr.tp2_hit = True

                # Al asegurar TP2, ceñir stop a +1.8R (+3.0%)
                lockin_stop_2 = round(tr.entry_price * (1.0 + (tr.stop_pct * 1.80)), 6)
                if lockin_stop_2 > tr.stop_price:
                    tr.stop_price = lockin_stop_2

                reason_tp2 = f"🎯 TP2 INTERMEDIO 25% (+3.0R | +{gain_pct*100:.2f}%): Ganancia masiva asegurada"
                bot.add_log(
                    f"{reason_tp2} en {sym} @ ${curr_p:.4f} | PnL: +${net_partial_pnl_2:.4f} USDT. "
                    f"Moonbag restante 25% persigue explosión parabólica libre con trailing ceñido.",
                    "trade"
                )
                bot.db.log_trade(
                    symbol=sym,
                    side="SELL",
                    price=curr_p,
                    amount=partial_amount_2,
                    capital=partial_cap_2,
                    pnl=net_partial_pnl_2,
                    fee=partial_exit_fee_2,
                    order_id=f"{tr.trade_id}_TP2",
                    target_price=tr.target_price,
                    stop_price=tr.stop_price,
                    note=reason_tp2,
                    parent_trade_id=tr.trade_id
                )
                bot.save_state()

        # 1.9 DETECCIÓN DE CLÍMAX INSTITUCIONAL EN MÁXIMOS (Blow-off Top Exit)
        # Si la ganancia es > +3.0% y el flujo de órdenes muestra agotamiento clímax
        # (compras minoristas > 88% o libro saturado de rechazo), liquidar el runner de inmediato en el pico.
        if gain_pct >= 0.030 and tr.amount > 0 and getattr(tr, "tp1_hit", False):
            try:
                flow_chk = fetch_order_flow_confirmation(sym)
                climax_buy = flow_chk.get("buy_ratio_pct", 50.0) >= 88.0
                climax_obi = flow_chk.get("obi", 0.0) <= -0.30  # Ventas masivas absorbiendo
                if climax_buy or climax_obi:
                    gross_climax_pnl = (curr_p - tr.entry_price) * tr.amount
                    exit_fee = (curr_p * tr.amount) * FEE_RATE
                    net_climax_pnl = gross_climax_pnl - tr.entry_fee - exit_fee
                    bot.cash += (tr.capital + net_climax_pnl)
                    reason_climax = f"🌋 ESCAPE POR CLÍMAX EN MÁXIMOS (+{gain_pct*100:.2f}% | OF: {flow_chk['buy_ratio_pct']:.1f}% Compras)"
                    bot.add_log(f"{reason_climax} en {sym} @ ${curr_p:.4f} | PnL: +${net_climax_pnl:.4f} USDT", "trade")
                    bot.db.log_trade(
                        symbol=sym,
                        side="SELL",
                        price=curr_p,
                        amount=tr.amount,
                        capital=tr.capital,
                        pnl=net_climax_pnl,
                        fee=exit_fee,
                        order_id=f"{tr.trade_id}_CLIMAX",
                        target_price=tr.target_price,
                        stop_price=tr.stop_price,
                        note=reason_climax,
                        parent_trade_id=tr.trade_id
                    )
                    process_trade_autopsy_and_feedback(bot, tr, curr_p, net_climax_pnl, reason_climax, exit_fee)
                    bot.cooldowns[sym] = time.time() + 300
                    bot.active_trades.pop(sym, None)
                    bot.save_state()
                    continue
            except Exception:
                pass

        # 2. TRAILING STOP ASIMÉTRICO CON ACELERACIÓN (TIGHTENING DINÁMICO)
        # • Fase 1 (Ganancia +1.8% a +3.5%): Oxígeno holgado (1.50x ATR)
        # • Fase 2 (Ganancia +3.5% a +6.0%): Compresión protectora (0.80x ATR - reduce el giveback a mínimos)
        # • Fase 3 (Parabólica > +6.0%): Ultra-ceñido (0.45x ATR - persigue la cima al milímetro)
        trail_trigger_pct = getattr(bot, "settings", {}).get("trail_trigger_pct", 0.0180)
        trailing_trigger = max(trail_trigger_pct, (tr.atr_pct / 100.0) * 1.8)
        if gain_pct >= trailing_trigger:
            if gain_pct >= 0.060:
                dyn_mult = 0.45   # Ultra-ceñido en despegue parabólico
                fase_desc = "Fase 3 Parabólica 0.45x ATR"
            elif gain_pct >= 0.035:
                dyn_mult = 0.80   # Compresión protectora anti-retroceso
                fase_desc = "Fase 2 Ceñida 0.80x ATR"
            else:
                dyn_mult = getattr(bot, "settings", {}).get("trail_distance_atr", 1.50)
                fase_desc = "Fase 1 Oxígeno 1.50x ATR"

            trail_stop = round(tr.highest_price - (dyn_mult * atr_val_abs), 6)
            if trail_stop > tr.stop_price:
                old_stop = tr.stop_price
                tr.stop_price = trail_stop
                tr.is_trailing_active = True
                bot.add_log(
                    f"📈 TRAILING DINÁMICO [{fase_desc}] en {sym}: "
                    f"Max ${tr.highest_price:.4f}. Stop ${old_stop:.4f} -> ${trail_stop:.4f}",
                    "trade"
                )
                bot.save_state()

        # 3. Cierre por Target
        # Si UNLIMITED_RUNNER está activo y ya se cobró TP1, el 50% restante es un RUNNER SIN LÍMITES
        # que no tiene techo fijo y corre libremente guiado al 100% por el Trailing Stop.
        unlimited_runner = getattr(bot, "settings", {}).get("unlimited_runner", True)
        should_close_target = (curr_p >= tr.target_price)
        if getattr(tr, "tp1_hit", False) and unlimited_runner:
            should_close_target = False  # El Runner corre libre sin techo fijo

        if should_close_target:
            gross_pnl = (tr.target_price - tr.entry_price) * tr.amount
            exit_fee = (tr.target_price * tr.amount) * FEE_RATE
            net_pnl = gross_pnl - tr.entry_fee - exit_fee
            bot.cash += (tr.capital + net_pnl)
            reason = f"🏆 TARGET V2 (+{tr.target_pct*100:.2f}%)"
            bot.add_log(f"{reason} en {sym}: ${tr.target_price:.4f} | PnL: +${net_pnl:.4f} USDT", "trade")
            bot.db.log_trade(
                symbol=sym,
                side="SELL",
                price=tr.target_price,
                amount=tr.amount,
                capital=tr.capital,
                pnl=net_pnl,
                fee=exit_fee,
                order_id=tr.trade_id,
                target_price=tr.target_price,
                stop_price=tr.stop_price,
                note=reason,
                parent_trade_id=tr.trade_id
            )
            process_trade_autopsy_and_feedback(bot, tr, tr.target_price, net_pnl, reason, exit_fee)
            bot.cooldowns[sym] = time.time() + 300  # 5 min cooldown tras win
            bot.active_trades.pop(sym, None)
            bot.save_state()
            continue

        # 4. Cierre por Stop Loss (o Break-Even / Trailing / Runner Ilimitado)
        if curr_p <= tr.stop_price:
            gross_pnl = (tr.stop_price - tr.entry_price) * tr.amount
            exit_fee = (tr.stop_price * tr.amount) * FEE_RATE
            net_pnl = gross_pnl - tr.entry_fee - exit_fee
            bot.cash += (tr.capital + net_pnl)
            if getattr(tr, "tp1_hit", False):
                runner_gain = ((tr.stop_price - tr.entry_price) / tr.entry_price) * 100.0
                reason = f"🚀 RUNNER SIN LÍMITE CERRÓ EN MÁXIMOS (+{runner_gain:+.2f}%)"
            elif tr.is_trailing_active:
                reason = "📈 TRAILING CERRÓ CON GANANCIA"
            elif tr.is_be_active:
                reason = "🛡️ SALIDA BREAK-EVEN"
            else:
                reason = f"🛑 STOP DEFENSIVO (-{tr.stop_pct*100:.2f}%)"
            bot.add_log(f"{reason} en {sym} @ ${tr.stop_price:.4f} | PnL: {net_pnl:+.4f} USDT", "trade")
            bot.db.log_trade(
                symbol=sym,
                side="SELL",
                price=tr.stop_price,
                amount=tr.amount,
                capital=tr.capital,
                pnl=net_pnl,
                fee=exit_fee,
                order_id=tr.trade_id,
                target_price=tr.target_price,
                stop_price=tr.stop_price,
                note=reason,
                parent_trade_id=tr.trade_id
            )
            process_trade_autopsy_and_feedback(bot, tr, tr.stop_price, net_pnl, reason, exit_fee)
            cd_sec = getattr(bot, "settings", {}).get("post_stop_cooldown_s", POST_STOP_COOLDOWN_S)
            bot.cooldowns[sym] = time.time() + cd_sec
            bot.last_stop_time = time.time()
            if not tr.is_trailing_active and not tr.is_be_active:
                # Pérdida real en stop loss: Pausa portfolio-wide para evitar el efecto ametralladora
                global_cd = getattr(bot, "settings", {}).get("global_stop_cooldown_s", 300)
                bot.global_cooldown_until = time.time() + global_cd
                bot.add_log(
                    f"⏸️ [ENFRIAMIENTO GLOBAL POST-STOP] Pausa obligatoria de {global_cd}s para evitar sobreoperar en mercado adverso.",
                    "info"
                )
            bot.active_trades.pop(sym, None)
            bot.save_state()
            continue

    if bot.active_trades:
        summaries = [f"{t.symbol} ({t.unrealized_pnl_pct:+.2f}%)" for t in bot.active_trades.values()]
        bot.status_msg = f"Posiciones Activas ({len(bot.active_trades)}/{bot.get_max_concurrent_trades()}): " + ", ".join(summaries)
