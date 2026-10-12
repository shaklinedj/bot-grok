import unittest
from paper_trading_agent import get_grid_matched_cycles, GridPosition

class TestGridMatchedCycles(unittest.TestCase):
    def test_paired_cycles(self):
        grid = GridPosition(
            grid_id="g_test_1",
            symbol="ONDO/USDT",
            grid_lower=0.4900,
            grid_upper=0.5000,
            grid_lines=5,
            step_pct=0.005,
            step_size=0.0025,
            capital_total=60.0,
            capital_per_line=12.0,
            lines=[]
        )
        trades = [
            {
                "id": 1,
                "timestamp": "2026-10-12T16:25:55",
                "symbol": "ONDO/USDT",
                "strategy": "grid_init",
                "side": "setup",
                "price": 0.4905,
                "amount": 48.06,
                "pnl": 0.0,
                "fee": 0.0,
                "extra_info": "Init"
            },
            {
                "id": 2,
                "timestamp": "2026-10-12T17:05:23",
                "symbol": "ONDO/USDT",
                "strategy": "grid_tp",
                "side": "sell",
                "price": 0.4958,
                "amount": 48.06,
                "pnl": 0.1262,
                "fee": 0.024,
                "extra_info": "Escalón completado"
            },
            {
                "id": 3,
                "timestamp": "2026-10-12T17:15:09",
                "symbol": "ONDO/USDT",
                "strategy": "grid_limit_buy",
                "side": "buy",
                "price": 0.4929,
                "amount": 23.85,
                "pnl": 0.0,
                "fee": 0.023,
                "extra_info": "Escalón ejecutado | Venta colocada en $0.495100"
            },
            {
                "id": 4,
                "timestamp": "2026-10-12T17:28:05",
                "symbol": "ONDO/USDT",
                "strategy": "grid_tp",
                "side": "sell",
                "price": 0.4951,
                "amount": 23.85,
                "pnl": 0.0398,
                "fee": 0.024,
                "extra_info": "Escalón #2 completado"
            },
            {
                "id": 5,
                "timestamp": "2026-10-12T18:09:44",
                "symbol": "ONDO/USDT",
                "strategy": "grid_limit_buy",
                "side": "buy",
                "price": 0.4925,
                "amount": 23.85,
                "pnl": 0.0,
                "fee": 0.023,
                "extra_info": "Escalón ejecutado | Venta colocada en $0.494500"
            }
        ]
        cycles = get_grid_matched_cycles(grid, trades, current_price=0.4930)
        self.assertEqual(len(cycles), 3)

        # Ciclo cosechado #1: Compra 0.4929 -> Venta 0.4951
        c_closed = [c for c in cycles if c["is_closed"] and c["buy_price"] == 0.4929][0]
        self.assertEqual(c_closed["status"], "COSECHADO")
        self.assertAlmostEqual(c_closed["sell_price"], 0.4951)
        self.assertAlmostEqual(c_closed["pnl"], 0.0398)

        # Ciclo en espera: Compra 0.4925 -> Esperando venta a 0.4945
        c_open = [c for c in cycles if not c["is_closed"]][0]
        self.assertEqual(c_open["status"], "ESPERANDO_VENTA")
        self.assertAlmostEqual(c_open["buy_price"], 0.4925)
        self.assertAlmostEqual(c_open["sell_price"], 0.4945)
        self.assertIsNone(c_open["sell_time"])

if __name__ == "__main__":
    unittest.main()
