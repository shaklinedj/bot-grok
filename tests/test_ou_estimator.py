import unittest
import numpy as np
from ou_estimator import estimate_ornstein_uhlenbeck


class TestOrnsteinUhlenbeckEstimator(unittest.TestCase):

    def test_insufficient_data(self):
        res = estimate_ornstein_uhlenbeck([1.0, 2.0, 3.0])
        self.assertEqual(res["status_label"], "DATOS_INSUFICIENTES")
        self.assertFalse(res["is_mean_reverting"])

    def test_synthetic_mean_reversion(self):
        np.random.seed(42)
        prices = [100.0]
        # Generar proceso Ornstein-Uhlenbeck sintético con reversión fuerte
        for _ in range(60):
            dp = 0.20 * (100.0 - prices[-1]) + np.random.normal(0, 0.5)
            prices.append(prices[-1] + dp)
        
        res = estimate_ornstein_uhlenbeck(prices, dt_minutes=15.0)
        self.assertTrue(res["theta"] > 0)
        self.assertTrue(res["half_life_min"] < 120.0)
        self.assertTrue(res["is_mean_reverting"])
        self.assertAlmostEqual(res["mu"], 100.0, delta=2.0)

    def test_pure_trending_data(self):
        # Datos en tendencia explosiva pura sin reversión
        prices = [10.0 + i * 2.0 for i in range(30)]
        res = estimate_ornstein_uhlenbeck(prices, dt_minutes=15.0)
        self.assertFalse(res["is_mean_reverting"])
        self.assertEqual(res["theta"], 0.0)
        self.assertEqual(res["half_life_min"], 999.0)

    def test_resilience_to_none_and_nan(self):
        res = estimate_ornstein_uhlenbeck(None)
        self.assertFalse(res["is_mean_reverting"])
        
        res_nan = estimate_ornstein_uhlenbeck([np.nan] * 20)
        self.assertFalse(res_nan["is_mean_reverting"])


if __name__ == '__main__':
    unittest.main()
