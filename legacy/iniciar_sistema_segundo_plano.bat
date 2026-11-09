@echo off
title 🟢 BOT GROK - SISTEMA EN VIVO 24/7
color 0A
chcp 65001 > nul
cd /d "%~dp0"

powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*master_daemon.py*' -or $_.CommandLine -like '*hourly_swing_agent.py*' -or $_.CommandLine -like '*buda_market_maker_sim.py*' -or $_.CommandLine -like '*cash_carry_sim.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

echo ================================================================================
echo    🟢 BOT GROK: INICIANDO SISTEMA MULTI-PILAR 24/7
echo ================================================================================
echo  * Se abrirá automáticamente el Dashboard en tu navegador: http://localhost:8900
echo  * Se activará el icono verde '$' en tu barra de tareas (junto al reloj).
echo  * Esta ventana te mostrará los latidos de telemetría en tiempo real.
echo  * Puedes minimizar esta ventana; el bot seguirá operando 24/7 de forma autónoma.
echo ================================================================================
echo.

py -3.12 master_daemon.py

pause
