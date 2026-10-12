import unittest
from monte_carlo_simulator import simulate_monte_carlo_forward

class TestMonteCarloSimulator(unittest.TestCase):
    def test_strong_bullish_pull_simulation(self):
        # Cuando mu está significativamente por encima de current_price (+3%), la reversión a la media
        # jala hacia arriba, por lo que p_win debe ser alta (> 60%)
        res = simulate_monte_carlo_forward(
            current_price=10.0,
            target_price=10.10,   # +1.0%
            floor_price=9.70,     # -3.0%
            theta=0.05,
            mu=10.30,             # Gravedad hacia arriba
            sigma=0.08,
            atr_pct=2.0,
            n_paths=1000,
            horizon_minutes=90,
            seed=42
        )
        self.assertIn("p_win", res)
        self.assertIn("p_loss", res)
        self.assertGreater(res["p_win"], 0.60)
        self.assertGreater(res["expected_value_pct"], 0)
        self.assertEqual(res["paths_simulated"], 1000)

    def test_bearish_downward_pull_simulation(self):
        # Cuando mu está por debajo del piso (9.50 vs 10.0), el activo es jalado hacia abajo,
        # lo que debe generar un veredicto de veto por riesgo de piso
        res = simulate_monte_carlo_forward(
            current_price=10.0,
            target_price=10.20,
            floor_price=9.70,
            theta=0.08,
            mu=9.40,              # Gravedad hacia abajo
            sigma=0.15,
            atr_pct=3.0,
            n_paths=1000,
            horizon_minutes=90,
            seed=42
        )
        self.assertGreater(res["p_loss"], 0.35)
        self.assertEqual(res["verdict"], "VETO_RIESGO_DE_PISO")

    def test_invalid_data_handles_gracefully(self):
        res = simulate_monte_carlo_forward(
            current_price=0.0,
            target_price=0.0,
            floor_price=0.0
        )
        self.assertEqual(res["verdict"], "DATOS_INVALIDOS")
        self.assertEqual(res["paths_simulated"], 0)

if __name__ == "__main__":
    unittest.main()
