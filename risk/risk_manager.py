"""
Módulo de Gestión de Riesgo Activo, Trailing Stop, Break-Even y Salidas Asimétricas.
"""
import time
from typing import List
from config import exchange, FEE_RATE, POST_STOP_COOLDOWN_S
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

        # 1. Break-Even: Dinámico por ATR o Manual
        if getattr(bot, "settings", {}).get("auto_atr_mode", True):
            be_threshold = max(0.012, (tr.atr_pct / 100.0) * 0.90)
        else:
            be_threshold = getattr(bot, "settings", {}).get("be_trigger_pct", 0.016)

        be_stop = getattr(bot, "settings", {}).get("be_stop_pct", 0.0020)
        if not tr.is_be_active and gain_pct >= be_threshold:
            tr.is_be_active = True
            new_stop = round(tr.entry_price * (1.0 + be_stop), 6)
            if new_stop > tr.stop_price:
                tr.stop_price = new_stop
                mode_lbl = "AUTO ATR" if getattr(bot, "settings", {}).get("auto_atr_mode", True) else "MANUAL"
                bot.add_log(
                    f"🛡️ BREAK-EVEN [{mode_lbl}] en {sym}: +{gain_pct*100:.2f}% (Umbral {be_threshold*100:.2f}%). "
                    f"Stop -> ${new_stop:.4f} (+{be_stop*100:.2f}%). Riesgo CERO.",
                    "trade"
                )
                bot.save_state()

        # 2. Trailing Stop: Se activa al alcanzar >= +1.8% o 1.8x ATR con holgura amplia (1.5x ATR)
        trail_dist_mult = getattr(bot, "settings", {}).get("trail_distance_atr", 1.5)
        trailing_trigger = max(0.018, (tr.atr_pct / 100.0) * 1.8)
        if gain_pct >= trailing_trigger:
            trail_stop = round(tr.highest_price - (trail_dist_mult * atr_val_abs), 6)
            if trail_stop > tr.stop_price:
                old_stop = tr.stop_price
                tr.stop_price = trail_stop
                tr.is_trailing_active = True
                bot.add_log(
                    f"📈 TRAILING [Oxígeno {trail_dist_mult}x ATR] en {sym}: "
                    f"Max ${tr.highest_price:.4f}. Stop ${old_stop:.4f} -> ${trail_stop:.4f}",
                    "trade"
                )
                bot.save_state()

        # 3. Cierre por Target
        if curr_p >= tr.target_price:
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

        # 4. Cierre por Stop Loss (o Break-Even / Trailing)
        if curr_p <= tr.stop_price:
            gross_pnl = (tr.stop_price - tr.entry_price) * tr.amount
            exit_fee = (tr.stop_price * tr.amount) * FEE_RATE
            net_pnl = gross_pnl - tr.entry_fee - exit_fee
            bot.cash += (tr.capital + net_pnl)
            if tr.is_trailing_active:
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
            bot.active_trades.pop(sym, None)
            bot.save_state()
            continue

    if bot.active_trades:
        summaries = [f"{t.symbol} ({t.unrealized_pnl_pct:+.2f}%)" for t in bot.active_trades.values()]
        bot.status_msg = f"Posiciones Activas ({len(bot.active_trades)}/{bot.get_max_concurrent_trades()}): " + ", ".join(summaries)
