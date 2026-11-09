"""
pionex_bridge.py — Puente y Adaptador de Ejecución Institucional para Pionex Spot API

Proporciona los puntos de unión directos para migrar de Paper Trading a Cuenta Real en Pionex:
- Autenticación HMAC-SHA256 estándar de Pionex.
- Formateo de símbolos (ej. SAND/USDT -> SAND_USDT).
- Consulta de saldos y efectivo libre en USDT para Interés Compuesto.
- Creación, cancelación y consulta de órdenes límite de compra/venta para mallas.
- Modo Dry-Run / Simulado de seguridad para pruebas pre-vuelo sin riesgo.
"""

import os
import sys
import time
import hmac
import hashlib
import json
import urllib.parse
from typing import Dict, List, Optional, Tuple, Any
import requests
from dotenv import load_dotenv

load_dotenv()

PIONEX_API_BASE = "https://api.pionex.com"


class PionexBridge:
    """
    Cliente de interfaz para Pionex Spot API.
    Documentación oficial: https://pionex-doc.gitbook.io/apidocs/
    """

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, dry_run: bool = False):
        self.api_key = api_key or os.environ.get("PIONEX_API_KEY", "")
        self.api_secret = api_secret or os.environ.get("PIONEX_API_SECRET", "")
        self.dry_run = dry_run or (not self.api_key or not self.api_secret)
        self.base_url = PIONEX_API_BASE
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "QuantitativeGridBot/12.0",
            "Content-Type": "application/json"
        })

    @staticmethod
    def format_symbol(symbol: str) -> str:
        """Convierte formatos como 'SAND/USDT' o 'SANDUSDT' al estándar de Pionex 'SAND_USDT'."""
        clean = symbol.replace("/", "_").replace("-", "_").upper()
        if "_" not in clean and clean.endswith("USDT"):
            base = clean[:-4]
            return f"{base}_USDT"
        return clean

    def _generate_signature(self, path: str, params_or_body: str = "") -> str:
        """Genera firma HMAC-SHA256 requerida por Pionex API."""
        if not self.api_secret:
            return ""
        message = f"{path}?{params_or_body}" if params_or_body else path
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return signature

    def _request(self, method: str, endpoint: str, params: Optional[Dict] = None, data: Optional[Dict] = None) -> Dict[str, Any]:
        """Envía una petición firmada a la API de Pionex con manejo de errores y timeouts."""
        if self.dry_run and not (self.api_key and self.api_secret):
            return {"result": False, "code": "DRY_RUN", "message": "PionexBridge en modo simulado (sin credenciales activas)"}

        url = f"{self.base_url}{endpoint}"
        ts = int(time.time() * 1000)

        req_params = dict(params or {})
        req_params["timestamp"] = ts

        # Ordenar parámetros alfabéticamente para firma
        sorted_qs = urllib.parse.urlencode(sorted(req_params.items()))
        
        signature = self._generate_signature(endpoint, sorted_qs)
        headers = {
            "PIONEX-KEY": self.api_key,
            "PIONEX-SIGNATURE": signature
        }

        try:
            if method.upper() == "GET":
                resp = self.session.get(url, params=req_params, headers=headers, timeout=10)
            elif method.upper() == "POST":
                # Para POST, Pionex firma la query string con timestamp y envía JSON body
                resp = self.session.post(url, params=req_params, json=data or {}, headers=headers, timeout=10)
            elif method.upper() == "DELETE":
                resp = self.session.delete(url, params=req_params, headers=headers, timeout=10)
            else:
                return {"result": False, "message": f"Método HTTP no soportado: {method}"}

            if resp.status_code == 200:
                return resp.json()
            else:
                return {
                    "result": False,
                    "status_code": resp.status_code,
                    "error": resp.text
                }
        except Exception as e:
            return {"result": False, "error": str(e)}

    # ==================== PUNTOS DE UNIÓN PÚBLICOS ====================

    def test_connection(self) -> Dict[str, Any]:
        """Verifica la conectividad y validez de las credenciales con Pionex."""
        if not self.api_key or not self.api_secret:
            return {
                "connected": False,
                "status": "SIN_CONFIGURAR",
                "message": "Credenciales PIONEX_API_KEY o PIONEX_API_SECRET no configuradas en el archivo .env"
            }
        
        res = self._request("GET", "/api/v1/account/balances")
        if res.get("result"):
            return {
                "connected": True,
                "status": "CONECTADO",
                "message": "Conexión autenticada con éxito a Pionex Spot API"
            }
        return {
            "connected": False,
            "status": "ERROR_AUTENTICACION",
            "message": res.get("message") or res.get("error", "Error desconocido")
        }

    def get_balances(self) -> Dict[str, Dict[str, float]]:
        """
        Retorna los balances disponibles por activo.
        Formato de salida: {'USDT': {'free': 80.0, 'frozen': 0.0}, ...}
        """
        if self.dry_run:
            # En modo simulado, retorna estructura vacía
            return {}

        res = self._request("GET", "/api/v1/account/balances")
        balances = {}
        if res.get("result"):
            for item in res.get("data", {}).get("balances", []):
                coin = item.get("coin", "")
                free = float(item.get("free", 0.0))
                frozen = float(item.get("frozen", 0.0))
                balances[coin] = {"free": free, "frozen": frozen}
        return balances

    def get_usdt_free(self) -> float:
        """Obtiene el saldo líquido en USDT disponible para reinversión (Interés Compuesto)."""
        balances = self.get_balances()
        return balances.get("USDT", {}).get("free", 0.0)

    def place_limit_order(self, symbol: str, side: str, price: float, size: float) -> Dict[str, Any]:
        """
        Coloca una orden LÍMITE en Pionex Spot:
        - symbol: 'SAND/USDT' o 'SAND_USDT'
        - side: 'BUY' o 'SELL'
        - price: Precio límite exacto
        - size: Cantidad de tokens
        """
        pionex_symbol = self.format_symbol(symbol)
        side_clean = side.upper()

        if self.dry_run:
            mock_id = f"mock_{int(time.time() * 1000)}"
            return {
                "result": True,
                "dry_run": True,
                "order_id": mock_id,
                "symbol": pionex_symbol,
                "side": side_clean,
                "price": price,
                "size": size,
                "message": f"[DRY-RUN] Orden simulada {side_clean} de {size} {pionex_symbol} a ${price:.6f}"
            }

        payload = {
            "symbol": pionex_symbol,
            "side": side_clean,
            "type": "LIMIT",
            "size": str(round(size, 6)),
            "price": str(round(price, 6))
        }

        res = self._request("POST", "/api/v1/trade/order", data=payload)
        return res

    def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """Cancela una orden activa específica por su ID."""
        pionex_symbol = self.format_symbol(symbol)
        if self.dry_run:
            return {"result": True, "dry_run": True, "order_id": order_id, "message": "Orden cancelada (simulación)"}

        params = {
            "symbol": pionex_symbol,
            "orderId": order_id
        }
        return self._request("DELETE", "/api/v1/trade/order", params=params)

    def cancel_all_orders(self, symbol: str) -> Dict[str, Any]:
        """Cancela todas las órdenes abiertas de un par (usado en Victoria Total / Cosecha)."""
        pionex_symbol = self.format_symbol(symbol)
        if self.dry_run:
            return {"result": True, "dry_run": True, "symbol": pionex_symbol, "message": "Todas las órdenes canceladas (simulación)"}

        params = {"symbol": pionex_symbol}
        return self._request("DELETE", "/api/v1/trade/allOrders", params=params)

    def get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """Obtiene la lista de órdenes límite vivas en Pionex para un símbolo."""
        pionex_symbol = self.format_symbol(symbol)
        if self.dry_run:
            return []

        params = {"symbol": pionex_symbol}
        res = self._request("GET", "/api/v1/trade/openOrders", params=params)
        if res.get("result"):
            return res.get("data", {}).get("orders", [])
        return []


# Instancia por defecto lista para integración
pionex_client = PionexBridge()


if __name__ == "__main__":
    print("=== Comprobación de Diagnóstico Pionex Bridge ===")
    status = pionex_client.test_connection()
    print(f"Estado de Conexión: {status['status']}")
    print(f"Mensaje: {status['message']}")
    print(f"Modo Dry-Run Activo: {pionex_client.dry_run}")
    print(f"Ejemplo conversión de símbolo: 'SAND/USDT' -> '{PionexBridge.format_symbol('SAND/USDT')}'")
