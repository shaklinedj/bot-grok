"""
Unit and Integration Tests for Grade 10 Institutional Architecture:
1. Dynamic Fractional Kelly & Volatility Scaling
2. L2 Orderbook Depth & VWAP Slippage Engine
3. Latency Budgeting & Stale Price Guard
4. Triple-Ledger Reconciliation & Self-Healing Audit
"""
import pytest
import time
import os

from risk.dynamic_sizing import (
    calculate_fractional_kelly_ratio,
    scale_capital_by_volatility,
    get_institutional_trade_size
)
from execution.depth_slippage import (
    calculate_orderbook_vwap,
    evaluate_execution_route
)
from execution.stale_guard import (
    validate_quote_freshness,
    check_spread_health,
    sanitize_execution_context
)
from auditor.reconciler import QuantitativeReconciler


# -------------------------------------------------------------
# 1. Tests for Dynamic Sizing & Fractional Kelly
# -------------------------------------------------------------
def test_fractional_kelly_positive_edge():
    # Win rate 70%, R:R 2.0 -> Full Kelly = (0.7*2 - 0.3) / 2 = 1.1 / 2 = 0.55
    # Fractional Kelly (0.25) -> 0.55 * 0.25 = 0.1375 -> bounded to min_ratio 0.15
    f = calculate_fractional_kelly_ratio(0.70, 2.0, kelly_fraction=0.25)
    assert 0.13 <= f <= 0.90


def test_fractional_kelly_negative_edge():
    # Win rate 30%, R:R 1.0 -> Full Kelly negative -> fallback to min_ratio
    f = calculate_fractional_kelly_ratio(0.30, 1.0, kelly_fraction=0.25, min_ratio=0.15)
    assert f == 0.15


def test_volatility_scaling_compression_and_expansion():
    # High volatility (4.0% vs 2.0% baseline) -> contracts capital
    scaled_down = scale_capital_by_volatility(50.0, current_atr_pct=4.0, baseline_atr_pct=2.0)
    assert scaled_down < 50.0
    assert scaled_down == 25.0  # 50 * (2/4) = 25.0

    # Low volatility (1.0% vs 2.0% baseline) -> expands capital up to max_scale (1.35x)
    scaled_up = scale_capital_by_volatility(50.0, current_atr_pct=1.0, baseline_atr_pct=2.0, max_scale=1.35)
    assert scaled_up == 67.5  # 50 * 1.35


def test_get_institutional_trade_size_bounds():
    res = get_institutional_trade_size(
        equity=60.0,
        cash=60.0,
        win_rate=0.75,
        profit_loss_ratio=2.2,
        current_atr_pct=2.0,
        baseline_atr_pct=2.0
    )
    assert "final_capital" in res
    assert 15.0 <= res["final_capital"] <= 60.0


# -------------------------------------------------------------
# 2. Tests for L2 Orderbook VWAP & Depth Slippage
# -------------------------------------------------------------
def test_orderbook_vwap_single_level():
    asks = [[100.0, 10.0]]  # $1000 quote depth
    res = calculate_orderbook_vwap(asks, target_amount_quote=50.0, side="BUY")
    assert res["vwap"] == 100.0
    assert res["slippage_pct"] == 0.0
    assert res["is_liquid"] is True


def test_orderbook_vwap_multi_level_slippage():
    asks = [
        [100.0, 0.20],  # $20 quote
        [101.0, 0.50],  # $50.50 quote
        [103.0, 1.00]   # $103 quote
    ]
    # Buying $50 quote: absorbs $20 at 100.0 and $30 at 101.0
    res = calculate_orderbook_vwap(asks, target_amount_quote=50.0, side="BUY")
    assert res["vwap"] > 100.0
    assert res["levels_swept"] == 2
    assert res["slippage_pct"] > 0.0


def test_evaluate_execution_route():
    # Deep liquid book -> DIRECT_TAKER
    orderbook = {
        "asks": [[100.0, 100.0], [100.05, 200.0]],
        "bids": [[99.95, 100.0], [99.90, 200.0]]
    }
    decision = evaluate_execution_route("SOL/USDT", target_capital=50.0, expected_gain_pct=2.5, orderbook=orderbook)
    assert decision["recommended_route"] == "DIRECT_TAKER"

    # Shallow illiquid book -> MAKER_TWAP
    shallow_book = {
        "asks": [[100.0, 0.05], [105.0, 0.10], [115.0, 1.0]],
        "bids": [[95.0, 0.10]]
    }
    decision_illiquid = evaluate_execution_route("ILLIQUID/USDT", target_capital=50.0, expected_gain_pct=2.5, orderbook=shallow_book)
    assert decision_illiquid["recommended_route"] == "MAKER_TWAP"


# -------------------------------------------------------------
# 3. Tests for Stale Guard & Latency Budgeting
# -------------------------------------------------------------
def test_quote_freshness_valid():
    now_ms = int(time.time() * 1000)
    res = validate_quote_freshness(quote_timestamp_ms=now_ms - 350, max_age_ms=1500, current_time_ms=now_ms)
    assert res["valid"] is True


def test_quote_freshness_stale():
    now_ms = int(time.time() * 1000)
    res = validate_quote_freshness(quote_timestamp_ms=now_ms - 2200, max_age_ms=1500, current_time_ms=now_ms)
    assert res["valid"] is False
    assert "Cotización caduca" in res["warning"]


def test_spread_health():
    # Normal spread 0.05%
    res = check_spread_health(bid=100.0, ask=100.05, baseline_spread_pct=0.05, max_spread_multiplier=3.0)
    assert res["valid"] is True

    # Blown out spread (0.30% vs baseline 0.05% * 3 = 0.15% max)
    res_bad = check_spread_health(bid=100.0, ask=100.30, baseline_spread_pct=0.05, max_spread_multiplier=3.0)
    assert res_bad["valid"] is False


def test_sanitize_execution_context():
    now_ms = int(time.time() * 1000)
    safe = sanitize_execution_context(
        symbol="BTC/USDT",
        bid=50000.0,
        ask=50010.0,
        quote_timestamp_ms=now_ms - 100,
        baseline_spread_pct=0.05
    )
    assert safe["safe_to_execute"] is True


# -------------------------------------------------------------
# 4. Tests for Triple-Ledger Reconciler
# -------------------------------------------------------------
def test_triple_ledger_reconciler(tmp_path):
    test_db = os.path.join(tmp_path, "test_reconciler.db")
    reconciler = QuantitativeReconciler(db_path=test_db)

    class DummyBot:
        def __init__(self):
            self.cash = 60.0
            self.initial_capital = 60.0
            self.active_trades = {}
            self.active_grid = None

    bot = DummyBot()
    report = reconciler.reconcile_swing_engine(bot)
    assert report["status"] == "BALANCED"
    assert report["is_balanced"] is True
    assert report["delta_usdt"] == 0.0
