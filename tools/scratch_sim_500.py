import numpy as np
import json

def run_simulations():
    np.random.seed(42)
    initial_capital = 500.0
    days_horizons = [30, 90, 180, 365]
    n_sims = 10000

    # ----------------------------------------------------
    # ESTRATEGIA 1: BUDA.COM MARKET MAKER ($500 USD / ~$500,000 CLP)
    # ----------------------------------------------------
    # Empírico en 24h: 100 fills, ~$1,120 CLP sobre $100k CLP = +1.12% diario.
    # Con $500 USD (~$500k CLP), la profundidad de mercado de Buda es limitada (adverse selection & depth penalty).
    # Modelamos una media diaria realista conservadora de 0.50% neto (rango 0.20% a 0.90% diario).
    buda_daily_returns = np.random.normal(loc=0.0050, scale=0.0020, size=(n_sims, 365))
    buda_daily_returns = np.clip(buda_daily_returns, 0.0005, 0.0120) # Mínimo 0.05%, máximo 1.2% diario

    buda_curves = initial_capital * np.cumprod(1.0 + buda_daily_returns, axis=1)

    buda_results = {}
    for d in days_horizons:
        vals = buda_curves[:, d - 1]
        buda_results[d] = {
            "p10": float(np.percentile(vals, 10)),
            "p50_median": float(np.percentile(vals, 50)),
            "p90": float(np.percentile(vals, 90)),
            "mean": float(np.mean(vals)),
            "profit_p50": float(np.percentile(vals, 50) - initial_capital),
            "roi_p50_pct": float((np.percentile(vals, 50) / initial_capital - 1.0) * 100.0)
        }

    # ----------------------------------------------------
    # ESTRATEGIA 2: BINANCE CASH & CARRY ROTATIVO ($500 USDT)
    # ----------------------------------------------------
    # 3 ciclos de financiamiento por día = 1,095 ciclos al año.
    # Tasa promedio en top 5 altcoins rotativas: 0.08% por 8h (media ponderada descontando comisiones de rotación).
    # Modelamos tasas por ciclo entre 0.03% y 0.18%.
    total_cycles = 365 * 3
    carry_cycle_returns = np.random.normal(loc=0.00085, scale=0.00030, size=(n_sims, total_cycles))
    carry_cycle_returns = np.clip(carry_cycle_returns, 0.0002, 0.0025)

    carry_curves = initial_capital * np.cumprod(1.0 + carry_cycle_returns, axis=1)

    carry_results = {}
    for d in days_horizons:
        c_idx = (d * 3) - 1
        vals = carry_curves[:, c_idx]
        carry_results[d] = {
            "p10": float(np.percentile(vals, 10)),
            "p50_median": float(np.percentile(vals, 50)),
            "p90": float(np.percentile(vals, 90)),
            "mean": float(np.mean(vals)),
            "profit_p50": float(np.percentile(vals, 50) - initial_capital),
            "roi_p50_pct": float((np.percentile(vals, 50) / initial_capital - 1.0) * 100.0)
        }

    # ----------------------------------------------------
    # ESTRATEGIA 3: HÍBRIDO 50/50 ($250 Buda MM + $250 Carry Binance)
    # ----------------------------------------------------
    hybrid_results = {}
    for d in days_horizons:
        b_vals = 250.0 * np.cumprod(1.0 + buda_daily_returns[:, :d], axis=1)[:, -1]
        c_vals = 250.0 * np.cumprod(1.0 + carry_cycle_returns[:, :(d*3)], axis=1)[:, -1]
        tot = b_vals + c_vals
        hybrid_results[d] = {
            "p10": float(np.percentile(tot, 10)),
            "p50_median": float(np.percentile(tot, 50)),
            "p90": float(np.percentile(tot, 90)),
            "mean": float(np.mean(tot)),
            "profit_p50": float(np.percentile(tot, 50) - initial_capital),
            "roi_p50_pct": float((np.percentile(tot, 50) / initial_capital - 1.0) * 100.0)
        }

    out = {
        "initial_capital": initial_capital,
        "buda": buda_results,
        "carry": carry_results,
        "hybrid": hybrid_results
    }
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    run_simulations()
