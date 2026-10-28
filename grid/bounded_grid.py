"""
Módulo de Malla Acotada (Bounded Micro-Grid) para Regímenes Laterales (CHOP_COMPRESSION).
Aplica Exponente de Hurst (H < 0.46) y canales de reversión a la media con Kill-Switch estricto.
"""
import time
from typing import Optional

from config import exchange, FEE_RATE
from engine.bot_models import BoundedMicroGrid, GridLevel
from scoring.indicators import calc_ema, calc_hurst_exponent, detect_horizontal_channel
from scoring.market_scanner import fetch_ohlcv_cached


def scan_bounded_grid_candidates(bot) -> Optional[BoundedMicroGrid]:
    """
    Escanea candidatos para Malla Acotada durante régimen CHOP_COMPRESSION.
    Criterios matemáticos:
    - Volumen y reputación comprobados
    - Exponente de Hurst H < 0.46 (Reversión a la media comprobada)
    - Canal horizontal detectado (1.0% <= Ancho <= 4.5%, pendiente plana)
    - Posición actual en el canal: channel_pos <= 0.60 (compramos en la mitad inferior)
    - Entrada inmediata (curr_p <= p1)
    """
    if bot.cash < 45.0 or getattr(bot, "active_grid", None) or bot.active_trades:
        return None

    now = time.time()
    symbols = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
        "XRP/USDT", "LTC/USDT", "ADA/USDT", "XLM/USDT",
        "NEAR/USDT", "LINK/USDT", "AVAX/USDT", "DOT/USDT", "SUI/USDT"
    ]

    best_candidate = None
    lowest_hurst = 0.50

    for sym in symbols:
        if bot.cooldowns.get(sym, 0) > now:
            continue
        try:
            candles = fetch_ohlcv_cached(sym, "15m", limit=36)
            if len(candles) < 24:
                continue
            closes = [c[4] for c in candles]
            curr_p = closes[-1]

            # 1. Filtro Multi-Timeframe 1H (Anti-Banderín Bajista)
            candles_1h = fetch_ohlcv_cached(sym, "1h", limit=24)
            if len(candles_1h) >= 12:
                closes_1h = [c[4] for c in candles_1h]
                chg_1h_24h = (closes_1h[-1] - closes_1h[0]) / closes_1h[0] * 100.0
                ema20_1h = calc_ema(closes_1h, min(len(closes_1h), 20))
                if chg_1h_24h < -3.5 and curr_p < ema20_1h * 0.99:
                    continue

            h = calc_hurst_exponent(closes)
            if h >= 0.46:
                continue

            chan = detect_horizontal_channel(candles)
            if not chan:
                continue

            if chan["channel_pos"] > 0.60:
                continue

            if h < lowest_hurst:
                lowest_hurst = h
                best_candidate = (sym, chan, h, curr_p)
        except Exception:
            continue

    if not best_candidate:
        return None

    sym, chan, h, curr_p = best_candidate
    supp = chan["support"]
    res = chan["resistance"]
    mid = chan["midpoint"]

    total_grid_cap = min(bot.cash * 0.85, 54.0)
    level_cap = round(total_grid_cap / 3.0, 2)

    half_width = (mid - supp)
    p1 = round(mid - half_width * 0.25, 6)
    p2 = round(mid - half_width * 0.65, 6)
    p3 = round(supp * 1.002, 6)

    def get_amt(p):
        if p >= 1000:
            return round(level_cap / p, 6)
        elif p >= 1:
            return round(level_cap / p, 4)
        else:
            return round(level_cap / p, 2)

    kill_switch_p = round(supp * 0.988, 6)

    bot.sim_order_seq += 1
    grid_id = f"GRID_{bot.sim_order_seq}"

    grid = BoundedMicroGrid(
        grid_id=grid_id,
        symbol=sym,
        channel_support=supp,
        channel_resistance=res,
        midpoint=mid,
        hurst_exponent=h,
        kill_switch_price=kill_switch_p,
        total_capital=total_grid_cap
    )

    lvl1 = GridLevel(0, p1, get_amt(p1), level_cap)
    lvl2 = GridLevel(1, p2, get_amt(p2), level_cap)
    lvl3 = GridLevel(2, p3, get_amt(p3), level_cap)

    # Exigencia de ejecución inmediata: evitar mallas fantasma
    if curr_p > p1:
        return None

    lvl1.status = "FILLED"
    lvl1.fill_price = curr_p
    lvl1.fill_time = time.time()
    bot.cash -= level_cap
    bot.db.log_trade(
        symbol=sym,
        side="BUY",
        price=curr_p,
        amount=lvl1.amount,
        capital=level_cap,
        pnl=0.0,
        fee=level_cap * FEE_RATE,
        order_id=f"{grid_id}_L1",
        target_price=res,
        stop_price=kill_switch_p,
        note=f"📥 MALLA FILL N1/3 {sym} (Canal {chan['width_pct']}% | H: {h})",
        mode="BOUNDED_GRID",
        parent_trade_id=grid_id
    )

    grid.levels = [lvl1, lvl2, lvl3]
    bot.active_grid = grid
    bot.active_mode = "BOUNDED_GRID"

    bot.add_log(
        f"🟡 ACTIVANDO MALLA ACOTADA #{grid_id} en {sym}: Canal ${supp:.4f} - ${res:.4f} ({chan['width_pct']}%) | "
        f"Hurst: {h} | Kill-Switch: ${kill_switch_p:.4f} | Cap: ${total_grid_cap:.2f} USDT",
        "trade"
    )
    bot.save_state()
    return grid


def manage_active_bounded_grid(bot):
    """
    Monitorea la Malla Acotada activa.
    1. Ejecuta Kill-Switch si el precio rompe el soporte del canal.
    2. Llena órdenes de compra pendientes cuando el precio retrocede.
    3. Cosecha ganancias (Take Profit) cuando el precio revierte hacia la resistencia o media.
    """
    grid = getattr(bot, "active_grid", None)
    if not grid or grid.status != "ACTIVE":
        return

    sym = grid.symbol
    try:
        ticker = exchange.fetch_ticker(sym)
        curr_p = float(ticker.get("last", 0.0) or 0.0)
    except Exception:
        return

    if curr_p <= 0:
        return

    grid.current_price = curr_p
    total_inv = grid.get_total_inventory()
    invested_cap = grid.get_invested_capital()
    avg_entry = grid.get_average_entry()

    if total_inv > 0 and avg_entry > 0:
        grid.unrealized_pnl = (curr_p - avg_entry) * total_inv
        unrealized_pct = (curr_p - avg_entry) / avg_entry * 100.0
    else:
        grid.unrealized_pnl = 0.0
        unrealized_pct = 0.0

    # 0. Auto-cancelación de mallas fantasma (sin inventario real ejecutado)
    if total_inv == 0:
        if curr_p >= grid.midpoint or (time.time() - grid.created_at > 600):
            bot.add_log(f"⚪ MALLA FANTASMA CANCELADA: {sym} cotiza a ${curr_p:.4f} sin retroceso a niveles de compra. Bot liberado al 100%.", "info")
            bot.active_grid = None
            bot.active_mode = "SWING_SNIPER"
            bot.save_state()
            return

    # 1. Kill-Switch Estricto (Garantía Anti-Atrapamiento)
    if curr_p <= grid.kill_switch_price:
        exit_fee = (curr_p * total_inv) * FEE_RATE if total_inv > 0 else 0.0
        gross_pnl = (curr_p - avg_entry) * total_inv if total_inv > 0 else 0.0
        net_pnl = gross_pnl - exit_fee
        bot.cash += (invested_cap + net_pnl)
        reason = f"🛑 KILL-SWITCH MALLA: Canal roto en {sym} @ ${curr_p:.4f} (Stop {-abs(unrealized_pct):.2f}%)"
        bot.add_log(f"{reason} | PnL: {net_pnl:+.4f} USDT | Capital protegido.", "trade")
        if total_inv > 0:
            bot.db.log_trade(
                symbol=sym,
                side="SELL",
                price=curr_p,
                amount=total_inv,
                capital=invested_cap,
                pnl=net_pnl,
                fee=exit_fee,
                order_id=f"{grid.grid_id}_KILL",
                target_price=grid.channel_resistance,
                stop_price=grid.kill_switch_price,
                note=reason,
                mode="BOUNDED_GRID",
                parent_trade_id=grid.grid_id
            )
            bot.db.log_autopsy(
                trade_id=grid.grid_id,
                symbol=sym,
                pnl=net_pnl,
                pnl_pct=unrealized_pct,
                duration_s=time.time() - grid.created_at,
                mfe_pct=0.0,
                mae_pct=unrealized_pct,
                exit_reason=reason,
                classification="GRID_KILL_SWITCH",
                btc_regime="CHOP_COMPRESSION",
                lesson_learned=f"Canal horizontal de {sym} perforado. Kill-Switch liquidó inventario evitando atrapamiento.",
                adaptive_action="Enfriamiento de 15m en el par y re-verificación de Hurst."
            )
        bot.cooldowns[sym] = time.time() + 900  # 15 min cooldown
        bot.active_grid = None
        bot.active_mode = "SWING_SNIPER"
        bot.save_state()
        return

    # 2. Ejecutar Fills de Niveles Pendientes
    for lvl in grid.levels:
        if lvl.status == "PENDING" and curr_p <= lvl.price:
            if bot.cash >= lvl.capital:
                bot.cash -= lvl.capital
                lvl.status = "FILLED"
                lvl.fill_price = curr_p
                lvl.fill_time = time.time()
                bot.add_log(f"📥 MALLA FILL Nivel {lvl.level_idx+1}/3 en {sym} @ ${curr_p:.4f} (${lvl.capital:.2f} USDT)", "trade")
                bot.db.log_trade(
                    symbol=sym,
                    side="BUY",
                    price=curr_p,
                    amount=lvl.amount,
                    capital=lvl.capital,
                    pnl=0.0,
                    fee=lvl.capital * FEE_RATE,
                    order_id=f"{grid.grid_id}_L{lvl.level_idx+1}",
                    target_price=grid.channel_resistance,
                    stop_price=grid.kill_switch_price,
                    note=f"📥 MALLA FILL N{lvl.level_idx+1}/3 @ ${curr_p:.4f}",
                    mode="BOUNDED_GRID",
                    parent_trade_id=grid.grid_id
                )
                bot.save_state()

    # 3. Cosecha de Ganancias (Take Profit / Reversión a la Media)
    is_above_midpoint_with_profit = (curr_p >= grid.midpoint and curr_p >= avg_entry * 1.0030)
    is_resistance_hit = (curr_p >= grid.channel_resistance)
    if total_inv > 0 and (is_resistance_hit or is_above_midpoint_with_profit):
        exit_fee = (curr_p * total_inv) * FEE_RATE
        gross_pnl = (curr_p - avg_entry) * total_inv
        net_pnl = gross_pnl - exit_fee
        bot.cash += (invested_cap + net_pnl)
        pnl_pct = (net_pnl / invested_cap) * 100.0
        reason = f"🏆 COSECHA MALLA CHOP en {sym} @ ${curr_p:.4f} (+{pnl_pct:.2f}%)"
        bot.add_log(f"{reason} | PnL: +${net_pnl:.4f} USDT | Capital devuelto a caja.", "trade")
        bot.db.log_trade(
            symbol=sym,
            side="SELL",
            price=curr_p,
            amount=total_inv,
            capital=invested_cap,
            pnl=net_pnl,
            fee=exit_fee,
            order_id=f"{grid.grid_id}_HARVEST",
            target_price=grid.channel_resistance,
            stop_price=grid.kill_switch_price,
            note=reason,
            mode="BOUNDED_GRID",
            parent_trade_id=grid.grid_id
        )
        bot.db.log_autopsy(
            trade_id=grid.grid_id,
            symbol=sym,
            pnl=net_pnl,
            pnl_pct=pnl_pct,
            duration_s=time.time() - grid.created_at,
            mfe_pct=pnl_pct,
            mae_pct=0.0,
            exit_reason=reason,
            classification="GRID_CHOP_HARVEST",
            btc_regime="CHOP_COMPRESSION",
            lesson_learned=f"Reversión a la media exitosa en {sym} (Hurst: {grid.hurst_exponent}). Ganancia cosechada sin acumulación.",
            adaptive_action="Capital liberado a caja listo para siguiente ciclo."
        )
        bot.cooldowns[sym] = time.time() + 300  # 5 min cooldown tras win
        bot.active_grid = None
        bot.active_mode = "SWING_SNIPER"
        bot.save_state()
        return

    filled_cnt = len(grid.get_filled_levels())
    bot.status_msg = f"🟡 Malla Chop {sym}: {filled_cnt}/3 niveles ({unrealized_pct:+.2f}%) | Kill-Switch: ${grid.kill_switch_price:.4f} | Hurst: {grid.hurst_exponent}"
