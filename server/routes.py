"""
Rutas HTTP, API REST y Servidor Dashboard para Antigravity Swing & Grid Bot.
"""
import os
import json
import http.server
import threading
from typing import Optional, Tuple

from config import BASE_DIR, SWING_HTTP_PORT
from server.templates import DASHBOARD_HTML
from scoring.market_scanner import update_btc_context


class SwingHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    bot = None

    def log_message(self, format, *args):
        pass  # Silenciar logs HTTP estándar para mantener la consola limpia

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode("utf-8"))
        elif self.path == "/quantum" or self.path == "/quantum.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            quantum_path = os.path.join(BASE_DIR, "quantum_terminal.html")
            if os.path.exists(quantum_path):
                with open(quantum_path, "r", encoding="utf-8") as f:
                    self.wfile.write(f.read().encode("utf-8"))
            else:
                self.wfile.write(b"<h1>Quantum Terminal no encontrada</h1>")
        elif self.path == "/api/autopsies":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            autopsies = self.bot.db.get_recent_autopsies(20) if self.bot else []
            self.wfile.write(json.dumps(autopsies).encode("utf-8"))
        elif self.path == "/api/history":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            history_data = self.bot.db.get_full_history() if self.bot else []
            self.wfile.write(json.dumps(history_data).encode("utf-8"))
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            bot = self.bot
            if not bot:
                self.wfile.write(json.dumps({"status": "no_bot"}).encode("utf-8"))
                return

            with bot.data_lock:
                telemetry = list(bot.radar_telemetry)
                stats = bot.db.get_stats()
                events = bot.db.get_recent_events(30)
                grid_stats = dict(bot.real_grid_stats)
                trades_list = list(bot.active_trades.values())
                last_closed = bot.db.get_last_closed_trade()
                autopsies = bot.db.get_recent_autopsies(5)

            invested = sum(round(t.amount * t.entry_price, 2) for t in trades_list)
            unrealized_pnl = sum(getattr(t, "unrealized_pnl", 0.0) for t in trades_list)
            unrealized_pnl_pct = ((unrealized_pnl / invested) * 100.0) if invested > 0 else 0.0
            grid_obj = getattr(bot, "active_grid", None)
            grid_dict = grid_obj.to_dict() if grid_obj else None
            grid_inv = grid_obj.get_invested_capital() if grid_obj else 0.0
            grid_unreal = grid_obj.unrealized_pnl if grid_obj else 0.0

            total_invested = invested + grid_inv
            total_unrealized = unrealized_pnl + grid_unreal
            total_unrealized_pct = ((total_unrealized / total_invested) * 100.0) if total_invested > 0 else 0.0
            equity = bot.cash + (total_invested + total_unrealized)

            buda_sim = None
            buda_file = os.path.join(BASE_DIR, "buda_sim_state.json")
            if os.path.exists(buda_file):
                try:
                    with open(buda_file, "r", encoding="utf-8") as bf:
                        buda_sim = json.load(bf)
                except Exception:
                    pass

            carry_sim = None
            carry_file = os.path.join(BASE_DIR, "cash_carry_sim_state.json")
            if os.path.exists(carry_file):
                try:
                    with open(carry_file, "r", encoding="utf-8") as cf:
                        carry_sim = json.load(cf)
                except Exception:
                    pass

            payload = {
                "cash": round(bot.cash, 2),
                "equity": round(equity, 2),
                "invested": round(total_invested, 2),
                "unrealized_pnl": round(total_unrealized, 4),
                "unrealized_pnl_pct": round(total_unrealized_pct, 2),
                "tier_mode": bot.get_tier_name(),
                "active_mode": getattr(bot, "active_mode", "SWING_SNIPER"),
                "max_concurrent_trades": bot.get_max_concurrent_trades(),
                "status_msg": bot.status_msg,
                "active_trade": trades_list[0].to_dict() if trades_list else None,
                "active_trades": [t.to_dict() for t in trades_list],
                "active_grid": grid_dict,
                "last_closed_trade": last_closed,
                "stats": stats,
                "settings": bot.settings,
                "radar_telemetry": telemetry,
                "real_grid": grid_stats,
                "events": events,
                "btc_context": update_btc_context(),
                "recent_autopsies": autopsies,
                "buda_sim": buda_sim,
                "carry_sim": carry_sim
            }
            self.wfile.write(json.dumps(payload).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/settings":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                data = json.loads(body)
                if self.bot:
                    self.bot.update_settings(data)
                    current_settings = self.bot.settings
                else:
                    current_settings = {}
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "settings": current_settings}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


def start_swing_dashboard(bot, port: int = SWING_HTTP_PORT, host: str = "0.0.0.0") -> Tuple[http.server.ThreadingHTTPServer, threading.Thread]:
    """Inicia el servidor HTTP dashboard en segundo plano."""
    class CustomHandler(SwingHTTPRequestHandler):
        pass
    CustomHandler.bot = bot

    server = http.server.ThreadingHTTPServer((host, port), CustomHandler)
    actual_port = server.server_address[1]
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    print(f"  🌐 [SWING & GRID DASHBOARD] Acceso en vivo: http://localhost:{actual_port}", flush=True)
    return server, th
