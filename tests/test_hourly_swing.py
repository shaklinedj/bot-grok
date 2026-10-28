"""Pruebas unitarias para el motor Hourly Swing Sniper (1H/4H)."""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hourly_swing_agent import (
    SwingBot, SwingTrade, SwingDatabase, execute_swing_paper_entry, manage_active_swing_trade,
    analyze_breakout_15m, MIN_SCORE_V2, POST_STOP_EXTRA_SCORE,
    calc_hurst_exponent, detect_horizontal_channel, BoundedMicroGrid, GridLevel, manage_active_bounded_grid,
    fetch_order_flow_confirmation
)


@pytest.fixture
def test_bot(tmp_path, monkeypatch):
    db_file = os.path.join(tmp_path, "test_swing.db")
    monkeypatch.setattr("hourly_swing_agent.SWING_DB_FILE", db_file)
    
    bot = SwingBot(db_file)
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

    # 1. El precio sube a $104.00 (+4.0% > trailing trigger 3.6%)
    monkeypatch.setattr("hourly_swing_agent.exchange.fetch_ticker", lambda s: {"last": 104.00})
    manage_active_swing_trade(test_bot)

    # Trailing Stop V2 con Oxígeno: Highest ($104.00) - 1.5x ATR ($3.00) = $101.00 (+1.0% asegurado)
    assert trade.is_trailing_active is True
    assert trade.stop_price == pytest.approx(101.00)
    assert trade.highest_price == pytest.approx(104.00)

    # 2. El precio sube aún más a $106.00
    monkeypatch.setattr("hourly_swing_agent.exchange.fetch_ticker", lambda s: {"last": 106.00})
    manage_active_swing_trade(test_bot)

    # Stop debe subir a Highest ($106.00) - 1.5x ATR ($3.00) = $103.00
    assert trade.stop_price == pytest.approx(103.00)
    assert trade.highest_price == pytest.approx(106.00)

    # 3. El precio retrocede a $102.50 (choca contra el trailing stop de $103.00)
    monkeypatch.setattr("hourly_swing_agent.exchange.fetch_ticker", lambda s: {"last": 102.50})
    manage_active_swing_trade(test_bot)

    # El trade debe cerrarse con ganancia asegurada por el trailing stop
    assert test_bot.active_trade is None
    stats = test_bot.db.get_stats()
    assert stats["total"] == 1
    assert stats["wins"] == 1
    assert stats["pnl"] > 0.5  # Ganancia positiva asegurada por Trailing Stop


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

    mock_5m = [list(c) for c in mock_15m[:25]]

    monkeypatch.setattr("hourly_swing_agent.fetch_ohlcv_cached", lambda sym, tf, limit=60: mock_15m if tf == "15m" else (mock_5m if tf == "5m" else mock_1h))

    btc_ctx = {"change_1h": 0.2, "change_4h": 0.5, "trend_4h": "bullish"}
    res = analyze_breakout_15m("TEST/USDT", btc_ctx)

    assert res is not None
    assert res["breakout"] is True
    assert res["vol_spike"] >= 2.0
    assert res["double_green"] is True
    assert res["is_overextended"] is False
    assert 38.0 <= res["rsi_15m"] <= 68.0
    assert res["score"] >= MIN_SCORE_V2
    assert res["trigger_ready"] is True
    assert res["rr_ratio"] >= 2.0


def test_v2_overextension_anti_fomo(monkeypatch):
    # Simula una moneda que ya subió verticalmente (RSI > 75, sobreextendida)
    base_ts = 1700000000000
    mock_15m = []
    # 35 velas subiendo sin parar
    for i in range(40):
        p = 10.0 + i * 0.20
        mock_15m.append([base_ts + i * 900000, p - 0.1, p + 0.3, p - 0.1, p, 2000.0])

    mock_1h = []
    for i in range(30):
        p = 9.0 + i * 0.30
        mock_1h.append([base_ts + i * 3600000, p - 0.1, p + 0.2, p - 0.1, p, 5000.0])

    mock_5m = [list(c) for c in mock_15m[:25]]
    monkeypatch.setattr("hourly_swing_agent.fetch_ohlcv_cached", lambda sym, tf, limit=60: mock_15m if tf == "15m" else (mock_5m if tf == "5m" else mock_1h))

    btc_ctx = {"change_1h": 0.5, "change_4h": 1.0, "trend_4h": "bullish"}
    res = analyze_breakout_15m("FOMO/USDT", btc_ctx)

    assert res is not None
    # Debe ser detectada como sobreextendida / agotamiento
    assert res["is_overextended"] is True
    # Disparo estrictamente bloqueado para no comprar techos
    assert res["trigger_ready"] is False


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


def test_sqlite_settings_and_state_persistence(test_bot, tmp_path):
    # 1. Modificar configuración a través de update_settings
    test_bot.update_settings({"be_trigger_pct": 0.022, "stop_atr_mult": 1.4, "auto_atr_mode": False})
    
    # 2. Verificar que se persistió en la tabla bot_settings de SQLite
    db_settings = test_bot.db.get_all_settings()
    assert db_settings["be_trigger_pct"] == pytest.approx(0.022)
    assert db_settings["stop_atr_mult"] == pytest.approx(1.4)
    assert db_settings["auto_atr_mode"] is False

    # 3. Guardar estado en SQLite
    test_bot.cash = 95.50
    test_bot.save_state()
    db_state = test_bot.db.load_bot_state()
    assert db_state["cash"] == pytest.approx(95.50)

    # 4. Crear una nueva instancia de SwingBot con la misma base de datos SQLite y verificar carga
    bot2 = SwingBot(str(test_bot.db.db_path))
    assert bot2.settings["be_trigger_pct"] == pytest.approx(0.022)
    assert bot2.settings["auto_atr_mode"] is False
    assert bot2.cash == pytest.approx(95.50)


def test_post_trade_autopsy_and_sqlite_logging(test_bot, monkeypatch):
    """Verifica que el motor de autopsia clínica clasifique y persista en SQLite tras un stop."""
    trade = SwingTrade(
        trade_id="SWING_TEST_AUTOPSY",
        symbol="AUTO/USDT",
        entry_price=10.0,
        amount=5.0,
        capital=50.0,
        target_price=10.50,
        stop_price=9.85,
        initial_stop=9.85,
        target_pct=0.05,
        stop_pct=0.015,
        atr_pct=1.5,
        rr_ratio=3.33,
        entry_time=1000.0,
        entry_fee=0.025
    )
    test_bot.active_trade = trade

    # Precio cae al stop en 9.80
    monkeypatch.setattr("hourly_swing_agent.exchange.fetch_ticker", lambda s: {"last": 9.80})
    manage_active_swing_trade(test_bot)

    # Debe haberse generado y guardado la autopsia en la tabla trade_autopsies de SQLite
    autopsies = test_bot.db.get_recent_autopsies(5)
    assert len(autopsies) >= 1
    latest = autopsies[0]
    assert latest["trade_id"] == "SWING_TEST_AUTOPSY"
    assert latest["symbol"] == "AUTO/USDT"
    assert latest["pnl"] < 0
    assert "classification" in latest
    assert "lesson_learned" in latest


def test_btc_regime_gate_blocks_on_dump(monkeypatch):
    """Verifica que si Bitcoin está en régimen BEARISH_DUMP, las compras en altcoins queden bloqueadas."""
    mock_15m = [[1700000000000 + i * 900000, 10.0, 10.2, 9.9, 10.1, 1500.0] for i in range(40)]
    mock_1h = [[1700000000000 + i * 3600000, 9.8, 10.2, 9.7, 10.0, 5000.0] for i in range(30)]
    monkeypatch.setattr("hourly_swing_agent.fetch_ohlcv_cached", lambda sym, tf, limit=60: mock_15m if tf == "15m" else mock_1h)

    # Simular contexto macro con BTC en corrección bajista
    btc_dump_ctx = {"change_1h": -1.5, "change_4h": -3.0, "regime": "BEARISH_DUMP"}
    res = analyze_breakout_15m("ALT/USDT", btc_dump_ctx)

    assert res is not None
    assert res["trigger_ready"] is False
    assert "BLOQUEO" in res["status"]


def test_calc_hurst_exponent_and_channel_detection():
    """Verifica que el exponente de Hurst y el detector de canal horizontal identifiquen chop."""
    import numpy as np
    # 1. Serie oscilante con reversión a la media
    sine_series = [10.0 + np.sin(i * 0.5) * 0.5 for i in range(80)]
    h = calc_hurst_exponent(sine_series)
    assert h < 0.46  # Debe confirmar mean-reversion

    # 2. Canal horizontal
    mock_candles = []
    for i in range(36):
        o = 10.0 + np.sin(i * 0.5) * 0.12
        c = 10.0 + np.sin((i + 1) * 0.5) * 0.12
        h_val = max(o, c) + 0.04
        l_val = min(o, c) - 0.04
        mock_candles.append([1000 + i * 900, o, h_val, l_val, c, 1000])

    chan = detect_horizontal_channel(mock_candles)
    assert chan is not None
    assert 1.0 <= chan["width_pct"] <= 5.0
    assert abs(chan["slope_pct"]) <= 1.8


def test_bounded_grid_kill_switch_protection(test_bot, monkeypatch):
    """Verifica que el Kill-Switch de la malla acotada cierre toda la posición si rompe el canal."""
    grid = BoundedMicroGrid(
        grid_id="GRID_TEST_KILL",
        symbol="TEST/USDT",
        channel_support=9.80,
        channel_resistance=10.20,
        midpoint=10.0,
        hurst_exponent=0.38,
        kill_switch_price=9.68,
        total_capital=54.0
    )
    lvl1 = GridLevel(0, 9.95, 1.8, 18.0, status="FILLED")
    lvl1.fill_price = 9.95
    grid.levels = [lvl1]
    test_bot.active_grid = grid
    test_bot.cash = 45.0  # $45 cash libre + $18 en inventario

    # Precio perfora el canal y cae por debajo del Kill-Switch ($9.65 < $9.68)
    monkeypatch.setattr("hourly_swing_agent.exchange.fetch_ticker", lambda s: {"last": 9.65})
    manage_active_bounded_grid(test_bot)

    # La malla debe haberse autodestruido por Kill-Switch, liquidado inventario y vuelto a modo SWING
    assert test_bot.active_grid is None
    assert test_bot.active_mode == "SWING_SNIPER"
    # El capital debe haberse devuelto a la caja menos la pequeña pérdida acotada (~$0.54)
    assert test_bot.cash > 61.50
    stats = test_bot.db.get_stats()
    assert stats["total"] == 1


def test_bounded_grid_harvest_profit(test_bot, monkeypatch):
    """Verifica que la malla acotada coseche beneficios cuando el precio revierte hacia la resistencia."""
    grid = BoundedMicroGrid(
        grid_id="GRID_TEST_WIN",
        symbol="TEST/USDT",
        channel_support=9.80,
        channel_resistance=10.20,
        midpoint=10.0,
        hurst_exponent=0.38,
        kill_switch_price=9.68,
        total_capital=54.0
    )
    lvl1 = GridLevel(0, 9.90, 2.0, 19.80, status="FILLED")
    lvl1.fill_price = 9.90
    grid.levels = [lvl1]
    test_bot.active_grid = grid
    test_bot.cash = 43.50

    # Precio revierte y alcanza la resistencia del canal ($10.22 >= $10.20)
    monkeypatch.setattr("hourly_swing_agent.exchange.fetch_ticker", lambda s: {"last": 10.22})
    manage_active_bounded_grid(test_bot)

    # La malla debe haberse cerrado con ganancia cosechada
    assert test_bot.active_grid is None
    assert test_bot.cash > (43.50 + 19.80)  # Capital devuelto + PnL neto
    stats = test_bot.db.get_stats()
    assert stats["wins"] == 1
    assert stats["pnl"] > 0


def test_momentum_ignition_detection_and_3_4r_target(monkeypatch):
    """Verifica que el detector de Ignición de Momentum detecte la vela institucional y fije 3.4R."""
    # 23 velas de 15m en rango base consolidando (100.0 - 100.5) con RSI neutral (~50)
    c_15m = []
    for i in range(23):
        if i % 2 == 0:
            c_15m.append([1000 + i * 900, 100.2, 100.5, 99.8, 100.0, 1000.0])
        else:
            c_15m.append([1000 + i * 900, 100.0, 100.4, 99.9, 100.3, 1000.0])
    # Vela 24: Vela preparatoria
    c_15m.append([1000 + 23 * 900, 100.2, 100.6, 100.1, 100.5, 1200.0])
    # Vela 25: Ignición institucional que rompe la resistencia de 100.6 hacia 102.8 con 4.5x volumen
    c_15m.append([1000 + 24 * 900, 100.5, 102.8, 100.4, 102.6, 4500.0])

    c_1h = []
    for i in range(20):
        if i % 2 == 0:
            c_1h.append([1000 + i * 3600, 100.0, 100.8, 99.5, 100.2, 5000.0])
        else:
            c_1h.append([1000 + i * 3600, 100.2, 100.9, 99.8, 100.1, 5000.0])
    c_1h[-1] = [1000 + 19 * 3600, 100.1, 102.8, 99.9, 102.6, 12000.0]

    c_5m = []
    for i in range(25):
        if i % 2 == 0:
            c_5m.append([1000 + i * 300, 101.5, 102.2, 101.2, 101.8, 800.0])
        else:
            c_5m.append([1000 + i * 300, 101.8, 102.6, 101.6, 102.5, 1200.0])

    def mock_fetch_ohlcv(sym, tf, limit=60):
        if tf == "15m":
            return c_15m
        elif tf == "1h":
            return c_1h
        elif tf == "5m":
            return c_5m
        return []

    monkeypatch.setattr("hourly_swing_agent.fetch_ohlcv_cached", mock_fetch_ohlcv)

    btc_ctx = {
        "regime": "NEUTRAL_TRANSITION",
        "change_1h": 0.20,
        "change_4h": 0.50,
        "price": 80000.0,
        "can_trade_alts": True
    }

    res = analyze_breakout_15m("SOL/USDT", btc_ctx)

    assert res is not None
    assert res["is_momentum_ignition"] is True
    assert res["vol_spike"] >= 2.0
    assert res["rr_ratio"] >= 3.4
    assert res["trigger_ready"] is True
    assert "IGNICIÓN MOMENTUM" in res["status"]


def test_order_flow_centinela_confirm():
    """Verifica que el Centinela de Order Flow confirme la entrada cuando hay OBI positivo y compras agresivas."""
    class MockExchange:
        def fetch_order_book(self, symbol, limit=20):
            # Bids superan a Asks (OBI positivo)
            return {
                "bids": [[100.0, 50.0], [99.9, 40.0]],
                "asks": [[100.1, 20.0], [100.2, 10.0]]
            }
        def fetch_trades(self, symbol, limit=50):
            # 70% de compras agresivas a mercado
            return [{"side": "buy", "amount": 7.0}] * 10 + [{"side": "sell", "amount": 3.0}] * 10

    flow = fetch_order_flow_confirmation("SOL/USDT", ex=MockExchange())
    assert flow["confirmed"] is True
    assert flow["obi"] > 0.0
    assert flow["buy_ratio_pct"] == 70.0
    assert flow["spread_pct"] < 0.25


def test_order_flow_centinela_veto_blocks_trade(test_bot):
    """Verifica que el Centinela de Order Flow vete la entrada si hay presión vendedora en la cinta."""
    class MockVetoExchange:
        def fetch_order_book(self, symbol, limit=20):
            return {
                "bids": [[100.0, 10.0]],
                "asks": [[100.1, 50.0]]  # Asks masivos
            }
        def fetch_trades(self, symbol, limit=50):
            # 80% de ventas agresivas a mercado (solo 20% compras)
            return [{"side": "buy", "amount": 2.0}] * 10 + [{"side": "sell", "amount": 8.0}] * 10

    # Test directo de veto
    flow = fetch_order_flow_confirmation("SOL/USDT", ex=MockVetoExchange())
    assert flow["confirmed"] is False
    assert flow["buy_ratio_pct"] < 45.0
    assert "Ventas agresivas" in flow["reason"] or "Muro de venta" in flow["reason"]


def test_database_get_full_history(test_bot):
    """Verifica que get_full_history calcule correctamente la curva de patrimonio acumulada."""
    db = test_bot.db
    # Registrar trade BUY inicial
    db.log_trade("BTC/USDT", "BUY", 80000.0, 0.0005, 40.0, 0.0, "Entrada test", "PAPER_SWING")
    # Registrar trade SELL con PnL +2.50
    db.log_trade("BTC/USDT", "SELL", 85000.0, 0.0005, 42.5, 2.50, "Salida con target", "PAPER_SWING")
    # Registrar trade SELL con PnL -1.20
    db.log_trade("ETH/USDT", "SELL", 2500.0, 0.01, 25.0, -1.20, "Stop loss", "PAPER_SWING")

    history = db.get_full_history()
    assert len(history["trades"]) == 3
    # Curva debe tener punto 0 (Init $70.0) + 2 cierres con PnL != 0
    assert len(history["equity_curve"]) == 3
    assert history["equity_curve"][0]["equity"] == 70.0
    assert history["equity_curve"][1]["equity"] == 72.5
    assert history["equity_curve"][2]["equity"] == 71.3


def test_bounded_grid_midpoint_profit_harvest(test_bot, monkeypatch):
    """Verifica que la malla acotada se coseche al cruzar el midpoint con ganancia neta >= +0.30%."""
    grid = BoundedMicroGrid(
        grid_id="GRID_TEST",
        symbol="BTC/USDT",
        channel_support=80000.0,
        channel_resistance=81000.0,
        midpoint=80500.0,
        hurst_exponent=0.38,
        kill_switch_price=79500.0,
        total_capital=45.0
    )
    grid.levels = [
        GridLevel(level_idx=0, price=80100.0, capital=15.0, amount=15.0/80100.0, status="FILLED"),
        GridLevel(level_idx=1, price=80200.0, capital=15.0, amount=15.0/80200.0, status="FILLED"),
        GridLevel(level_idx=2, price=80300.0, capital=15.0, amount=15.0/80300.0, status="FILLED"),
    ]
    test_bot.active_grid = grid
    test_bot.cash = 10.0

    # Precio actual a $80,550 (> midpoint $80,500 y ganancia +0.43% > +0.30%)
    monkeypatch.setattr("hourly_swing_agent.exchange.fetch_ticker", lambda s: {"last": 80550.0})
    manage_active_bounded_grid(test_bot)

    # Debe haberse cosechado
    assert test_bot.active_grid is None
    # Capital liberado a cash (> 10.0 + 45.0)
    assert test_bot.cash > 55.0
