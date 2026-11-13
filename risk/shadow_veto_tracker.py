"""
Módulo de Seguimiento en la Sombra de Vetos Institucionales (Shadow Veto Tracker).
Registra y audita qué habría pasado con cada oportunidad vetada por Order Flow,
Stale Guard o Slippage excesivo para calcular el capital salvado y aprender si los
filtros están demasiado estrictos o perfectamente calibrados.
"""

import time
import logging
from typing import Any, Dict, List
from datetime import datetime

logger = logging.getLogger("ShadowVetoTracker")


def register_shadow_veto(bot: Any, symbol: str, veto_type: str, reason: str,
                         opp: Dict[str, Any], curr_p: float, trade_capital: float,
                         leverage: float = 2.0, horizon_seconds: float = 3600.0) -> int:
    """Registra una orden descartada para seguimiento contrafactual."""
    target_p = float(opp.get("target_price", curr_p * (1.0 + opp.get("target_pct", 0.035))))
    stop_p = float(opp.get("stop_price", curr_p * (1.0 - opp.get("stop_pct", 0.018))))
    target_pct = float(opp.get("target_pct", 0.035))
    stop_pct = float(opp.get("stop_pct", 0.018))

    try:
        veto_id = bot.db.log_veto_candidate(
            symbol=symbol,
            veto_type=veto_type,
            reason=reason,
            veto_price=curr_p,
            target_price=target_p,
            stop_price=stop_p,
            target_pct=target_pct,
            stop_pct=stop_pct,
            capital=trade_capital,
            leverage=leverage,
            horizon_seconds=horizon_seconds
        )
        return veto_id
    except Exception as e:
        logger.error(f"Error registrando shadow veto en {symbol}: {e}")
        return 0


def update_shadow_veto_tracking(bot: Any, exchange: Any):
    """
    Evalúa periódicamente (cada ciclo) los vetos abiertos en SQLite.
    Compara precio actual, actualiza MFE / MAE y determina el resultado:
    - SAVED_LOSS_STOP: Habría tocado el Stop Loss (capital salvado).
    - MISSED_WIN: Habría tocado el Target a pesar del veto.
    - EXPIRED_NEUTRAL: Terminó la ventana de 1 hora sin tocar stop ni target.
    """
    try:
        open_vetoes = bot.db.get_open_vetoes()
        if not open_vetoes:
            return

        now = time.time()
        for v in open_vetoes:
            v_id = v["id"]
            sym = v["symbol"]
            veto_p = float(v["veto_price"])
            tgt_p = float(v["target_price"])
            stp_p = float(v["stop_price"])
            cap = float(v["capital"])
            lev = float(v.get("leverage", 2.0))
            max_p = max(float(v["max_price"]), veto_p)
            min_p = min(float(v["min_price"]), veto_p)
            expires_at = float(v["expires_at"])
            entry_ts = datetime.fromisoformat(v["timestamp"]).timestamp() if "T" in v["timestamp"] else now
            duration_s = now - entry_ts

            try:
                ticker = exchange.fetch_ticker(sym)
                curr_p = float(ticker.get("last", 0.0) or 0.0)
            except Exception:
                continue

            if curr_p <= 0.0:
                continue

            # Actualizar extremos de precio
            if curr_p > max_p:
                max_p = curr_p
            if curr_p < min_p:
                min_p = curr_p

            mfe_pct = ((max_p - veto_p) / veto_p) * 100.0
            mae_pct = ((min_p - veto_p) / veto_p) * 100.0

            outcome = None
            insight = ""
            hypo_pnl = 0.0
            hypo_pnl_pct = 0.0

            # 1. ¿Habría tocado el Stop Loss? (Pérdida salvada)
            if curr_p <= stp_p or min_p <= stp_p:
                outcome = "SAVED_LOSS_STOP"
                hypo_loss_pct = -abs(v["stop_pct"]) * lev * 100.0
                hypo_pnl = (hypo_loss_pct / 100.0) * cap
                hypo_pnl_pct = hypo_loss_pct
                insight = (
                    f"🛡️ Filtro de {v['veto_type']} salvó ${abs(hypo_pnl):.2f} USDT: "
                    f"El activo cayó {mae_pct:.2f}% y tocó el stop en ${stp_p:.4f}."
                )
                bot.add_log(f"🧠 [SHADOW LEARNING] {insight}", "info")

            # 2. ¿Habría tocado el Target? (Oportunidad perdida)
            elif curr_p >= tgt_p or max_p >= tgt_p:
                outcome = "MISSED_WIN"
                hypo_win_pct = abs(v["target_pct"]) * lev * 100.0
                hypo_pnl = (hypo_win_pct / 100.0) * cap
                hypo_pnl_pct = hypo_win_pct
                insight = (
                    f"⚠️ Filtro de {v['veto_type']} fue demasiado conservador: "
                    f"El activo avanzó +{mfe_pct:.2f}% hasta target ${tgt_p:.4f} (+${hypo_pnl:.2f} USDT perdidos)."
                )
                bot.add_log(f"🧠 [SHADOW LEARNING] {insight}", "warn")

            # 3. ¿Expiró la ventana temporal de observación (1 hora)?
            elif now >= expires_at:
                outcome = "SAVED_LOSS_TIME" if curr_p < veto_p else "EXPIRED_NEUTRAL"
                diff_pct = ((curr_p - veto_p) / veto_p) * lev * 100.0
                hypo_pnl = (diff_pct / 100.0) * cap
                hypo_pnl_pct = diff_pct
                if outcome == "SAVED_LOSS_TIME":
                    insight = (
                        f"🛡️ Filtro {v['veto_type']} evitó desgaste: A 1h cotiza {diff_pct:+.2f}% "
                        f"(Salvó ${abs(hypo_pnl):.2f} USDT)."
                    )
                else:
                    insight = f"⚖️ Veto neutro en {sym}: A 1h cotiza {diff_pct:+.2f}% sin alcanzar targets."
                bot.add_log(f"🧠 [SHADOW LEARNING] {insight}", "info")

            # Si se cerró la observación
            if outcome:
                bot.db.update_veto_autopsy(
                    veto_id=v_id,
                    max_price=max_p,
                    min_price=min_p,
                    final_price=curr_p,
                    mfe_pct=round(mfe_pct, 2),
                    mae_pct=round(mae_pct, 2),
                    hypothetical_pnl=round(hypo_pnl, 4),
                    hypothetical_pnl_pct=round(hypo_pnl_pct, 2),
                    outcome=outcome,
                    learning_insight=insight,
                    duration_s=round(duration_s, 1),
                    status="CLOSED"
                )
            else:
                # Actualizar estado intermedio
                bot.db.update_veto_autopsy(
                    veto_id=v_id,
                    max_price=max_p,
                    min_price=min_p,
                    final_price=curr_p,
                    mfe_pct=round(mfe_pct, 2),
                    mae_pct=round(mae_pct, 2),
                    hypothetical_pnl=round(((curr_p - veto_p)/veto_p)*lev*cap, 4),
                    hypothetical_pnl_pct=round(((curr_p - veto_p)/veto_p)*lev*100.0, 2),
                    outcome="TRACKING",
                    learning_insight=f"MFE +{mfe_pct:.2f}% | MAE {mae_pct:.2f}%",
                    duration_s=round(duration_s, 1),
                    status="OPEN"
                )
    except Exception as e:
        logger.error(f"Error actualizando shadow vetoes: {e}")
