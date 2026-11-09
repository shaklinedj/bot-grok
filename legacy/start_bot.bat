@echo off
chcp 65001 >nul
title Bot Cuantitativo v12 - Pionex / Binance Grid Agent

echo ===============================================================================
echo     INICIANDO BOT CUANTITATIVO SPOT NEUTRAL GRID v12
echo ===============================================================================
echo.
echo  [1/3] Verificando entorno de Python...

:: Detectar py launcher o python
set PYTHON_CMD=
py -3.12 --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set PYTHON_CMD=py -3.12
) else (
    python --version >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        set PYTHON_CMD=python
    ) else (
        echo  [ERROR] No se encontro Python instalado en el sistema.
        echo  Instala Python 3.11 o 3.12 y vuelve a ejecutar este script.
        pause
        exit /b 1
    )
)

echo  [OK] Usando interprete: %PYTHON_CMD%
echo.
echo  [2/3] Programando apertura del Dashboard en tu navegador (http://localhost:8888)...
start "" cmd /c "timeout /t 2 >nul & start http://localhost:8888"

echo.
echo  [3/3] Ejecutando Paper Trading Agent en vivo...
echo  Presiona Ctrl+C en cualquier momento para detener el bot con seguridad.
echo ===============================================================================
echo.

:LOOP
%PYTHON_CMD% -u paper_trading_agent.py %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [AVISO] El proceso se detuvo con codigo %ERRORLEVEL%.
    echo  Reiniciando en 5 segundos... (Presiona Ctrl+C para cancelar)
    timeout /t 5 >nul
    goto LOOP
)

echo.
echo  [INFO] Bot detenido limpiamente.
pause
