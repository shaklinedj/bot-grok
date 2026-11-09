"""
monte_carlo_simulator.py — Simulador Estocástico Prospectivo de Monte Carlo
============================================================================
Proyecta 1,000 trayectorias futuras del precio en los próximos 60-120 minutos
para responder la pregunta matemática clave:
    ¿Qué probabilidad real tiene este activo de chocar contra nuestras órdenes
    de venta con ganancia ANTES de perforar el piso de la malla?

Utiliza la dinámica de reversión a la media acoplada (Ornstein-Uhlenbeck)
con difusión browniana en tiempo continuo discretizado:
    S_{t+dt} = S_t + θ(μ - S_t)dt + σ S_t √dt Z_t,  donde Z ~ N(0, 1)

Métricas proyectivas:
- p_win: Probabilidad de tocar el objetivo de venta antes del piso (0.0 a 1.0)
- p_loss: Probabilidad de perforar el piso de riesgo antes del objetivo (0.0 a 1.0)
- median_time_min: Mediana de minutos estimados para alcanzar la venta
- expected_value_pct: Esperanza matemática neta proyectada (% EV)
- verdict: Veredicto prospectivo ('ALTA_CONVICCION', 'MODERADA', 'VETO_RIESGO')
"""

import numpy as np
from typing import Dict, Any, Optional


def simulate_monte_carlo_forward(
    current_price: float,
    target_price: float,
    floor_price: float,
    theta: float = 0.02,
    mu: Optional[float] = None,
    sigma: Optional[float] = None,
    atr_pct: float = 2.0,
    n_paths: int = 1000,
    horizon_minutes: int = 90,
    dt_minutes: float = 1.0,
    seed: Optional[int] = None
) -> Dict[str, Any]:
    """
    Simula n_paths trayectorias prospectivas hacia adelante en el tiempo.
    Retorna métricas estadísticas de primer cruce (First-Passage Time).
    """
    if current_price <= 0 or target_price <= 0 or floor_price <= 0:
        return {
            "p_win": 0.50,
            "p_loss": 0.50,
            "p_timeout": 0.0,
            "median_time_min": float(horizon_minutes / 2),
            "expected_value_pct": 0.0,
            "mc_score": 50.0,
            "verdict": "DATOS_INVALIDOS",
            "paths_simulated": 0
        }

    # Si target está abajo o floor está arriba, ajustar lógicamente
    if target_price <= current_price:
        target_price = current_price * 1.011  # +1.1% por defecto
    if floor_price >= current_price:
        floor_price = current_price * 0.970   # -3.0% por defecto

    # Parámetros por defecto robustos si OU no está disponible
    if mu is None or mu <= 0:
        mu = current_price
    
    # Deriva theta acotada [0.001, 0.15]
    theta_eff = float(max(0.001, min(0.15, theta if theta > 0 else 0.015)))

    # Sigma relativo (volatilidad por minuto): combinar ATR y OU para reflejar la oscilación real
    atr_vol = ((atr_pct / 100.0) / np.sqrt(60.0)) if atr_pct > 0 else 0.002
    if sigma is None or sigma <= 0:
        vol_per_min = atr_vol
    else:
        # Convertir sigma absoluto de OU a relativo respecto al precio
        ou_vol = float(sigma / current_price) if current_price > 0 else 0.002
        vol_per_min = max(atr_vol, ou_vol)
    vol_per_min = float(max(0.0005, min(0.025, vol_per_min)))

    steps = int(max(15, min(240, horizon_minutes / dt_minutes)))
    
    if seed is not None:
        rng = np.random.default_rng(seed)
    else:
        rng = np.random.default_rng()

    # Generar todos los choques aleatorios Z ~ N(0, 1) en una matriz (steps x n_paths)
    sqrt_dt = np.sqrt(dt_minutes)
    z_matrix = rng.standard_normal((steps, n_paths))

    # Vectorización temporal
    prices = np.zeros((steps + 1, n_paths), dtype=np.float64)
    prices[0, :] = current_price

    curr_p = np.full(n_paths, current_price, dtype=np.float64)
    for t in range(steps):
        drift = theta_eff * (mu - curr_p) * dt_minutes
        diffusion = curr_p * vol_per_min * sqrt_dt * z_matrix[t, :]
        curr_p = np.maximum(0.000001, curr_p + drift + diffusion)
        prices[t + 1, :] = curr_p

    # Análisis de Primer Cruce (First-Passage Time) por trayectoria
    # Máscaras booleanas: shape (steps + 1, n_paths)
    hit_target_mask = prices >= target_price
    hit_floor_mask = prices <= floor_price

    # Encontrar el primer paso de tiempo donde se toca el target o el floor
    # argmax devuelve el primer índice True; si todo es False devuelve 0
    first_target = np.argmax(hit_target_mask, axis=0)
    first_floor = np.argmax(hit_floor_mask, axis=0)

    ever_target = np.any(hit_target_mask, axis=0)
    ever_floor = np.any(hit_floor_mask, axis=0)

    # Clasificación determinista de cada trayectoria
    # 1. Ganador (Win): Toca target y nunca tocó floor, o tocó target antes que floor
    wins = ever_target & (~ever_floor | (first_target < first_floor))
    # 2. Perdedor (Loss): Toca floor y nunca tocó target, o tocó floor antes que target
    losses = ever_floor & (~ever_target | (first_floor < first_target))
    # 3. Timeout: Ninguno fue tocado dentro del horizonte
    timeouts = ~ever_target & ~ever_floor

    n_wins = int(np.sum(wins))
    n_losses = int(np.sum(losses))
    n_timeouts = int(np.sum(timeouts))

    p_win = round(float(n_wins / n_paths), 3)
    p_loss = round(float(n_losses / n_paths), 3)
    p_timeout = round(float(n_timeouts / n_paths), 3)

    # Mediana del tiempo hasta la venta en trayectorias ganadoras
    if n_wins > 0:
        win_times = first_target[wins] * dt_minutes
        median_time_min = round(float(np.median(win_times)), 1)
    else:
        median_time_min = float(horizon_minutes)

    # Ganancia y pérdida porcentual
    gain_pct = ((target_price - current_price) / current_price) * 100.0
    loss_pct = ((current_price - floor_price) / current_price) * 100.0
    fee_drag_pct = 0.16  # Comisiones ida y vuelta estimadas

    expected_value_pct = round(float((p_win * gain_pct) - (p_loss * loss_pct) - fee_drag_pct), 3)
    mc_score = round(float(p_win * 100.0), 1)

    # Veredicto cualitativo basado en probabilidad prospectiva
    if p_win >= 0.70 and expected_value_pct > 0:
        verdict = "ALTA_CONVICCION_ALCISTA"
    elif p_win >= 0.55 and expected_value_pct >= 0:
        verdict = "PROYECCION_MODERADA"
    elif p_loss >= 0.35 or p_win < 0.45:
        verdict = "VETO_RIESGO_DE_PISO"
    else:
        verdict = "TRANSICION_NEUTRA"

    return {
        "p_win": p_win,
        "p_loss": p_loss,
        "p_timeout": p_timeout,
        "median_time_min": median_time_min,
        "expected_value_pct": expected_value_pct,
        "mc_score": mc_score,
        "verdict": verdict,
        "gain_target_pct": round(gain_pct, 2),
        "loss_floor_pct": round(loss_pct, 2),
        "paths_simulated": n_paths,
        "horizon_min": horizon_minutes
    }
