"""Lógica del Dollar Scalper en modo paper con libro de Pionex simulado (sin red ni dinero)."""
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def sc(tmp_path, monkeypatch):
    monkeypatch.setenv("SCALPER_PAPER", "1")
    monkeypatch.setenv("SCALPER_DATA_DIR", str(tmp_path))
    sys.modules.pop("dollar_scalper_agent", None)
    m = importlib.import_module("dollar_scalper_agent")
    book = {"bid": 10.00, "ask": 10.01}
    ex = m.PaperExecutor
    ex.reset(70.0)
    monkeypatch.setattr(ex, "get_symbol_rules", classmethod(lambda c: {"AAA_USDT": {
        "basePrecision": 2, "quotePrecision": 4, "minAmount": 10.0, "minTradeSize": 0.01}}))
    monkeypatch.setattr(ex, "get_market_depth", classmethod(lambda c, s, limit=5: {
        "bids": [[str(book["bid"]), "1000"], [str(book["bid"] - 0.01), "1000"]],
        "asks": [[str(book["ask"]), "1000"]]}))
    return m, ex, book


def test_buy_fill_fee_in_base_and_target_sell_pnl(sc):
    m, ex, book = sc
    oid = ex.place_limit_buy("AAA_USDT", 9.90, 6.0)
    assert ex.get_usdt_balance() == (pytest.approx(70 - 59.4), pytest.approx(59.4))
    assert [o["orderId"] for o in ex.get_open_orders("AAA_USDT")] == [oid]
    book["ask"] = 9.90  # el mercado toca el límite
    assert ex.get_open_orders("AAA_USDT") == []
    buy = ex.summarize_fill(ex.get_order("AAA_USDT", oid))
    assert buy["size"] == 6.0 and buy["base_fee"] == pytest.approx(6.0 * m.PIONEX_FEE_RATE)
    held = buy["size"] - buy["base_fee"]
    assert ex.get_coin_balance("AAA") == pytest.approx(held)
    book["bid"] = 9.95
    sid = ex.place_limit_sell("AAA_USDT", 10.00, held)
    assert sid and ex.get_order("AAA_USDT", sid)["status"] == "OPEN"
    book["bid"] = 10.00
    sell = ex.summarize_fill(ex.get_order("AAA_USDT", sid))
    assert sell["status"] == "CLOSED"
    pnl = sell["amount"] - sell["fee_usdt"] - buy["amount"]
    assert pnl == pytest.approx(5.99 * 10 * 0.9995 - 59.4, abs=1e-3)


def test_cancel_returns_funds_and_market_sell_crosses_book(sc):
    m, ex, book = sc
    ex.place_limit_buy("AAA_USDT", 9.00, 6.0)
    assert ex.cancel_all_orders("AAA_USDT")
    assert ex.get_usdt_balance() == (pytest.approx(70.0), pytest.approx(0.0))
    book["ask"] = 9.0
    oid = ex.place_limit_buy("AAA_USDT", 9.0, 6.0)
    ex.get_open_orders("AAA_USDT")
    res = ex.place_market_sell("AAA_USDT", 5.99)
    fill = ex.summarize_fill(ex.get_order("AAA_USDT", res["orderId"]))
    assert fill["status"] == "CLOSED" and fill["price"] == pytest.approx(10.00)


def test_buy_rejected_below_min_or_without_funds(sc):
    m, ex, _ = sc
    assert ex.place_limit_buy("AAA_USDT", 10.0, 0.5) is None
    assert ex.place_limit_buy("AAA_USDT", 10.0, 8.0) is None


def test_close_trade_uses_real_fills_and_cooldown(sc):
    m, ex, book = sc
    bot = m.ScalperBot()
    oid = ex.place_limit_buy("AAA_USDT", 10.00, 6.0)
    book["ask"] = 10.0
    buy = ex.summarize_fill(ex.get_order("AAA_USDT", oid))
    tr = m.ScalperTrade("t", "AAA_USDT", buy["price"], buy["size"] - buy["base_fee"], buy["amount"], "", buy["fee_usdt"])
    bot.active_trade = tr
    book["bid"] = 9.90
    assert m.market_exit(bot, tr, 9.90, "stop", is_stop=True)
    assert bot.active_trade is None
    assert bot.cooldowns["AAA_USDT"] > 0
    st = bot.db.get_stats()
    assert st["losses"] == 1 and st["pnl"] == pytest.approx(5.99 * 9.90 * 0.9995 - 60, abs=1e-3)  # 5.997 -> 5.99 por precisión


def test_state_roundtrip_atomic(sc):
    m, ex, _ = sc
    bot = m.ScalperBot()
    bot.pending_order = m.ScalperPendingOrder("1", "AAA_USDT", 10.0, 6.0, 60.0, "x")
    bot.save_state()
    assert os.path.getsize(m.SCALPER_STATE_FILE) > 0
    assert m.ScalperBot().pending_order.order_id == "1"



