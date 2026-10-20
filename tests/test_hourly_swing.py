"""Pruebas unitarias para el motor Hourly Swing Sniper (1H/4H)."""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hourly_swing_agent import SwingBot, SwingTrade, SwingDatabase, execute_swing_paper_entry, manage_active_swing_trade


@pytest.fixture
def test_bot(tmp_path, monkeypatch):
    db_file = os.path.join(tmp_path, "test_swing.db")
    state_file = os.path.join(tmp_path, "test_state.json")
    monkeypatch.setattr("hourly_swing_agent.SWING_DB_FILE", db_file)
    monkeypatch.setattr("hourly_swing_agent.SWING_STATE_FILE", state_file)
    
    bot = SwingBot()
    bot.db = SwingDatabase(db_file)
    bot.cash = 70.00
    bot.active_trade = None
    return bot


def test_swing_trade_break_even_shield(test_bot, monkeypatch):
    # Simula una posición en SOL a $100.00 con Stop inicial a $98.50 (-1.5%) y Target a $105.00 (+5.0%)
    trade = SwingTrade(
        trade_id="SWING_TEST_1",
        symbol="SOL/USDT",
        entry_price=100.0,
        amount=0.5,
        capital=50.0,
        target_price=105.0,
        stop_price=98.50,
        initial_stop=98.50,
        target_pct=0.05,
        stop_pct=0.015,
        atr_pct=1.8,
        rr_ratio=3.33,
        entry_time=1000.0,
        entry_fee=0.025
    )
    test_bot.active_trade = trade

    # 1. Precio sube a $101.50 (+1.50% > +1.20% umbral Break-Even)
    monkeypatch.setattr("hourly_swing_agent.exchange.fetch_ticker", lambda s: {"last": 101.50})
    manage_active_swing_trade(test_bot)

    # El Escudo Break-Even debe activarse y mover el Stop a $100.20 (+0.20%)
    assert trade.is_be_active is True
    assert trade.stop_price == pytest.approx(100.20)
    assert test_bot.active_trade is not None


def test_swing_trade_target_win(test_bot, monkeypatch):
    trade = SwingTrade(
        trade_id="SWING_TEST_2",
        symbol="SOL/USDT",
        entry_price=100.0,
        amount=0.5,
        capital=50.0,
        target_price=105.0,
        stop_price=98.50,
        initial_stop=98.50,
        target_pct=0.05,
        stop_pct=0.015,
        atr_pct=1.8,
        rr_ratio=3.33,
        entry_time=1000.0,
        entry_fee=0.025
    )
    test_bot.active_trade = trade

    # Precio alcanza el Target a $105.00
    monkeypatch.setattr("hourly_swing_agent.exchange.fetch_ticker", lambda s: {"last": 105.10})
    manage_active_swing_trade(test_bot)

    # Posición debe cerrarse con ganancia neta en la caja
    assert test_bot.active_trade is None
    stats = test_bot.db.get_stats()
    assert stats["total"] == 1
    assert stats["wins"] == 1
    assert stats["pnl"] > 2.0  # +$2.50 bruto menos fees


def test_swing_trade_stop_loss(test_bot, monkeypatch):
    trade = SwingTrade(
        trade_id="SWING_TEST_3",
        symbol="SOL/USDT",
        entry_price=100.0,
        amount=0.5,
        capital=50.0,
        target_price=105.0,
        stop_price=98.50,
        initial_stop=98.50,
        target_pct=0.05,
        stop_pct=0.015,
        atr_pct=1.8,
        rr_ratio=3.33,
        entry_time=1000.0,
        entry_fee=0.025
    )
    test_bot.active_trade = trade

    # Precio cae por debajo del Stop Loss a $98.40
    monkeypatch.setattr("hourly_swing_agent.exchange.fetch_ticker", lambda s: {"last": 98.40})
    manage_active_swing_trade(test_bot)

    # Posición debe cerrarse y registrar pérdida controlada
    assert test_bot.active_trade is None
    stats = test_bot.db.get_stats()
    assert stats["total"] == 1
    assert stats["losses"] == 1
    assert stats["pnl"] < 0
