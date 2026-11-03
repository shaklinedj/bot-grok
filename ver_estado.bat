@echo off
title Estado del Sistema de Trading
chcp 65001 > nul
cd /d "%~dp0"

echo ================================================================================
echo    ESTADO DE PROCESOS ACTIVOS EN SEGUNDO PLANO
echo ================================================================================
echo.

powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*hourly_swing_agent.py*' -or $_.CommandLine -like '*buda_market_maker_sim.py*' -or $_.CommandLine -like '*cash_carry_sim.py*' } | Select-Object ProcessId, CreationDate, CommandLine | Format-Table -AutoSize"

echo.
echo ================================================================================
echo    VERIFICANDO ACCESO HTTP AL DASHBOARD (http://localhost:8900)
echo ================================================================================
powershell -Command "try { $r = Invoke-WebRequest -Uri 'http://localhost:8900/api/status' -TimeoutSec 3 -UseBasicParsing; Write-Host ('[ONLINE] Dashboard respondiendo OK (Status 200)') -ForegroundColor Green } catch { Write-Host ('[OFFLINE] Dashboard no responde') -ForegroundColor Red }"
echo.
pause
