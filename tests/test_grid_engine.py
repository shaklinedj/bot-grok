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
    active_grid_orders,
    compress_grid_spacing,
    evaluate_anomaly_trailing_down,
    apply_trailing_down_shift,
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

    def test_compressed_grid_spacing_updates_arithmetic_step(self):
        grid = GridPosition(
            grid_id="test_grid_compress",
            symbol="BTC/USDT",
            grid_upper=101.0,
            grid_lower=99.0,
            grid_lines=3,
            step_pct=0.01,
            capital_total=30.0,
            capital_per_line=10.0,
            lines=[],
        )
        old_step = compress_grid_spacing(grid, 100.0)
        self.assertEqual(old_step, 0.01)
        self.assertAlmostEqual(grid.step_pct, 0.0088)
        self.assertAlmostEqual(grid.step_size, 0.88)

    def test_new_sell_order_is_not_in_same_tick_sell_snapshot(self):
        lines = [{"price": 100.0, "side": "buy", "amount": 1.0, "active": True}]
        sells_to_process = active_grid_orders(lines, "sell")
        lines.append({"price": 101.0, "side": "sell", "amount": 1.0, "active": True})
        self.assertEqual(sells_to_process, [])

    def test_evaluate_anomaly_trailing_down_approval_and_rejection(self):
        grid = GridPosition(
            grid_id="test_reval",
            symbol="ONDO/USDT",
            grid_upper=0.52,
            grid_lower=0.48,
            grid_lines=5,
            step_pct=0.01,
            capital_total=40.0,
            capital_per_line=10.0,
            lines=[],
        )
        opps_high = [{"symbol": "ONDO/USDT", "score": 70.0}]
        opps_low = [{"symbol": "ONDO/USDT", "score": 55.0}]

        # 1. Approval: Score >= 65 and safe macro
        approved, reason, score = evaluate_anomaly_trailing_down(
            grid, "ONDO/USDT", 0.478, -0.4, opps_high, "BULLISH_EXPANSION"
        )
        self.assertTrue(approved)
        self.assertEqual(score, 70.0)

        # 2. Rejection: Score < 65
        approved_low, reason_low, score_low = evaluate_anomaly_trailing_down(
            grid, "ONDO/USDT", 0.478, -0.4, opps_low, "BULLISH_EXPANSION"
        )
        self.assertFalse(approved_low)
        self.assertEqual(score_low, 55.0)

        # 3. Rejection: Panic dump macro
        approved_macro, reason_macro, _ = evaluate_anomaly_trailing_down(
            grid, "ONDO/USDT", 0.478, -0.4, opps_high, "PANIC_DUMP"
        )
        self.assertFalse(approved_macro)

        # 4. Rejection: Already shifted once
        grid.trailing_down_shifts = 1
        approved_limit, reason_limit, _ = evaluate_anomaly_trailing_down(
            grid, "ONDO/USDT", 0.478, -0.4, opps_high, "BULLISH_EXPANSION"
        )
        self.assertFalse(approved_limit)

    def test_apply_trailing_down_shift_adjusts_range_and_resets_anomaly(self):
        grid = GridPosition(
            grid_id="test_shift",
            symbol="ONDO/USDT",
            grid_upper=0.52,
            grid_lower=0.48,
            grid_lines=5,
            step_pct=0.01,
            capital_total=40.0,
            capital_per_line=10.0,
            lines=[],
            anomaly_start_ts=12345.0,
            freeze_buys=True,
        )
        new_lower, new_upper = apply_trailing_down_shift(grid, 0.475)
        self.assertLess(new_lower, 0.48)
        self.assertLess(new_upper, 0.52)
        self.assertEqual(grid.trailing_down_shifts, 1)
        self.assertEqual(grid.anomaly_start_ts, 0.0)
        self.assertFalse(grid.freeze_buys)

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
