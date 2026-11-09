import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reversion_strategy import evaluate_rebound_signal


def candles(closes):
    rows = np.zeros((len(closes), 6), dtype=float)
    for i, close in enumerate(closes):
        rows[i] = [i * 3_600_000, close, close + 0.2, close - 0.2, close, 100_000]
    return rows


def eligible_market():
    asset = candles([100] + [94.5] * 23 + [95.0])
    btc = candles([100] * 25)
    asset[-2] = [23 * 3_600_000, 94.4, 94.7, 94.2, 94.5, 100_000]
    asset[-1] = [24 * 3_600_000, 94.7, 95.2, 94.6, 95.0, 150_000]
    return asset, btc


def test_accepts_moderate_fall_after_confirmed_rebound():
    asset, btc = eligible_market()

    signal = evaluate_rebound_signal(asset, btc)

    assert signal is not None
    assert np.isclose(signal["r24"], -0.05)
    assert signal["volume_ratio"] == 1.5
    assert signal["quote_volume_24h"] >= 10_000_000
    assert signal["rebound_pct"] > 0


def test_rejects_fall_outside_moderate_range():
    asset, btc = eligible_market()
    asset[0, 4] = 110

    assert evaluate_rebound_signal(asset, btc) is None


def test_rejects_without_breaking_previous_candle_high():
    asset, btc = eligible_market()
    asset[-1, 4] = 94.6
    asset[-1, 2] = 94.8

    assert evaluate_rebound_signal(asset, btc) is None


def test_rejects_declining_low_and_weak_volume():
    asset, btc = eligible_market()
    asset[-1, 3] = 94.1
    assert evaluate_rebound_signal(asset, btc) is None

    asset, btc = eligible_market()
    asset[-1, 5] = 400_000
    assert evaluate_rebound_signal(asset, btc) is None


def test_rejects_extreme_rebound_candle():
    asset, btc = eligible_market()
    asset[-1] = [24 * 3_600_000, 94.7, 97.0, 94.6, 96.2, 150_000]

    assert evaluate_rebound_signal(asset, btc) is None


def test_rejects_market_crash_and_extreme_relative_weakness():
    asset, btc = eligible_market()
    asset[0, 4] = 102
    btc[0, 4] = 105
    assert evaluate_rebound_signal(asset, btc) is None

    asset, btc = eligible_market()
    btc[0, 4] = 97
    assert evaluate_rebound_signal(asset, btc) is None
