"""
Motor Principal de Ejecución y Orquestación del Swing Sniper & Bounded Grid.
Coordina el escaneo de mercado, telemetría, ordenamiento, ejecuciones de entrada y ciclo de control.
"""
import time
import threading
from typing import Dict, Any, List, Optional

from config import (
    exchange,
    FEE_RATE,
    SWING_HTTP_PORT,
    MIN_SCORE_V2,
    POST_STOP_EXTRA_SCORE,
    TURBO_LEVERAGE,
    TURBO_MIN_SCORE
)
from engine.bot_models import SwingTrade
from engine.swing_bot import SwingBot
from scoring.order_flow import fetch_order_flow_confirmation
from scoring.market_scanner import (
    update_btc_context,
    scan_market_top_movers,
    fetch_real_pionex_grid_stats
)
from scoring.breakout import analyze_breakout_15m
from risk.risk_manager import manage_active_swing_trade
from grid.bounded_grid import scan_bounded_grid_candidates, manage_active_bounded_grid
from server.routes import start_swing_dashboard


def execute_swing_paper_entry(bot: SwingBot, opp: Dict[str, Any]):
    """Abre una posición con confirmación de ruptura 15m + Interés Compuesto y enlace de ID."""
    sym = opp["symbol"]
    if sym in bot.active_trades:
        return
    if len(bot.active_trades) >= bot.get_max_concurrent_trades():
        return

    curr_p = opp["price"]
    trade_capital = bot.calculate_trade_capital()
    if trade_capital < 15.0 or curr_p <= 0 or bot.cash < trade_capital:
        return

    # --- FILTRO CENTINELA DE ORDER FLOW (Microestructura L2 & Tape) ---
    flow = fetch_order_flow_confirmation(sym, exchange)
    if not flow.get("confirmed", True):
        bot.add_log(
            f"🛡️ [VETO ORDER FLOW] Disparo cancelado en {sym}: {flow['reason']} "
            f"(OBI: {flow['obi']:+.2f} | Compras: {flow['buy_ratio_pct']:.1f}% | Spread: {flow['spread_pct']:.2f}%)",
            "info"
        )
        bot.cooldowns[sym] = time.time() + 180  # Cooldown 3m para re-evaluar
        return

    # --- CLASIFICACIÓN DE CONVICCIÓN GRADE A+ (APALANCAMIENTO x2) ---
    is_grade_a = opp.get("is_grade_a_turbo", False)
    flow_confirmed = (flow.get("buy_ratio_pct", 50.0) >= 60.0 and flow.get("obi", 0.0) >= 0.15)
    is_turbo = is_grade_a and flow_confirmed and (opp.get("score", 0.0) >= TURBO_MIN_SCORE)
    leverage = TURBO_LEVERAGE if is_turbo else 1.0

    # Capital efectivo con apalancamiento x2 (Notional)
    effective_cap = trade_capital * leverage
    if curr_p >= 1000:
        amount = round(effective_cap / curr_p, 6)
    elif curr_p >= 1:
        amount = round(effective_cap / curr_p, 4)
    else:
        amount = round(effective_cap / curr_p, 2)

    target_p = opp["target_price"]
    stop_p = opp["stop_price"]
    target_pct = opp["target_pct"] / 100.0
    stop_pct = opp["stop_pct"] / 100.0
    atr_p = opp["atr_15m_pct"]
    rr = opp["rr_ratio"]

    bot.sim_order_seq += 1
    order_id = f"SWING_{bot.sim_order_seq}"

    bot.cash -= trade_capital
    entry_fee = effective_cap * FEE_RATE

    trade = SwingTrade(
        trade_id=order_id,
        symbol=sym,
        entry_price=curr_p,
        amount=amount,
        capital=trade_capital,
        target_price=target_p,
        stop_price=stop_p,
        initial_stop=stop_p,
        target_pct=target_pct,
        stop_pct=stop_pct,
        atr_pct=atr_p,
        rr_ratio=rr,
        entry_time=time.time(),
        entry_fee=entry_fee,
        of_obi=flow.get("obi", 0.0),
        of_buy_ratio=flow.get("buy_ratio_pct", 50.0),
        leverage=leverage,
        is_turbo=is_turbo
    )
    bot.active_trades[sym] = trade
    rs_info = f"RS vs BTC: {opp.get('rs_vs_btc', 0):+.1f}pp"
    of_info = f"OF: OBI {flow['obi']:+.2f}, Compras {flow['buy_ratio_pct']:.1f}%"
    is_ign = opp.get("is_momentum_ignition", False)

    if is_turbo:
        bot.add_log(
            f"⚡ [GRADE A+ HYPER-SNIPER x2] OLA DE ALTA CONVICCIÓN en {sym}: Vol {opp.get('vol_spike', 0):.1f}x | {rs_info} | {of_info} | "
            f"Margen: ${trade_capital:.2f} USDT (Notional x2: ${effective_cap:.2f}) | Target 3.8R: ${target_p:.4f} (+{target_pct*100:.2f}%) | "
            f"Stop: ${stop_p:.4f} (-{stop_pct*100:.2f}%) | Time-Stop: 25m",
            "trade"
        )
        entry_note = f"⚡ Turbo A+ x2 #{order_id} (Notional ${effective_cap:.2f} | R:R {rr}:1 | Vol {opp.get('vol_spike', 0):.1f}x | {of_info})"
    elif is_ign:
        bot.add_log(
            f"🚀 [IGNICIÓN MOMENTUM] OLA INSTITUCIONAL en {sym}: Vol {opp.get('vol_spike', 0):.1f}x | {rs_info} | {of_info} | "
            f"${trade_capital:.2f} USDT | Target 3.8R: ${target_p:.4f} (+{target_pct*100:.2f}%) | "
            f"Stop: ${stop_p:.4f} (-{stop_pct*100:.2f}%) | R:R {rr}:1",
            "trade"
        )
        entry_note = f"🚀 Ignición Momentum #{order_id} (R:R {rr}:1 | Vol {opp.get('vol_spike', 0):.1f}x | {of_info})"
    else:
        bot.add_log(
            f"🎯 DISPARO V2 #{order_id}: {sym} @ ${curr_p:.4f} | {rs_info} | {of_info} | "
            f"Ruptura 15m + Vol {opp.get('vol_spike', 0):.1f}x | ${trade_capital:.2f} USDT | "
            f"Target: ${target_p:.4f} (+{target_pct*100:.2f}%) | Stop: ${stop_p:.4f} (-{stop_pct*100:.2f}%) | R:R {rr}:1",
            "trade"
        )
        entry_note = f"V2 Entry #{order_id} (R:R {rr}:1 | {of_info} | RS {opp.get('rs_vs_btc', 0):+.1f}pp)"

    bot.db.log_trade(
        symbol=sym,
        side="BUY",
        price=curr_p,
        amount=amount,
        capital=trade_capital,
        pnl=0.0,
        fee=entry_fee,
        order_id=order_id,
        target_price=target_p,
        stop_price=stop_p,
        note=entry_note,
        parent_trade_id=order_id
    )
    bot.save_state()


def swing_telemetry_thread(bot: SwingBot):
    """Escanea el mercado dinámicamente buscando candidatos con Fuerza Relativa y Rupturas 15m."""
    print("  📡 [SWING RADAR V2] Motor dinámico de Fuerza Relativa & Ruptura 15m activo.", flush=True)
    last_grid_check = 0.0

    while True:
        try:
            bot.scan_cycle += 1
            btc_ctx = update_btc_context()
            movers = scan_market_top_movers()

            results = []
            for cand in movers:
                try:
                    res = analyze_breakout_15m(cand["symbol"], btc_ctx, bot.settings)
                    if res:
                        results.append(res)
                except Exception:
                    continue

            results.sort(key=lambda x: x["score"], reverse=True)

            with bot.data_lock:
                bot.radar_telemetry = results

            # Consultar estado de la Malla Real DOGE cada 60s (solo lectura)
            now = time.time()
            if now - last_grid_check >= 60.0:
                grid_info = fetch_real_pionex_grid_stats()
                with bot.data_lock:
                    bot.real_grid_stats = grid_info
                last_grid_check = now

        except Exception as e:
            bot.add_log(f"Error en escaneo radar V2: {e}", "error")

        time.sleep(12.0)


def run_hourly_swing():
    """Bucle principal de orquestación del bot."""
    print("=" * 80, flush=True)
    print("  THE ADAPTIVE SWING SNIPER V2 (RELATIVE STRENGTH & 15m BREAKOUT ENGINE)", flush=True)
    print("  • Modo                           -> PAPER TRADING ESTRICTO (Capital virtual)", flush=True)
    print("  • Seguridad                      -> Malla DOGE Real Pionex INTACTA (Solo Lectura)", flush=True)
    print("  • Estrategia V2                  -> Fuerza Relativa vs BTC + Ruptura 15m + Vol Spike", flush=True)
    print("  • Filtro Anti-Ametralladora      -> Cooldown adaptativo + Exigencia de Score Elevado tras stop", flush=True)
    print("  • Gestión de Riesgo              -> Stop Dinámico 1.2x-2.2x ATR | Break-Even Dinámico | Trailing Oxígeno 1.5x ATR", flush=True)
    print("  • Motor Adaptativo               -> Ventana Móvil 20 Trades + Tasa de Aprendizaje Decreciente", flush=True)
    print(f"  • Dashboard Integrado            -> http://localhost:{SWING_HTTP_PORT}", flush=True)
    print("=" * 80, flush=True)

    bot = SwingBot()
    start_swing_dashboard(bot, SWING_HTTP_PORT)

    scan_th = threading.Thread(target=swing_telemetry_thread, args=(bot,), daemon=True)
    scan_th.start()

    time.sleep(3.0)

    while True:
        try:
            now_ts = time.time()
            btc_ctx = update_btc_context()
            btc_regime = btc_ctx.get("regime", "NEUTRAL_TRANSITION")

            # 1. Monitoreo de posiciones vivas
            manage_active_swing_trade(bot)
            manage_active_bounded_grid(bot)

            has_active_swing = len(bot.active_trades) > 0
            has_active_grid = (getattr(bot, "active_grid", None) is not None and bot.active_grid.status == "ACTIVE")

            # 2. Conmutación de Régimen y Ejecución Dual
            if not has_active_swing and not has_active_grid:
                # Régimen 1: Expansión alcista o consolidación normal -> MODO SWING SNIPER
                if btc_regime in ("BULLISH_EXPANSION", "NEUTRAL_TRANSITION"):
                    bot.active_mode = "SWING_SNIPER"
                    max_concurrent = bot.get_max_concurrent_trades()
                    current_active_count = len(bot.active_trades)

                    if current_active_count < max_concurrent:
                        with bot.data_lock:
                            telemetry = list(bot.radar_telemetry)

                        time_since_last_stop = now_ts - getattr(bot, "last_stop_time", 0.0)
                        is_recovering_from_stop = time_since_last_stop < 300.0
                        base_min_score = bot.settings.get("min_score", MIN_SCORE_V2)
                        extra_score = bot.settings.get("post_stop_extra_score", POST_STOP_EXTRA_SCORE)
                        effective_min_score = (base_min_score + extra_score) if is_recovering_from_stop else base_min_score

                        ready_opps = [
                            o for o in telemetry
                            if o.get("trigger_ready")
                            and o.get("score", 0.0) >= effective_min_score
                            and bot.cooldowns.get(o["symbol"], 0.0) <= now_ts
                            and o["symbol"] not in bot.active_trades
                        ]

                        if ready_opps:
                            best = ready_opps[0]
                            execute_swing_paper_entry(bot, best)
                        else:
                            top = telemetry[0] if telemetry else None
                            if top and not bot.active_trades:
                                cooldown_active = bot.cooldowns.get(top["symbol"], 0.0) > now_ts
                                anti_badge = f" [Anti-Ametralladora: Min Score {effective_min_score:.0f}]" if is_recovering_from_stop else ""
                                cd_badge = " (Cooldown activo)" if cooldown_active else ""
                                bot.status_msg = f"Radar V2: Líder {top['symbol']} (Score {top['score']}/100 | RS {top.get('rs_vs_btc', 0):+.1f}pp | {top['status']}){cd_badge}{anti_badge}."

                # Régimen 2: Compresión lateral (Chop) -> MODO MALLA ACOTADA
                elif btc_regime == "CHOP_COMPRESSION":
                    bot.active_mode = "BOUNDED_GRID"
                    scan_bounded_grid_candidates(bot)
                    if not bot.active_grid:
                        bot.status_msg = "🟡 MODO CHOP: Escaneando activos con reversión comprobada (Hurst < 0.45)..."

                # Régimen 3: Dump bajista de BTC -> MODO BÚNKER 100% CAJA
                elif btc_regime == "BEARISH_DUMP":
                    bot.active_mode = "CASH_VAULT"
                    bot.status_msg = "🛡️ MODO BÚNKER (Caja 100%): BTC en corrección bajista. Disparos y mallas bloqueados."

            time.sleep(2.5)

        except KeyboardInterrupt:
            print("\nDeteniendo Swing Engine V2...", flush=True)
            break
        except Exception as e:
            bot.add_log(f"Error en bucle swing: {e}", "error")
            time.sleep(5.0)
