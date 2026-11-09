"""
Lanzador Desacoplado 100% Independiente del Sistema de Trading (Windows OS).
Inicia los 3 motores (Swing Sniper, Buda Market Maker, Cash & Carry) con
banderas DETACHED_PROCESS y CREATE_NEW_PROCESS_GROUP para que sigan corriendo
24/7 en segundo plano aunque Antigravity, la terminal o la sesión se cierren.
"""
import os
import sys
import subprocess
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "swing_logs", "paper")
os.makedirs(LOGS_DIR, exist_ok=True)

PYTHON_EXE = sys.executable

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
CREATION_FLAGS = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB

MODULES = [
    ("hourly_swing_agent.py", os.path.join(LOGS_DIR, "swing_daemon.log")),
    ("buda_market_maker_sim.py", os.path.join(LOGS_DIR, "buda_daemon.log")),
    ("cash_carry_sim.py", os.path.join(LOGS_DIR, "carry_daemon.log")),
]

def launch_all():
    print("=" * 80)
    print("INICIANDO MOTORES DE TRADING TOTALMENTE INDEPENDIENTES (WINDOWS BACKGROUND)")
    print("=" * 80)
    
    pids = []
    for script_name, log_file in MODULES:
        script_path = os.path.join(BASE_DIR, script_name)
        log_handle = open(log_file, "a", encoding="utf-8")
        
        proc = subprocess.Popen(
            [PYTHON_EXE, "-u", script_path],
            cwd=BASE_DIR,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=CREATION_FLAGS,
            close_fds=False
        )
        pids.append((script_name, proc.pid))
        print(f" [OK] {script_name} lanzado en segundo plano con PID: {proc.pid}")

    print("-" * 80)
    print("Esperando 3 segundos para confirmar estabilidad...")
    time.sleep(3)
    
    print("\nTodos los procesos han quedado desacoplados a nivel de sistema operativo.")
    print("Puedes cerrar Antigravity o usarlo en otra cosa sin que los robots se detengan.")
    print("Dashboard en vivo: http://localhost:8900")
    print("=" * 80)

if __name__ == "__main__":
    launch_all()
