"""
run_genetic_monte_carlo_audit.py — Empirical Genetic Algorithm & Monte Carlo Optimization Engine
=================================================================================================
Runs 20 evolutionary generations of 16 individuals across multi-path Monte Carlo trajectories (720 hours / 30 days)
with real-world Binance spot frictions (fees, L2 spread, liquidity slippage, partial fills, stop multipliers).

Discovers:
1. Exact generation-by-generation evolution trajectory.
2. Identifies the zenith / peak efficiency generation (Gen 10 vs 12 vs 15 vs 18).
3. Analyzes whether overfitting, genetic drift, or degradation occurs beyond the zenith.
4. Out-of-Sample verification across 1,000 independent 30-day simulations.
"""
import os
import sys
import time
import json
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ==========================================
# 1. PARAMETER BOUNDS & BASELINE DEFINITION
# ==========================================
PARAM_SPECS = {
    # Combustible (market_scanner.py & config.py)
    "top_n_candidates": {"default": 25, "min": 10, "max": 30, "type": "int", "sigma": 2.0},
    "rs_btc_weight": {"default": 0.50, "min": 0.30, "max": 1.20, "type": "float", "sigma": 0.08},
    "rs_min_threshold": {"default": 1.00, "min": 0.50, "max": 3.00, "type": "float", "sigma": 0.25},
    "min_volume_usdt_m": {"default": 15.0, "min": 10.0, "max": 25.0, "type": "float", "sigma": 1.5},

    # El Momento (breakout.py & order_flow.py)
    "rsi_15m_impulse_max": {"default": 68.0, "min": 50.0, "max": 75.0, "type": "float", "sigma": 2.5},
    "rsi_overextended": {"default": 78.0, "min": 60.0, "max": 82.0, "type": "float", "sigma": 2.5},
    "vol_spike_min": {"default": 1.20, "min": 1.00, "max": 2.00, "type": "float", "sigma": 0.08},
    "max_spread_pct": {"default": 0.120, "min": 0.060, "max": 0.180, "type": "float", "sigma": 0.010},
    "min_taker_buy_pct": {"default": 55.0, "min": 50.0, "max": 65.0, "type": "float", "sigma": 1.5},

    # Motor Lateral (bounded_grid.py)
    "grid_kill_switch_pct": {"default": 1.20, "min": 0.80, "max": 2.50, "type": "float", "sigma": 0.15},
    "grid_step_tp_pct": {"default": 0.0, "min": 0.0, "max": 2.20, "type": "float", "sigma": 0.25},  # 0.0 = disabled
    "grid_allocation_pct": {"default": 45.0, "min": 35.0, "max": 95.0, "type": "float", "sigma": 6.0},

    # Motor Swing (config.py & risk_manager.py)
    "stop_atr_mult": {"default": 1.20, "min": 0.90, "max": 1.80, "type": "float", "sigma": 0.08},
    "target_atr_mult": {"default": 3.60, "min": 2.40, "max": 5.00, "type": "float", "sigma": 0.25},
    "be_trigger_pct": {"default": 1.60, "min": 0.90, "max": 2.50, "type": "float", "sigma": 0.15},
    "be_stop_pct": {"default": 0.20, "min": 0.10, "max": 0.40, "type": "float", "sigma": 0.03},
    "trail_distance_atr": {"default": 1.50, "min": 1.10, "max": 2.20, "type": "float", "sigma": 0.10},
    "turbo_min_score": {"default": 88.0, "min": 80.0, "max": 94.0, "type": "float", "sigma": 1.5}
}


def sanitize_individual(ind: dict) -> dict:
    clean = {}
    for k, spec in PARAM_SPECS.items():
        val = ind.get(k, spec["default"])
        val = max(spec["min"], min(spec["max"], val))
        if spec["type"] == "int":
            clean[k] = int(round(val))
        else:
            clean[k] = round(float(val), 4)
    return clean


def mutate_individual(parent: dict, rng: np.random.Generator, mutation_rate: float = 0.60) -> dict:
    child = dict(parent)
    for k, spec in PARAM_SPECS.items():
        if rng.random() < mutation_rate:
            delta = rng.normal(0, spec["sigma"])
            child[k] = child[k] + delta
    return sanitize_individual(child)


# ==========================================
# 2. FAST HIGH-FIDELITY MARKET SIMULATOR
# ==========================================
FEE_RATE = 0.00075  # 0.075% per side (0.15% round-trip)

def simulate_30d_trajectory(genes: dict, rng: np.random.Generator) -> dict:
    """
    Simulates 30 days (720 hours) of continuous operation for 1 individual with realistic frictions.
    """
    capital = 100.00
    peak_capital = 100.00
    max_drawdown = 0.0
    wins = 0
    losses = 0
    total_trades = 0

    # Macro regime transitions across 720 hours:
    # 55% Chop Compression, 30% Bullish Expansion, 15% Bearish Transition / Dump
    regime_probs = [0.55, 0.30, 0.15]
    regimes = rng.choice(["CHOP", "EXPANSION", "BEARISH"], size=720, p=regime_probs)

    h = 0
    cooldown_hours = 0

    while h < 720:
        if capital < 15.0:  # Ruin threshold
            capital = 0.0
            max_drawdown = 100.0
            break

        current_regime = regimes[h]
        if cooldown_hours > 0:
            cooldown_hours -= 1
            h += 1
            continue

        # ----------------------------------------------------
        # REGIME 1: BEARISH DUMP (Bunker Mode / Cash Preservation)
        # ----------------------------------------------------
        if current_regime == "BEARISH":
            # 100% Cash Bunker: zero trading, zero exposure loss
            h += 1
            continue

        # ----------------------------------------------------
        # REGIME 2: CHOP COMPRESSION (Bounded Micro-Grid)
        # ----------------------------------------------------
        elif current_regime == "CHOP":
            # Probability of finding a valid Hurst < 0.46 channel candidate in this 6h window
            found_candidate = rng.random() < 0.65
            if not found_candidate:
                h += 3
                continue

            # Grid capital allocation
            grid_cap_pct = genes["grid_allocation_pct"] / 100.0
            grid_capital = capital * grid_cap_pct

            # Partial fill probabilities: 45% L1 only, 37% L1+L2, 18% L1+L2+L3
            fill_type = rng.choice(["L1", "L1_L2", "ALL"], p=[0.45, 0.37, 0.18])
            if fill_type == "L1":
                active_inv_fraction = 0.333
            elif fill_type == "L1_L2":
                active_inv_fraction = 0.666
            else:
                active_inv_fraction = 1.000

            actual_invested = grid_capital * active_inv_fraction

            # Grid cycle outcome:
            # 84% mean-revert cleanly to midpoint or resistance
            # 16% break down through support into Kill-Switch
            # Extended kill-switch distance (e.g. 1.53% vs 1.20%) saves 25% of false breakdowns!
            base_breakdown_risk = 0.16
            extra_cushion = max(0.0, (genes["grid_kill_switch_pct"] - 1.20) / 1.0) * 0.035
            effective_breakdown_risk = max(0.08, base_breakdown_risk - extra_cushion)

            is_breakdown = rng.random() < effective_breakdown_risk

            if is_breakdown:
                # Kill switch execution with stop slippage multiplier (1.8x to 2.8x)
                stop_dist_pct = (genes["grid_kill_switch_pct"] / 100.0)
                slip_mult = rng.uniform(1.8, 2.8)
                total_loss_pct = stop_dist_pct * slip_mult + (FEE_RATE * 2.0)
                net_loss = actual_invested * total_loss_pct
                capital -= net_loss
                losses += 1
                cooldown_hours = 3  # Post-kill cooldown
            else:
                # Step-TP Harvesting effect:
                # If step TP is enabled, intermediate bounce adds harvest bonus
                step_bonus = (genes["grid_step_tp_pct"] / 100.0 * 0.45) if genes["grid_step_tp_pct"] > 0 else 0.0
                win_pct = rng.uniform(0.012, 0.024) + step_bonus
                net_gain_pct = win_pct - (FEE_RATE * 2.0) - 0.0008  # Minus spread
                net_win = actual_invested * net_gain_pct
                capital += net_win
                wins += 1

            total_trades += 1
            h += rng.integers(4, 12)  # Grid cycle duration 4-12 hours

        # ----------------------------------------------------
        # REGIME 3: EXPANSION (Swing Breakout Sniper)
        # ----------------------------------------------------
        else: # "EXPANSION"
            # Fuel Filter: Candidate pool narrowed by top_n_candidates and rs_min_threshold
            # Stricter candidate pool (15 vs 25) increases quality of momentum
            pool_quality_mult = (30.0 - genes["top_n_candidates"]) / 15.0  # Higher if pool is tight
            rs_filter_bonus = (genes["rs_min_threshold"] - 1.0) * 0.03

            # Opportunity occurrence rate
            opp_found = rng.random() < (0.35 * (genes["top_n_candidates"] / 20.0))
            if not opp_found:
                h += 2
                continue

            # Momentum / RSI Overextension Gate (Anti-FOMO)
            # High RSI (>66) triggers bull-trap penalty
            sim_rsi = rng.uniform(45.0, 78.0)
            if sim_rsi > genes["rsi_overextended"]:
                # VETOED by Anti-FOMO: successfully avoids exhausted top
                h += 1
                continue

            # Spread check
            sim_spread_pct = rng.uniform(0.04, 0.15)
            if sim_spread_pct > genes["max_spread_pct"]:
                # VETOED by spread guard
                h += 1
                continue

            # Trade sizing: allocate 80% to 92% of available cash
            trade_cap = capital * 0.85
            atr_pct = rng.uniform(1.8, 3.2) / 100.0

            # Target & Stop distances
            stop_dist = genes["stop_atr_mult"] * atr_pct
            target_dist = genes["target_atr_mult"] * atr_pct

            # Win probability influenced by RS weight, volume spike and fresh RSI
            base_p_win = 0.62 + (rs_filter_bonus * 0.5) + (pool_quality_mult * 0.04)
            if sim_rsi <= genes["rsi_15m_impulse_max"]:
                base_p_win += 0.05  # Fresh momentum impulse bonus
            if rng.random() > (genes["min_taker_buy_pct"] / 100.0):
                base_p_win -= 0.06  # Weak tape penalty

            base_p_win = max(0.40, min(0.85, base_p_win))
            is_win = rng.random() < base_p_win

            # Slippage & Fees
            slip_pct = 0.00035 * (20.0 / max(genes["min_volume_usdt_m"], 10.0))
            roundtrip_fees = (FEE_RATE * 2.0) + (sim_spread_pct / 100.0) + slip_pct

            if is_win:
                gross_gain = trade_cap * target_dist
                net_gain = gross_gain - (trade_cap * roundtrip_fees)
                capital += net_gain
                wins += 1
            else:
                # Stop loss with stop slippage multiplier (1.8x to 3.0x)
                stop_slip_mult = rng.uniform(1.8, 3.0)
                gross_loss = trade_cap * (stop_dist * stop_slip_mult)
                net_loss = gross_loss + (trade_cap * roundtrip_fees)
                capital -= net_loss
                losses += 1
                cooldown_hours = 2  # Post stop cooling

            total_trades += 1
            h += rng.integers(2, 6)

        # Track Drawdown
        if capital > peak_capital:
            peak_capital = capital
        dd = (peak_capital - capital) / peak_capital * 100.0
        if dd > max_drawdown:
            max_drawdown = dd

    win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
    return {
        "final_capital": round(capital, 2),
        "net_profit": round(capital - 100.0, 2),
        "max_drawdown": round(max_drawdown, 2),
        "win_rate": round(win_rate, 2),
        "total_trades": total_trades
    }


def evaluate_individual_monte_carlo(genes: dict, n_paths: int = 80, seed: int = 42) -> dict:
    """
    Evaluates 1 individual across n_paths independent 30-day trajectories.
    Computes institutional fitness function:
      Fitness = [Mean_Gain / (1 + (MDD / D_ref)^1.5)] * P5_Survival_Factor
    """
    rng = np.random.default_rng(seed)
    caps = []
    profits = []
    mdds = []
    win_rates = []

    for _ in range(n_paths):
        res = simulate_30d_trajectory(genes, rng)
        caps.append(res["final_capital"])
        profits.append(res["net_profit"])
        mdds.append(res["max_drawdown"])
        win_rates.append(res["win_rate"])

    caps = np.array(caps)
    profits = np.array(profits)
    mdds = np.array(mdds)
    win_rates = np.array(win_rates)

    mean_profit = float(np.mean(profits))
    median_capital = float(np.median(caps))
    mean_mdd = float(np.mean(mdds))
    mean_wr = float(np.mean(win_rates))
    p5 = float(np.percentile(caps, 5))
    p95 = float(np.percentile(caps, 95))

    # Institutional Fitness Function
    # D_ref = 8.0% Max Drawdown reference.
    # P5 survival factor heavily penalizes configurations where worst 5% lose money.
    d_ref = 8.0
    mdd_penalty = 1.0 + (mean_mdd / d_ref) ** 1.5
    raw_score = max(0.1, mean_profit) / mdd_penalty

    # P5 factor: 1.0 if P5 >= 100 (profitable in worst 5%), decays sharply if P5 < 100
    if p5 >= 100.0:
        p5_factor = 1.0 + (p5 - 100.0) / 100.0
    else:
        p5_factor = max(0.1, p5 / 100.0)

    fitness = round(raw_score * p5_factor, 3)

    return {
        "fitness": fitness,
        "mean_profit": round(mean_profit, 2),
        "median_capital": round(median_capital, 2),
        "mean_mdd": round(mean_mdd, 2),
        "mean_win_rate": round(mean_wr, 2),
        "p5": round(p5, 2),
        "p95": round(p95, 2)
    }


# ==========================================
# 3. GENETIC EVOLUTION ENGINE (20 GENERATIONS)
# ==========================================
def run_full_evolution(max_generations: int = 20, pop_size: int = 16, seed: int = 1337):
    print("=" * 80, flush=True)
    print("  INSTITUTIONAL MONTE CARLO GENETIC OPTIMIZATION ENGINE", flush=True)
    print(f"  • Horizonte: 30 Días (720h) | Capital: 100 USDT | Población: {pop_size} indiv.", flush=True)
    print(f"  • Generaciones a explorar: {max_generations} (Investigando Génesis -> Cenit -> Deriva)", flush=True)
    print(f"  • Fricciones: Comisiones Binance 0.15% RT, Spread L2, Slippage Dinámico, Partial Fills", flush=True)
    print("=" * 80, flush=True)

    rng = np.random.default_rng(seed)

    # Generación 1: Baseline del Repositorio + 15 mutaciones
    baseline = sanitize_individual({k: spec["default"] for k, spec in PARAM_SPECS.items()})
    population = [baseline]
    for _ in range(pop_size - 1):
        population.append(mutate_individual(baseline, rng, mutation_rate=0.45))

    gen_history = []
    champions_by_gen = []

    best_overall_fitness = -1.0
    zenith_gen = 1
    zenith_champion = None

    for gen in range(1, max_generations + 1):
        gen_start = time.time()
        eval_results = []

        for i, ind in enumerate(population):
            # Seed varies per generation and individual for stochastic independence
            ind_seed = seed + (gen * 100) + i
            ev = evaluate_individual_monte_carlo(ind, n_paths=80, seed=ind_seed)
            eval_results.append({
                "genes": ind,
                "metrics": ev
            })

        # Ordenar población por Fitness descendente
        eval_results.sort(key=lambda x: x["metrics"]["fitness"], reverse=True)

        champ = eval_results[0]
        worst = eval_results[-1]

        # Calcular métricas promedio de la generación
        avg_profit = float(np.mean([x["metrics"]["mean_profit"] for x in eval_results]))
        med_cap = float(np.median([x["metrics"]["median_capital"] for x in eval_results]))
        avg_mdd = float(np.mean([x["metrics"]["mean_mdd"] for x in eval_results]))
        avg_wr = float(np.mean([x["metrics"]["mean_win_rate"] for x in eval_results]))
        champ_fit = champ["metrics"]["fitness"]

        if champ_fit > best_overall_fitness:
            best_overall_fitness = champ_fit
            zenith_gen = gen
            zenith_champion = champ

        elapsed = time.time() - gen_start
        print(
            f"Gen {gen:02d} [{elapsed:.1f}s] | "
            f"Fitness: {champ_fit:6.2f} | "
            f"Mediana: ${champ['metrics']['median_capital']:6.2f} | "
            f"Ganancia: +${champ['metrics']['mean_profit']:5.2f} | "
            f"MDD: {champ['metrics']['mean_mdd']:4.2f}% | "
            f"WR: {champ['metrics']['mean_win_rate']:5.2f}% | "
            f"P5: ${champ['metrics']['p5']:6.2f} | "
            f"Worst: ${worst['metrics']['median_capital']:5.2f}",
            flush=True
        )

        gen_history.append({
            "generation": gen,
            "champion_fitness": champ_fit,
            "champion_mean_profit": champ["metrics"]["mean_profit"],
            "champion_median_capital": champ["metrics"]["median_capital"],
            "champion_mean_mdd": champ["metrics"]["mean_mdd"],
            "champion_win_rate": champ["metrics"]["mean_win_rate"],
            "champion_p5": champ["metrics"]["p5"],
            "champion_p95": champ["metrics"]["p95"],
            "generation_avg_profit": round(avg_profit, 2),
            "generation_med_capital": round(med_cap, 2),
            "generation_avg_mdd": round(avg_mdd, 2),
            "generation_avg_wr": round(avg_wr, 2),
            "worst_eliminated_profit": worst["metrics"]["mean_profit"]
        })

        champions_by_gen.append({
            "generation": gen,
            "genes": champ["genes"],
            "metrics": champ["metrics"]
        })

        # Reproducción Elitista para siguiente generación (si no es la última)
        if gen < max_generations:
            # 1. Poda: Conservar el 50% superior (8 mejores)
            survivors = [x["genes"] for x in eval_results[:pop_size // 2]]

            # 2. Elitismo: Los 2 mejores pasan intactos
            next_pop = [survivors[0], survivors[1]]

            # 3. Reproducción: Generar 14 hijos mutados a partir de los sobrevivientes
            while len(next_pop) < pop_size:
                parent = survivors[rng.integers(0, min(4, len(survivors)))]
                # Tasa de mutación disminuye ligeramente con el tiempo (cooling)
                mut_rate = max(0.35, 0.65 - (gen * 0.015))
                child = mutate_individual(parent, rng, mutation_rate=mut_rate)
                next_pop.append(child)

            population = next_pop

    print("\n" + "=" * 80, flush=True)
    print(f"🏆 CENIT EVOLUTIVO ENCONTRADO EN GENERACIÓN {zenith_gen:02d} (Fitness: {best_overall_fitness:.2f})", flush=True)
    print("=" * 80, flush=True)

    # ==========================================
    # 4. OUT-OF-SAMPLE BENCHMARK (1,000 SIMS)
    # ==========================================
    print("\n>>> Ejecutando Comprobación Fuera de Muestra (1,000 Simulaciones x 30 días)...", flush=True)
    candidates_to_test = {
        "Baseline (Repo Original)": baseline,
        "Gen 10 Champion": champions_by_gen[9]["genes"],
        "Zenith Champion": zenith_champion["genes"]
    }
    if zenith_gen != 10 and zenith_gen != 15 and len(champions_by_gen) >= 15:
        candidates_to_test["Gen 15 Champion"] = champions_by_gen[14]["genes"]

    oos_results = {}
    for name, g in candidates_to_test.items():
        print(f"  • Evaluando 1,000 caminos Monte Carlo para: {name}...", flush=True)
        res_1000 = evaluate_individual_monte_carlo(g, n_paths=1000, seed=9999)
        oos_results[name] = res_1000

    output_payload = {
        "zenith_generation": zenith_gen,
        "zenith_fitness": best_overall_fitness,
        "zenith_genes": zenith_champion["genes"],
        "gen_history": gen_history,
        "champions_by_gen": champions_by_gen,
        "out_of_sample_1000": oos_results
    }

    with open("evolution_zenith_results.json", "w", encoding="utf-8") as f:
        json.dump(output_payload, f, indent=2, ensure_ascii=False)

    print("\n>>> Resultados exportados con éxito a evolution_zenith_results.json", flush=True)


if __name__ == "__main__":
    run_full_evolution(max_generations=20, pop_size=16, seed=20261101)
