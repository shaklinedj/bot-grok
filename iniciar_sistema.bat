@echo off
title Sistema Bot Grok 24/7
chcp 65001 > nul
cd /d "%~dp0"

echo ================================================================================
echo    INICIANDO SUPERVISOR MAESTRO BOT GROK 24/7
echo ================================================================================
echo.

rem 1. Detener instancias previas limpiamente
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*master_daemon.py*' -or $_.CommandLine -like '*hourly_swing_agent.py*' -or $_.CommandLine -like '*buda_market_maker_sim.py*' -or $_.CommandLine -like '*cash_carry_sim.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" > nul 2>&1

rem 2. Detectar interprete Python 3.12
set "PY_EXE="
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
) else (
    set "PY_EXE=py -3.12"
)

echo [OK] Interprete: %PY_EXE%
echo [OK] Lanzando Supervisor Maestro...
echo.
"%PY_EXE%" master_daemon.py
