"""
Paquete de Gestión de Riesgo, Salidas y Aprendizaje Adaptativo.
"""
from risk.risk_manager import manage_active_swing_trade
from risk.adaptive import process_trade_autopsy_and_feedback, calculate_decaying_learning_rate

__all__ = [
    "manage_active_swing_trade",
    "process_trade_autopsy_and_feedback",
    "calculate_decaying_learning_rate"
]
