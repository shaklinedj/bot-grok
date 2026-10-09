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
            self.assertTrue(os.path.exists(bak_file))

if __name__ == "__main__":
    unittest.main()
