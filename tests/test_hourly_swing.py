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


def test_swing_trade_trailing_profit(test_bot, monkeypatch):
    # Trade con ATR 2.0% ($2.00 por token). Stop inicial $97.00 (-3.00%), Target $109.00 (+9.00%)
    trade = SwingTrade(
        trade_id="SWING_TEST_4",
        symbol="SOL/USDT",
        entry_price=100.0,
        amount=0.5,
        capital=50.0,
        target_price=109.0,
        stop_price=97.00,
        initial_stop=97.00,
        target_pct=0.09,
        stop_pct=0.03,
        atr_pct=2.0,
        rr_ratio=3.0,
        entry_time=1000.0,
        entry_fee=0.025
    )
    test_bot.active_trade = trade

    # 1. El precio sube a $104.00 (+4.0% > trailing trigger 3.0%)
    monkeypatch.setattr("hourly_swing_agent.exchange.fetch_ticker", lambda s: {"last": 104.00})
    manage_active_swing_trade(test_bot)

    # Trailing Stop Chandelier: Highest ($104.00) - 1.5x ATR ($3.00) = $101.00 (+1.0% asegurado)
    assert trade.is_trailing_active is True
    assert trade.stop_price == pytest.approx(101.00)
    assert trade.highest_price == pytest.approx(104.00)

    # 2. El precio sube aún más a $106.00
    monkeypatch.setattr("hourly_swing_agent.exchange.fetch_ticker", lambda s: {"last": 106.00})
    manage_active_swing_trade(test_bot)

    # Stop debe subir a Highest ($106.00) - 1.5x ATR ($3.00) = $103.00
    assert trade.stop_price == pytest.approx(103.00)
    assert trade.highest_price == pytest.approx(106.00)

    # 3. El precio retrocede a $102.80 (choca contra el trailing stop de $103.00)
    monkeypatch.setattr("hourly_swing_agent.exchange.fetch_ticker", lambda s: {"last": 102.80})
    manage_active_swing_trade(test_bot)

    # El trade debe cerrarse con ganancia asegurada por el trailing stop
    assert test_bot.active_trade is None
    stats = test_bot.db.get_stats()
    assert stats["total"] == 1
    assert stats["wins"] == 1
    assert stats["pnl"] > 1.0  # Ganancia positiva asegurada por Trailing Stop


def test_swing_compound_and_multi_trade_tiering(test_bot):
    # 1. Nivel inicial (< $120): 1 trade simultáneo, asigna ~80% de la caja libre
    test_bot.cash = 70.00
    assert test_bot.get_max_concurrent_trades() == 1
    assert "Mono-Sniper" in test_bot.get_tier_name()
    cap1 = test_bot.calculate_trade_capital()
    assert cap1 == pytest.approx(56.00)  # 70 * 0.80

    # 2. Cuenta crece a $150 (Tier Dual: $120 a $200)
    test_bot.cash = 150.00
    assert test_bot.get_max_concurrent_trades() == 2
    assert "Dual-Sniper" in test_bot.get_tier_name()
    cap2 = test_bot.calculate_trade_capital()
    assert cap2 == pytest.approx(67.50)  # 150 * 0.45

    # 3. Cuenta alcanza $200 (Tier Multi-Sniper diversificado al unísono)
    test_bot.cash = 210.00
    assert test_bot.get_max_concurrent_trades() == 3
    assert "Multi-Sniper Diversificado" in test_bot.get_tier_name()
    cap3 = test_bot.calculate_trade_capital()
    assert cap3 == pytest.approx(63.00)  # 210 * 0.30 por trade al unísono


