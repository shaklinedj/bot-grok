"""
Dynamic Position Sizing & Fractional Kelly Allocation Engine (Institutional Grade 10).
Applies Fractional Kelly Criterion combined with Inverse-ATR Volatility Scaling.
Prevents risk of ruin while maximizing compounding growth during high-conviction regimes.
"""
from typing import Dict, Any


def calculate_fractional_kelly_ratio(
    win_rate: float,
    profit_loss_ratio: float,
    kelly_fraction: float = 0.25,
    min_ratio: float = 0.15,
    max_ratio: float = 0.90
) -> float:
    """
    Calculates the Fractional Kelly allocation fraction:
      f* = (p * b - q) / b
      f_adj = kelly_fraction * f*
    Where:
      p = win_rate (e.g. 0.70)
      q = 1 - p (e.g. 0.30)
      b = profit_loss_ratio (Avg Win / Avg Loss, e.g. 2.2)
      kelly_fraction = conservatism multiplier (0.25 to 0.33 to eliminate risk of ruin)
    """
    if win_rate <= 0.0 or profit_loss_ratio <= 0.0:
        return min_ratio

    p = win_rate
    q = 1.0 - p
    b = profit_loss_ratio

    full_kelly = (p * b - q) / b
    if full_kelly <= 0.0:
        # Negative expected edge: reduce to minimum survival size
        return min_ratio

    fractional = full_kelly * kelly_fraction
    return max(min_ratio, min(max_ratio, fractional))


def scale_capital_by_volatility(
    base_capital: float,
    current_atr_pct: float,
    baseline_atr_pct: float = 2.0,
    min_scale: float = 0.40,
    max_scale: float = 1.35
) -> float:
    """
    Scales position sizing inversely with respect to market volatility:
      scale = baseline_atr / current_atr
    When market volatility explodes, position size automatically contracts
    to maintain constant portfolio risk-at-risk (VaR parity).
    """
    if current_atr_pct <= 0.0 or base_capital <= 0.0:
        return base_capital

    raw_scale = baseline_atr_pct / current_atr_pct
    bounded_scale = max(min_scale, min(max_scale, raw_scale))
    return round(base_capital * bounded_scale, 2)


def get_institutional_trade_size(
    equity: float,
    cash: float,
    win_rate: float = 0.70,
    profit_loss_ratio: float = 2.0,
    current_atr_pct: float = 2.0,
    baseline_atr_pct: float = 2.0,
    kelly_fraction: float = 0.25,
    max_portfolio_risk_pct: float = 0.95
) -> Dict[str, Any]:
    """
    Full institutional sizing computation combining Kelly + Volatility Scaling.
    Guarantees that sizing never exceeds available cash or maximum allowable portfolio risk.
    """
    kelly_frac = calculate_fractional_kelly_ratio(
        win_rate=win_rate,
        profit_loss_ratio=profit_loss_ratio,
        kelly_fraction=kelly_fraction
    )

    unscaled_cap = equity * kelly_frac
    scaled_cap = scale_capital_by_volatility(
        base_capital=unscaled_cap,
        current_atr_pct=current_atr_pct,
        baseline_atr_pct=baseline_atr_pct
    )

    # Hard risk constraints: never exceed available cash or total equity boundary
    max_cap = min(cash * 0.98, equity * max_portfolio_risk_pct)
    final_cap = max(15.0, min(max_cap, scaled_cap)) if cash >= 15.0 else 0.0

    return {
        "final_capital": round(final_cap, 2),
        "kelly_fraction_applied": round(kelly_frac, 4),
        "volatility_scale": round(baseline_atr_pct / max(current_atr_pct, 0.001), 3),
        "raw_kelly_capital": round(unscaled_cap, 2),
        "is_scaled": abs(scaled_cap - unscaled_cap) > 0.5
    }
