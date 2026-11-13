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
    TURBO_MIN_SCORE,
    SNIPER_LEVERAGE
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
from risk.shadow_veto_tracker import register_shadow_veto, update_shadow_veto_tracking
from grid.bounded_grid import scan_bounded_grid_candidates, manage_active_bounded_grid
from server.routes import start_swing_dashboard
from execution.depth_slippage import evaluate_execution_route
from execution.stale_guard import sanitize_execution_context
from auditor.reconciler import QuantitativeReconciler


def execute_swing_paper_entry(bot: SwingBot, opp: Dict[str, Any]):
    """Abre una posición con confirmación de ruptura 15m + Interés Compuesto y enlace de ID."""
    sym = opp["symbol"]
    if sym in bot.active_trades:
        return
    if len(bot.active_trades) >= bot.get_max_concurrent_trades():
        return
    if getattr(bot, "global_cooldown_until", 0.0) > time.time():
        return

    curr_p = opp["price"]
    atr_p = opp.get("atr_15m_pct", 2.0)
    trade_capital = bot.calculate_trade_capital(current_atr_pct=atr_p)
    if trade_capital < 15.0 or curr_p <= 0 or bot.cash < trade_capital:
        return

    # --- FILTRO CENTINELA: APERTURA INSTITUCIONAL WALL STREET (14:30-14:40 UTC / 10:30-10:40 Local) ---
    # Durante los primeros 10 minutos de la campana de apertura de EE.UU., los creadores de mercado
    # ejecutan barridas masivas de liquidez y falsos rompimientos de alta volatilidad errática.
    from datetime import datetime, timezone
    utc_now = datetime.now(timezone.utc)
    # Lunes a Viernes (0 a 4)
    if utc_now.weekday() < 5 and (utc_now.hour == 14 and 30 <= utc_now.minute < 40):
        bell_reason = f"Apertura EE.UU. (14:{utc_now.minute:02d} UTC): Pausa defensiva de 10m contra barridas de apertura"
        bot.add_log(f"🛡️ [VETO APERTURA WALL STREET] Disparo cancelado en {sym}: {bell_reason}", "info")
        register_shadow_veto(
            bot=bot,
            symbol=sym,
            veto_type="OPENING_BELL_GUARD",
            reason=bell_reason,
            opp=opp,
            curr_p=curr_p,
            trade_capital=trade_capital,
            leverage=leverage
        )
        bot.cooldowns[sym] = time.time() + 180
        return

    # --- FILTRO CENTINELA DE ORDER FLOW (Microestructura L2 & Tape) ---
    flow = fetch_order_flow_confirmation(sym, exchange)
    if not flow.get("confirmed", True):
        reason_msg = f"{flow['reason']} (OBI: {flow['obi']:+.2f} | Compras: {flow['buy_ratio_pct']:.1f}% | Spread: {flow['spread_pct']:.2f}%)"
        bot.add_log(
            f"🛡️ [VETO ORDER FLOW] Disparo cancelado en {sym}: {reason_msg}",
            "info"
        )
        register_shadow_veto(
            bot=bot,
            symbol=sym,
            veto_type="ORDER_FLOW",
            reason=reason_msg,
            opp=opp,
            curr_p=curr_p,
            trade_capital=trade_capital,
            leverage=leverage
        )
        bot.cooldowns[sym] = time.time() + 180  # Cooldown 3m para re-evaluar
        return

    # --- FILTRO INSTITUCIONAL DE COTIZACIÓN CADUCA Y SPREAD (GRADO 10) ---
    quote_ts = opp.get("timestamp_ms")
    bid_p = opp.get("bid", curr_p * 0.9997)
    ask_p = opp.get("ask", curr_p * 1.0003)
    stale_check = sanitize_execution_context(sym, bid=bid_p, ask=ask_p, quote_timestamp_ms=quote_ts)
    if not stale_check["safe_to_execute"]:
        reasons_str = "; ".join(stale_check["rejection_reasons"])
        bot.add_log(f"🛡️ [VETO GRADO 10: STALE GUARD] Disparo cancelado en {sym}: {reasons_str}", "warn")
        register_shadow_veto(
            bot=bot,
            symbol=sym,
            veto_type="STALE_GUARD",
            reason=reasons_str,
            opp=opp,
            curr_p=curr_p,
            trade_capital=trade_capital,
            leverage=leverage
        )
        bot.cooldowns[sym] = time.time() + 120
        return

    # --- FILTRO INSTITUCIONAL DE DESLIZAMIENTO Y VWAP POR PROFUNDIDAD (GRADO 10) ---
    try:
        raw_ob = exchange.fetch_order_book(sym, limit=10)
        route_decision = evaluate_execution_route(
            symbol=sym,
            target_capital=trade_capital,
            expected_gain_pct=opp.get("target_pct", 2.5),
            orderbook=raw_ob,
            side="BUY"
        )
        if route_decision["slippage_pct"] > 0.20:
            slip_reason = f"Deslizamiento {route_decision['slippage_pct']:.3f}% supera tolerancia (Impacto: {route_decision['market_impact_bps']:.1f} bps)"
            bot.add_log(
                f"🛡️ [VETO GRADO 10: SLIPPAGE EXCESIVO] {sym}: {slip_reason}",
                "warn"
            )
            register_shadow_veto(
                bot=bot,
                symbol=sym,
                veto_type="SLIPPAGE_VWAP",
                reason=slip_reason,
                opp=opp,
                curr_p=curr_p,
                trade_capital=trade_capital,
                leverage=leverage
            )
            bot.cooldowns[sym] = time.time() + 180
            return
    except Exception:
        pass

    # --- CLASIFICACIÓN DE CONVICCIÓN Y APALANCAMIENTO x2 ---
    is_grade_a = opp.get("is_grade_a_turbo", False)
    flow_confirmed = (flow.get("buy_ratio_pct", 50.0) >= 60.0 and flow.get("obi", 0.0) >= 0.15)
    is_turbo = is_grade_a and flow_confirmed and (opp.get("score", 0.0) >= TURBO_MIN_SCORE)
    leverage = TURBO_LEVERAGE if is_turbo else SNIPER_LEVERAGE

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
            f"🎯 DISPARO V2 x{leverage:.0f} #{order_id}: {sym} @ ${curr_p:.4f} | {rs_info} | {of_info} | "
            f"Margen: ${trade_capital:.2f} USDT (Notional x{leverage:.0f}: ${effective_cap:.2f}) | "
            f"Target: ${target_p:.4f} (+{target_pct*100:.2f}%) | Stop: ${stop_p:.4f} (-{stop_pct*100:.2f}%) | R:R {rr}:1",
            "trade"
        )
        entry_note = f"🎯 Disparo V2 x{leverage:.0f} #{order_id} (Notional ${effective_cap:.2f} | R:R {rr}:1 | Vol {opp.get('vol_spike', 0):.1f}x | {of_info})"

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
    reconciler = QuantitativeReconciler(bot.db.db_path)
    last_reconcile_time = time.time() - 3300.0  # Primera verificación a los 5 minutos de arrancar
    try:
        bot.real_grid_stats = fetch_real_pionex_grid_stats()
    except Exception:
        pass
    start_swing_dashboard(bot, SWING_HTTP_PORT)

    scan_th = threading.Thread(target=swing_telemetry_thread, args=(bot,), daemon=True)
    scan_th.start()

    time.sleep(3.0)

    while True:
        try:
            now_ts = time.time()

            # Auditoría Triple-Ledger Recurrente (Grado 10: cada 1 hora)
            if now_ts - last_reconcile_time >= 3600.0:
                last_reconcile_time = now_ts
                rec_res = reconciler.reconcile_swing_engine(bot)
                if rec_res["is_balanced"]:
                    bot.add_log(f"⚖️ [AUDITORÍA TRIPLE-LEDGER GRADO 10] Balance íntegro: {rec_res['status']} (Delta: {rec_res['delta_usdt']:+.4f} USDT)", "info")
                else:
                    bot.add_log(f"⚠️ [AUDITORÍA TRIPLE-LEDGER GRADO 10] Alerta: {rec_res['details']}", "warn")
            btc_ctx = update_btc_context()
            btc_regime = btc_ctx.get("regime", "NEUTRAL_TRANSITION")

            # 1. Monitoreo de posiciones vivas y Shadow Tracking de Vetos
            manage_active_swing_trade(bot)
            manage_active_bounded_grid(bot)
            update_shadow_veto_tracking(bot, exchange)

            has_active_swing = len(bot.active_trades) > 0
            has_active_grid = (getattr(bot, "active_grid", None) is not None and bot.active_grid.status == "ACTIVE")

            # 2. Conmutación de Régimen y Ejecución Dinámica Core + Satélite Barbell
            plan = bot.get_portfolio_allocation_plan(btc_regime) if hasattr(bot, "get_portfolio_allocation_plan") else None
            max_swings = plan["max_swings"] if plan else bot.get_max_concurrent_trades()
            max_grids = plan["max_grids"] if plan else 1
            current_swings = len(bot.active_trades)
            active_grids_list = bot.get_active_grids() if hasattr(bot, "get_active_grids") else ([bot.active_grid] if getattr(bot, "active_grid", None) else [])
            current_grids = len(active_grids_list)

            # Pausa portfolio-wide si está activo el enfriamiento global post-stop
            if getattr(bot, "global_cooldown_until", 0.0) > now_ts:
                remaining = int(bot.global_cooldown_until - now_ts)
                bot.status_msg = f"🛡️ ENFRIAMIENTO GLOBAL POST-STOP ({remaining}s): Pausa preventiva para asentar volatilidad..."
                time.sleep(2.5)
                continue

            # Régimen 3: Dump bajista de BTC -> MODO BÚNKER 100% CAJA
            if btc_regime == "BEARISH_DUMP":
                bot.active_mode = "CASH_VAULT"
                bot.status_msg = "🛡️ MODO BÚNKER (Caja 100%): BTC en corrección bajista. Disparos y mallas bloqueados."
                time.sleep(2.5)
                continue

            # Slot A: Swing Sniper (Longs Direccionales de Alta Convicción)
            can_open_swing = (current_swings < max_swings) and (bot.cash >= 20.0)
            if can_open_swing and btc_regime in ("BULLISH_EXPANSION", "NEUTRAL_TRANSITION"):
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
                    # Priorizar por Convicción x Velocidad de Expansión (Score + Bonus de ATR/Beta para acelerar rallies)
                    ready_opps.sort(key=lambda o: (o.get("score", 0.0) + min(o.get("atr_pct", 1.5) * 2.0, 8.0)), reverse=True)
                    best = ready_opps[0]
                    execute_swing_paper_entry(bot, best)
                else:
                    top = telemetry[0] if telemetry else None
                    if top and not bot.active_trades:
                        cooldown_active = bot.cooldowns.get(top["symbol"], 0.0) > now_ts
                        anti_badge = f" [Anti-Ametralladora: Min Score {effective_min_score:.0f}]" if is_recovering_from_stop else ""
                        cd_badge = " (Cooldown activo)" if cooldown_active else ""
                        bot.status_msg = f"Radar V2: Líder {top['symbol']} (Score {top['score']}/100 | RS {top.get('rs_vs_btc', 0):+.1f}pp | {top['status']}){cd_badge}{anti_badge}."

            # Slot B: Mallas Acotadas (Satélite de Reversión a la Media)
            # DESACTIVADO EN CUENTAS <$100 (Tier 1):
            # En cuentas pequeñas (<$100), la malla arriesgaba el 85% del capital ($51 USDT) perdiendo ~$1.00 en Kill-Switch
            # para ganar apenas +$0.20 en cosechas (R:R asimétrico negativo 5:1 en contra).
            # Por mandato cuantitativo de EV positivo, la cuenta opera 100% en SWING SNIPER ASIMÉTRICO (R:R 2.4:1 a favor).
            is_tier_1 = (plan is None or plan["tier"] == 1)
            can_open_grid = (not is_tier_1) and (current_grids < max_grids) and (bot.cash >= 40.0)
            if can_open_grid:
                grid_target_cap = plan.get("grid_cap") if plan else None
                scan_bounded_grid_candidates(bot, target_cap=grid_target_cap)
                if not bot.active_grid:
                    bot.status_msg = "🟡 MODO CHOP/SATÉLITE: Escaneando activos con reversión comprobada (Hurst < 0.46)..."

            time.sleep(2.5)

        except KeyboardInterrupt:
            print("\nDeteniendo Swing Engine V2...", flush=True)
            break
        except Exception as e:
            bot.add_log(f"Error en bucle swing: {e}", "error")
            time.sleep(5.0)
