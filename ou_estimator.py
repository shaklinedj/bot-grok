"""
ou_estimator.py — Estimador Cuantitativo del Proceso de Ornstein-Uhlenbeck
========================================================================
Modela la dinámica de reversión a la media (Mean Reversion) del activo:
    dx_t = θ (μ - x_t) dt + σ dW_t

Calcula:
  - θ (theta): Velocidad de reversión hacia la media
  - μ (mu): Precio medio de equilibrio gravitacional
  - σ (sigma): Volatilidad del ruido estocástico
  - τ (half_life_min): Vida media de reversión en minutos (tiempo para recorrer 50% de la distancia a μ)
  - σ_OU (ou_std): Desviación estándar estacionaria del proceso
  - r2 (r_squared): Fuerza estadística del ajuste de reversión
  - is_mean_reverting: Booleano (True si θ > 0 y half_life_min está en rango saludable)
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Union


def estimate_ornstein_uhlenbeck(
    prices: Union[List[float], np.ndarray, pd.Series],
    dt_minutes: float = 15.0
) -> Dict[str, Any]:
    """
    Estima los parámetros del proceso Ornstein-Uhlenbeck a partir de una serie temporal de precios.
    No lanza excepciones ante datos anómalos; devuelve un dict estructurado seguro con fallbacks.
    """
    if prices is None or len(prices) < 15:
        p_last = float(prices[-1]) if (prices is not None and len(prices) > 0) else 0.0
        return {
            "theta": 0.0,
            "mu": p_last,
            "sigma": 0.0,
            "half_life_min": 999.0,
            "ou_std": 0.0,
            "ou_std_pct": 0.0,
            "r_squared": 0.0,
            "is_mean_reverting": False,
            "status_label": "DATOS_INSUFICIENTES"
        }

    try:
        p = np.asarray(prices, dtype=np.float64)
        if np.any(np.isnan(p)) or np.any(p <= 0):
            return {
                "theta": 0.0,
                "mu": float(p[~np.isnan(p)][-1]) if np.any(~np.isnan(p)) else 0.0,
                "sigma": 0.0,
                "half_life_min": 999.0,
                "ou_std": 0.0,
                "ou_std_pct": 0.0,
                "r_squared": 0.0,
                "is_mean_reverting": False,
                "status_label": "DATOS_INVALIDOS"
            }

        x = p[:-1]
        y = p[1:]
        dx = y - x

        n = len(x)
        x_mean = float(np.mean(x))
        dx_mean = float(np.mean(dx))

        denom = float(np.sum((x - x_mean) ** 2))
        if denom <= 1e-12:
            return {
                "theta": 0.0,
                "mu": float(p[-1]),
                "sigma": 0.0,
                "half_life_min": 999.0,
                "ou_std": 0.0,
                "ou_std_pct": 0.0,
                "r_squared": 0.0,
                "is_mean_reverting": False,
                "status_label": "SIN_VARIANZA"
            }

        beta = float(np.sum((x - x_mean) * (dx - dx_mean)) / denom)
        alpha = float(dx_mean - beta * x_mean)

        # Residuos y R² de la regresión
        dx_pred = alpha + beta * x
        residuals = dx - dx_pred
        ss_res = float(np.sum(residuals ** 2))
        ss_tot = float(np.sum((dx - dx_mean) ** 2))
        r2 = max(0.0, 1.0 - (ss_res / ss_tot)) if ss_tot > 1e-12 else 0.0

        # Si beta >= 0, el resorte no jala hacia la media: el activo está en tendencia o paseo aleatorio
        if beta >= 0.0:
            return {
                "theta": 0.0,
                "mu": float(p[-1]),
                "sigma": float(np.std(residuals)),
                "half_life_min": 999.0,
                "ou_std": 0.0,
                "ou_std_pct": 0.0,
                "r_squared": round(float(r2), 3),
                "is_mean_reverting": False,
                "status_label": "TENDENCIA / CAMINO ALEATORIO"
            }

        # Parámetros del proceso continuo
        # 1 + beta = exp(-theta * dt) => theta = -ln(1 + beta) / dt
        arg = max(0.0001, 1.0 + beta)
        theta = -np.log(arg) / dt_minutes
        mu = -alpha / beta

        # Half-life: tiempo para recorrer el 50% de la distancia a mu
        half_life_min = (np.log(2.0) / theta) if theta > 1e-6 else 999.0

        # Volatilidad estocástica sigma
        sigma_epsilon = float(np.std(residuals))
        sigma = (sigma_epsilon / np.sqrt(dt_minutes)) if dt_minutes > 0 else sigma_epsilon

        # Varianza estacionaria de largo plazo: Var = sigma^2 / (2 * theta)
        var_ou = (sigma ** 2) / (2.0 * theta) if theta > 1e-6 else 0.0
        ou_std = np.sqrt(max(0.0, var_ou))
        ou_std_pct = (ou_std / mu * 100.0) if mu > 0 else 0.0

        # Diagnóstico de calidad de reversión:
        # Saludable para mallas spot: half-life entre 8m y 180m y R² aceptable
        is_healthy_reversion = (theta > 0.0) and (8.0 <= half_life_min <= 180.0)

        if is_healthy_reversion and r2 >= 0.15:
            status = "REVERSIÓN FUERTE"
        elif is_healthy_reversion:
            status = "REVERSIÓN MODERADA"
        elif half_life_min > 180.0:
            status = "REVERSIÓN LENTA"
        else:
            status = "ALTO RUIDO"

        return {
            "theta": round(float(theta), 6),
            "mu": round(float(mu), 6),
            "sigma": round(float(sigma), 6),
            "half_life_min": round(float(half_life_min), 1),
            "ou_std": round(float(ou_std), 6),
            "ou_std_pct": round(float(ou_std_pct), 2),
            "r_squared": round(float(r2), 3),
            "is_mean_reverting": bool(is_healthy_reversion),
            "status_label": status
        }
    except Exception:
        p_last = float(prices[-1]) if (prices is not None and len(prices) > 0) else 0.0
        return {
            "theta": 0.0,
            "mu": p_last,
            "sigma": 0.0,
            "half_life_min": 999.0,
            "ou_std": 0.0,
            "ou_std_pct": 0.0,
            "r_squared": 0.0,
            "is_mean_reverting": False,
            "status_label": "ERROR_CALCULO"
        }
