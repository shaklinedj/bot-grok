"""
Paquete de Servidor Web y API REST para Dashboard y Terminal Cuántica.
"""
from server.routes import SwingHTTPRequestHandler, start_swing_dashboard
from server.templates import DASHBOARD_HTML

__all__ = [
    "SwingHTTPRequestHandler",
    "start_swing_dashboard",
    "DASHBOARD_HTML"
]
