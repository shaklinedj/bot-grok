"""
SUPERVISOR MAESTRO 24/7 CON BANDEJA DEL SISTEMA (TRAY ICON) & CONSOLA EN VIVO
Ejecuta, supervisa y muestra el estado en tiempo real del sistema de trading:
  - Icono verde activo en la bandeja de Windows (junto al reloj).
  - Consola visible con latidos de telemetría en tiempo real.
  - Menú contextual para abrir el dashboard o detener el sistema.
"""
import os
import sys
import time
import subprocess
import threading
import webbrowser
import ctypes
import socket

# Configurar encoding UTF-8 en consola Windows para evitar UnicodeEncodeError con emojis
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from datetime import datetime
from PIL import Image, ImageDraw
import pystray

MASTER_LOCK_PORT = 48901
_lock_socket = None

def ensure_single_instance():
    """Garantiza que no existan dos instancias del supervisor maestro corriendo a la vez."""
    global _lock_socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", MASTER_LOCK_PORT))
        s.listen(1)
        _lock_socket = s
        return True
    except OSError:
        print("\n" + "=" * 70)
        print("  ⚠️ [INSTANCIA DUPLICADA DETECTADA]")
        print("  Ya existe un Supervisor Maestro 24/7 corriendo en este equipo.")
        print("  Revisa tu barra de tareas (junto al reloj) o abre: http://localhost:8900")
        print("=" * 70 + "\n")
        time.sleep(3)
        sys.exit(0)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "swing_logs", "paper")
os.makedirs(LOGS_DIR, exist_ok=True)

PYTHON_EXE = sys.executable
ICON_PATH = os.path.join(BASE_DIR, "tray_icon.png")

SERVICES = [
    {
        "name": "Pilar 1: Swing Sniper & Dashboard",
        "script": "hourly_swing_agent.py",
        "log": os.path.join(LOGS_DIR, "swing_daemon.log")
    },
    {
        "name": "Pilar 2: Buda Market Maker Pasivo",
        "script": "buda_market_maker_sim.py",
        "log": os.path.join(LOGS_DIR, "buda_daemon.log")
    },
    {
        "name": "Pilar 3: Binance Cash & Carry",
        "script": "cash_carry_sim.py",
        "log": os.path.join(LOGS_DIR, "carry_daemon.log")
    }
]

global_tray = None
is_running = True
processes = {}

def create_icon_image():
    """Genera o carga el icono verde de estado para la barra de tareas."""
    if os.path.exists(ICON_PATH):
        try:
            return Image.open(ICON_PATH)
        except Exception:
            pass
    img = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=(16, 185, 129), outline=(5, 150, 105), width=3)
    d.text((22, 16), "$", fill=(255, 255, 255), font_size=32)
    return img

def open_dashboard(icon=None, item=None):
    webbrowser.open("http://localhost:8900")

def stop_all(icon=None, item=None):
    global is_running, global_tray
    print("\n[STOP] Deteniendo todos los motores del bot...", flush=True)
    is_running = False
    for name, p in processes.items():
        try:
            p.terminate()
        except Exception:
            pass
    if global_tray:
        global_tray.stop()
    sys.exit(0)

def setup_tray_icon():
    global global_tray
    img = create_icon_image()
    menu = pystray.Menu(
        pystray.MenuItem("🌐 Abrir Dashboard Web (Puerto 8900)", open_dashboard, default=True),
        pystray.MenuItem("🛑 Detener Bot Grok", stop_all)
    )
    global_tray = pystray.Icon("BotGrok", img, "🟢 Bot Grok 24/7 (Trading Activo)", menu)
    global_tray.run()

def log_master(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}\n"
    sys.stdout.write(line)
    sys.stdout.flush()
    with open(os.path.join(LOGS_DIR, "master_supervisor.log"), "a", encoding="utf-8") as f:
        f.write(line)

def run_supervisor():
    global is_running
    ensure_single_instance()
    try:
        ctypes.windll.kernel32.SetConsoleTitleW("🟢 BOT GROK 24/7 - SISTEMA EN VIVO")
    except Exception:
        pass

    print("=" * 80)
    print("  🟢 BOT GROK - SISTEMA CUANTITATIVO MULTI-PILAR 24/7 EN VIVO")
    print("=" * 80)
    print("  • Dashboard Web:   http://localhost:8900 (Se abrirá automáticamente)")
    print("  • Bandeja Windows: Icono verde '$' activo junto al reloj")
    print("  • Supervisión:     Auto-recuperación activa de caídas o timeouts")
    print("=" * 80 + "\n")

    handles = {}
    for s in SERVICES:
        script_path = os.path.join(BASE_DIR, s["script"])
        log_f = open(s["log"], "a", encoding="utf-8", buffering=1)
        handles[s["script"]] = log_f
        
        p = subprocess.Popen(
            [PYTHON_EXE, "-u", script_path],
            cwd=BASE_DIR,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL
        )
        processes[s["script"]] = p
        log_master(f"✅ {s['name']} -> Activo (PID: {p.pid})")

    # Iniciar icono en la bandeja de tareas en un hilo secundario
    tray_th = threading.Thread(target=setup_tray_icon, daemon=True)
    tray_th.start()
    log_master("🔔 Icono del sistema registrado en la bandeja de Windows.")

    # Abrir el navegador tras 3 segundos
    time.sleep(3.0)
    try:
        webbrowser.open("http://localhost:8900")
        log_master("🌐 Dashboard web abierto en el navegador.")
    except Exception:
        pass

    cycle = 0
    while is_running:
        time.sleep(15)
        cycle += 1
        
        # Verificar estado de cada proceso
        status_strs = []
        for s in SERVICES:
            script = s["script"]
            proc = processes.get(script)
            if proc is not None and proc.poll() is not None:
                code = proc.poll()
                log_master(f"⚠️ [RESTART] {s['name']} cayó (código {code}). Reiniciando...")
                log_f = open(s["log"], "a", encoding="utf-8", buffering=1)
                handles[script] = log_f
                new_p = subprocess.Popen(
                    [PYTHON_EXE, "-u", os.path.join(BASE_DIR, script)],
                    cwd=BASE_DIR,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL
                )
                processes[script] = new_p
                status_strs.append(f"{s['script'][:8]}: RESTART({new_p.pid})")
            else:
                status_strs.append(f"{s['script'][:8]}: OK")

        # Emitir latido de actividad visible en consola SOLO cuando hay cambios o errores,
        # o un latido silencioso cada 20 minutos (80 ciclos x 15s) para no inundar memoria ni logs.
        ts = datetime.now().strftime("%H:%M:%S")
        has_issue = any("RESTART" in st for st in status_strs)
        if has_issue:
            log_master(f"⚠️ [ALERTA PROCESOS] {' | '.join(status_strs)}")
        elif cycle % 80 == 0:
            print(f"[{ts}] 🟢 [SUPERVISOR 24/7] Motores saludables: {' | '.join(status_strs)} | Dashboard: http://localhost:8900", flush=True)

if __name__ == "__main__":
    try:
        run_supervisor()
    except KeyboardInterrupt:
        stop_all()
