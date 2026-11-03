@echo off
title Detener Sistema de Trading
chcp 65001 > nul
cd /d "%~dp0"

echo ================================================================================
echo    DETENIENDO SISTEMA DE TRADING EN SEGUNDO PLANO
echo ================================================================================
echo.

powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*hourly_swing_agent.py*' -or $_.CommandLine -like '*buda_market_maker_sim.py*' -or $_.CommandLine -like '*cash_carry_sim.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('[OK] Proceso detenido PID ' + $_.ProcessId + ': ' + $_.Name) }"

echo.
echo ================================================================================
echo    TODOS LOS PROCESOS DEL BOT HAN SIDO DETENIDOS EXITOSAMENTE
echo ================================================================================
echo.
pause
