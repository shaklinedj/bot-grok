import os
import json
import glob
import tempfile
import unittest
from unittest.mock import patch
from paper_trading_agent import (
    GridPosition,
    LongPosition,
    PaperBot,
    ReinforcementBrain,
    INITIAL_CAPITAL,
    get_position_volume_24h,
    get_tick_price_range,
)

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
            with open(corrupt_file, "w", encoding="utf-8") as f:
                json.dump({"cash": 12.0, "longs": {"BTC/USDT": {}}}, f)

            bot = PaperBot.__new__(PaperBot)
            bot.cash = INITIAL_CAPITAL
            bot.holdings = {}
            bot.longs = {}
            bot.grids = {}
            bot.total_fees_paid = 0.0
            bot.total_slippage_cost = 0.0
            bot.total_realized_pnl_acc = 0.0
            bot.wins = bot.losses = bot.total_trades = 0

            with patch("paper_trading_agent.PORTFOLIO_STATE_FILE", corrupt_file):
                bot.load_portfolio_state()

            backups = glob.glob(f"{corrupt_file}.corrupt.*.bak")
            self.assertEqual(len(backups), 1)
            self.assertEqual(bot.cash, INITIAL_CAPITAL)
            self.assertEqual(bot.longs, {})

    def test_trade_range_includes_intermediate_wicks(self):
        trades = [{"price": 101.0}, {"price": 95.0}, {"price": 104.0}]
        self.assertEqual(get_tick_price_range(trades, 100.0, 99.0), (95.0, 104.0))

    def test_slippage_uses_saved_volume_features(self):
        position = LongPosition(
            position_id="test",
            symbol="BTC/USDT",
            initial_amount=1.0,
            amount=1.0,
            entry_price=100.0,
            stop_loss=90.0,
            initial_sl=90.0,
            trailing_stop=90.0,
            features_at_entry={"volume_m": 7.5},
        )
        self.assertEqual(get_position_volume_24h(position), 7_500_000.0)
        position.features_at_entry["volume_24h"] = 12_000_000
        self.assertEqual(get_position_volume_24h(position), 12_000_000.0)

if __name__ == "__main__":
    unittest.main()
