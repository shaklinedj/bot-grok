"""
Tests de integración End-to-End con servidor HTTP efímero (requests reales con urllib.request).
Valida endpoints del Dashboard, Terminal Cuántica (/quantum) y API REST (/api/status, /api/history, /api/settings).
"""
import os
import json
import urllib.request
import urllib.error
import pytest

from engine.swing_bot import SwingBot
from server.routes import start_swing_dashboard


@pytest.fixture
def ephemeral_server(tmp_path):
    """Levanta un servidor HTTP efímero en 127.0.0.1 con puerto dinámico asignado por el OS."""
    db_file = os.path.join(tmp_path, "ephemeral_vault.db")
    bot = SwingBot(db_file)
    bot.cash = 62.44
    bot.settings["min_score"] = 72.0
    bot.settings["trail_distance_atr"] = 1.5

    # Sembrar un trade y una autopsia para verificar respuestas ricas
    bot.db.log_trade(
        symbol="FET/USDT",
        side="BUY",
        price=1.25,
        amount=40.0,
        capital=50.0,
        pnl=0.0,
        fee=0.0375,
        order_id="SWING_1001",
        target_price=1.35,
        stop_price=1.20,
        note="Entrada test de integración",
        parent_trade_id="SWING_1001"
    )
    bot.db.log_trade(
        symbol="FET/USDT",
        side="SELL",
        price=1.283,
        amount=40.0,
        capital=50.0,
        pnl=1.25,
        fee=0.0385,
        order_id="SWING_1001",
        target_price=1.35,
        stop_price=1.20,
        note="🏆 TARGET V2 (+2.64%)",
        parent_trade_id="SWING_1001"
    )
    bot.db.log_autopsy(
        trade_id="SWING_1001",
        symbol="FET/USDT",
        pnl=1.25,
        pnl_pct=2.5,
        duration_s=3600.0,
        mfe_pct=2.8,
        mae_pct=0.4,
        exit_reason="🏆 TARGET V2 (+2.64%)",
        classification="TARGET_HIT",
        btc_regime="BULLISH_EXPANSION",
        lesson_learned="Ruptura sólida con expansión completa.",
        adaptive_action="Mantener parámetros."
    )

    # Iniciar servidor efímero en puerto 0 (el SO asigna un puerto libre)
    server, thread = start_swing_dashboard(bot, port=0, host="127.0.0.1")
    port = server.server_address[1]
    base_url = f"http://127.0.0.1:{port}"

    yield {"bot": bot, "url": base_url, "port": port}

    # Desmantelar servidor limpiamente
    server.shutdown()
    server.server_close()


def test_http_get_dashboard_root(ephemeral_server):
    """Verifica que el dashboard HTML raíz se sirva correctamente."""
    url = ephemeral_server["url"] + "/"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        content_type = resp.headers.get("Content-Type", "")
        assert "text/html" in content_type
        html = resp.read().decode("utf-8")
        assert "<!DOCTYPE html>" in html
        assert "THE ADAPTIVE SWING SNIPER" in html or "Dashboard" in html


def test_http_get_quantum_terminal(ephemeral_server):
    """Verifica que /quantum cargue la terminal Monte Carlo interactiva."""
    url = ephemeral_server["url"] + "/quantum"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        content_type = resp.headers.get("Content-Type", "")
        assert "text/html" in content_type
        html = resp.read().decode("utf-8")
        assert "Quantum Monte Carlo" in html or "QUANTUM" in html


def test_http_get_api_status(ephemeral_server):
    """Verifica que /api/status devuelva el JSON completo de telemetría y balances."""
    url = ephemeral_server["url"] + "/api/status"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "cash" in data
        assert data["cash"] == pytest.approx(62.44)
        assert "equity" in data
        assert "settings" in data
        assert data["settings"]["min_score"] == 72.0
        assert "recent_autopsies" in data
        assert len(data["recent_autopsies"]) >= 1
        assert data["recent_autopsies"][0]["symbol"] == "FET/USDT"


def test_http_get_api_history(ephemeral_server):
    """Verifica que /api/history devuelva trades y curva de equity acumulada."""
    url = ephemeral_server["url"] + "/api/history"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "trades" in data
        assert len(data["trades"]) == 2
        assert "equity_curve" in data
        assert len(data["equity_curve"]) >= 2
        # Verificar parent_trade_id emparejado en el JSON
        closed_trade = next(t for t in data["trades"] if t["side"] == "SELL")
        assert closed_trade["parent_trade_id"] == "SWING_1001"


def test_http_get_api_autopsies(ephemeral_server):
    """Verifica que /api/autopsies liste el historial de autoaprendizaje."""
    url = ephemeral_server["url"] + "/api/autopsies"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["classification"] == "TARGET_HIT"


def test_http_post_api_settings_update(ephemeral_server):
    """Verifica que POST a /api/settings actualice en caliente los parámetros en SQLite."""
    url = ephemeral_server["url"] + "/api/settings"
    payload = json.dumps({"trail_distance_atr": 1.75, "min_score": 77.0}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")

    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        result = json.loads(resp.read().decode("utf-8"))
        assert result["status"] == "ok"
        assert result["settings"]["trail_distance_atr"] == pytest.approx(1.75)
        assert result["settings"]["min_score"] == pytest.approx(77.0)

    # Verificar que el bot en memoria y la base de datos se actualizaron
    bot = ephemeral_server["bot"]
    assert bot.settings["trail_distance_atr"] == pytest.approx(1.75)
    db_settings = bot.db.get_all_settings()
    assert db_settings["trail_distance_atr"] == pytest.approx(1.75)


def test_http_404_not_found(ephemeral_server):
    """Verifica respuesta 404 para rutas inexistentes."""
    url = ephemeral_server["url"] + "/invalid_route_xyz"
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(url, timeout=5)
    assert exc_info.value.code == 404
