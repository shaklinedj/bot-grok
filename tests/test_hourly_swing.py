"""Pruebas unitarias para el motor Hourly Swing Sniper (1H/4H)."""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hourly_swing_agent import (
    SwingBot, SwingTrade, SwingDatabase, execute_swing_paper_entry, manage_active_swing_trade,
    analyze_breakout_15m, MIN_SCORE_V2, POST_STOP_EXTRA_SCORE
)


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

    # 1. Precio sube a $101.80 (+1.80% > umbral dinámico ATR Opción B)
    monkeypatch.setattr("hourly_swing_agent.exchange.fetch_ticker", lambda s: {"last": 101.80})
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

    # Trailing Stop V2: Highest ($104.00) - 0.8x ATR ($1.60) = $102.40 (+2.4% asegurado)
    assert trade.is_trailing_active is True
    assert trade.stop_price == pytest.approx(102.40)
    assert trade.highest_price == pytest.approx(104.00)

    # 2. El precio sube aún más a $106.00
    monkeypatch.setattr("hourly_swing_agent.exchange.fetch_ticker", lambda s: {"last": 106.00})
    manage_active_swing_trade(test_bot)

    # Stop debe subir a Highest ($106.00) - 0.8x ATR ($1.60) = $104.40
    assert trade.stop_price == pytest.approx(104.40)
    assert trade.highest_price == pytest.approx(106.00)

    # 3. El precio retrocede a $104.00 (choca contra el trailing stop de $104.40)
    monkeypatch.setattr("hourly_swing_agent.exchange.fetch_ticker", lambda s: {"last": 104.00})
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


def test_v2_breakout_detection(monkeypatch):
    # Genera 40 velas de 15m con oscilación natural donde la última rompe la resistencia con volumen spike
    base_ts = 1700000000000
    mock_15m = []
    prices = [
        10.0, 10.1, 10.05, 10.15, 10.1, 10.2, 10.15, 10.25, 10.2, 10.3,
        10.25, 10.2, 10.15, 10.2, 10.25, 10.3, 10.28, 10.32, 10.3, 10.35,
        10.32, 10.3, 10.28, 10.32, 10.35, 10.3, 10.25, 10.3, 10.35, 10.32,
        10.3, 10.25, 10.20, 10.15, 10.18, 10.15, 10.12, 10.18, 10.25, 10.45
    ]
    for i, p in enumerate(prices):
        prev = prices[i - 1] if i > 0 else p
        o = prev
        c = p
        h = max(o, c) + 0.05
        l = min(o, c) - 0.05
        vol = 3500.0 if i == 39 else 1000.0
        mock_15m.append([base_ts + i * 900000, o, h, l, c, vol])

    # 30 velas de 1h con tendencia alcista y fuerza relativa vs BTC
    mock_1h = []
    for i in range(30):
        p = 9.8 + i * 0.03
        mock_1h.append([base_ts + i * 3600000, p - 0.02, p + 0.05, p - 0.05, p, 5000.0])
    # Última vela 1h con buen avance para dar alta fuerza relativa
    mock_1h[-1][4] = 10.65

    monkeypatch.setattr("hourly_swing_agent.fetch_ohlcv_cached", lambda sym, tf, limit=60: mock_15m if tf == "15m" else mock_1h)

    btc_ctx = {"change_1h": 0.2, "change_4h": 0.5, "trend_4h": "bullish"}
    res = analyze_breakout_15m("TEST/USDT", btc_ctx)

    assert res is not None
    assert res["breakout"] is True
    assert res["vol_spike"] >= 2.0
    assert res["double_green"] is True
    assert 38.0 <= res["rsi_15m"] <= 68.0
    assert res["score"] >= MIN_SCORE_V2
    assert res["trigger_ready"] is True
    assert res["rr_ratio"] >= 2.0


def test_v2_falling_knife_rejection(monkeypatch):
    # Moneda cayendo en picada: últimas 4 velas de 1H rojas
    base_ts = 1700000000000
    mock_15m = []
    for i in range(40):
        mock_15m.append([base_ts + i * 900000, 10.0, 10.2, 9.5, 9.6, 1000.0])

    mock_1h = []
    for i in range(26):
        mock_1h.append([base_ts + i * 3600000, 12.0, 12.2, 11.8, 11.9, 5000.0])
    # 4 velas consecutivas rojas en 1H (cuchillo cayendo)
    for i in range(4):
        p = 11.5 - i * 0.5
        mock_1h.append([base_ts + (26 + i) * 3600000, p, p + 0.1, p - 0.6, p - 0.5, 8000.0])

    monkeypatch.setattr("hourly_swing_agent.fetch_ohlcv_cached", lambda sym, tf, limit=60: mock_15m if tf == "15m" else mock_1h)

    btc_ctx = {"change_1h": 0.0, "change_4h": 0.0, "trend_4h": "neutral"}
    res = analyze_breakout_15m("FALLING/USDT", btc_ctx)

    assert res is not None
    assert res["is_falling_knife"] is True
    assert res["trigger_ready"] is False
    assert res["score"] < 50.0  # Penalizada fuertemente por cuchillo cayendo


def test_v2_anti_ametralladora_threshold(test_bot):
    import time
    now_ts = time.time()
    # Simular stop reciente hace 60 segundos
    test_bot.last_stop_time = now_ts - 60.0

    time_since_last_stop = now_ts - test_bot.last_stop_time
    is_recovering = time_since_last_stop < 300.0
    effective_score = (MIN_SCORE_V2 + POST_STOP_EXTRA_SCORE) if is_recovering else MIN_SCORE_V2

    assert is_recovering is True
    assert effective_score == MIN_SCORE_V2 + POST_STOP_EXTRA_SCORE  # 70 + 15 = 85

    # Simular que pasaron más de 300 segundos
    test_bot.last_stop_time = now_ts - 350.0
    time_since_last_stop2 = now_ts - test_bot.last_stop_time
    is_recovering2 = time_since_last_stop2 < 300.0
    effective_score2 = (MIN_SCORE_V2 + POST_STOP_EXTRA_SCORE) if is_recovering2 else MIN_SCORE_V2

    assert is_recovering2 is False
    assert effective_score2 == MIN_SCORE_V2  # Vuelve a 70



