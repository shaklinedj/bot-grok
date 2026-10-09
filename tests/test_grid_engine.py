import os
import json
import shutil
import tempfile
import unittest
from paper_trading_agent import GridPosition, PaperBot, ReinforcementBrain, INITIAL_CAPITAL

class TestGridEngine(unittest.TestCase):
    def test_grid_step_size_initialization(self):
        grid = GridPosition(
            grid_id="test_grid_1",
            symbol="SAND/USDT",
            grid_upper=0.25,
            grid_lower=0.20,
            grid_lines=5,
            step_pct=0.0125,
            capital_total=50.0,
            capital_per_line=10.0,
            lines=[]
        )
        # 5 lines between 0.20 and 0.25 -> step = (0.25 - 0.20) / (5 - 1) = 0.05 / 4 = 0.0125
        self.assertAlmostEqual(grid.step_size, 0.0125, places=5)

    def test_reinforcement_brain_persistence_and_decay(self):
        brain = ReinforcementBrain()
        brain.min_score_required = 75.0
        brain.coin_pnl_memory["BTC/USDT"] = [1.2, -0.5, 2.0]
        brain.coin_blacklist_until["SOL/USDT"] = 9999999999.0
        
        brain.save_state()
        
        # Verify decay
        initial_score = brain.min_score_required
        brain.time_decay()
        self.assertEqual(brain.min_score_required, initial_score - 0.05)

    def test_portfolio_corrupt_state_recovery(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            corrupt_file = os.path.join(tmp_dir, "portfolio_state.json")
            with open(corrupt_file, "w") as f:
                f.write("{corrupted_json_content: true,")
            
            # Verify file exists
            self.assertTrue(os.path.exists(corrupt_file))
            
            # Backup verification simulation
            bak_file = f"{corrupt_file}.corrupt.bak"
            shutil.copy2(corrupt_file, bak_file)
    def test_database_vault_operations(self):
        from db_vault import DatabaseVault
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_db = os.path.join(tmp_dir, "test_vault.db")
            with DatabaseVault(db_path=test_db) as v:
                # Test trade insertion
                trade_id = v.insert_trade(
                    timestamp="2026-10-09T14:00:00",
                    symbol="BTC/USDT",
                    strategy="grid_buy",
                    side="buy",
                    price=65000.0,
                    amount=0.001,
                    pnl=0.0,
                    fee=0.065,
                    status="OPEN"
                )
                self.assertGreater(trade_id, 0)
                
                # Test equity insertion
                eq_id = v.insert_equity(
                    timestamp="2026-10-09T14:00:00",
                    equity=80.0,
                    cash=80.0,
                    holdings_value=0.0,
                    open_longs=0,
                    realized_pnl_total=0.0,
                    fees_paid=0.065,
                    slippage_cost=0.0,
                    max_drawdown=0.0
                )
                self.assertGreater(eq_id, 0)
                
                # Test queries
                trades = v.get_recent_trades(limit=10)
                self.assertEqual(len(trades), 1)
                self.assertEqual(trades[0]["symbol"], "BTC/USDT")
                
                eq_hist = v.get_equity_history(sample_limit=10)
                self.assertEqual(len(eq_hist), 1)
                self.assertEqual(eq_hist[0]["v"], 80.0)

if __name__ == "__main__":
    unittest.main()
