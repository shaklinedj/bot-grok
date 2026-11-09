# ===============================================================================
# start_bot.ps1 — Script de PowerShell para levantar el Bot Cuantitativo v12
# Uso:
#   .\start_bot.ps1            -> Inicia normalmente
#   .\start_bot.ps1 -Reset     -> Inicia reseteando el capital a $80 USDT
#   .\start_bot.ps1 -NoBrowser -> Inicia sin abrir el navegador automáticamente
# ===============================================================================

param (
    [switch]$Reset,
    [switch]$NoBrowser
)

$Host.UI.RawUI.WindowTitle = "Bot Cuantitativo v12 - Pionex / Binance Grid"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host "    INICIANDO BOT CUANTITATIVO SPOT NEUTRAL GRID v12 (PIONEX/BINANCE)          " -ForegroundColor Yellow
Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Detección de Python
$PythonCmd = "python"
if (Get-Command "py" -ErrorAction SilentlyContinue) {
    $PythonCmd = "py -3.12"
} elseif (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] No se encontró Python en el PATH del sistema." -ForegroundColor Red
    exit 1
}

Write-Host "[1/3] Usando intérprete: $PythonCmd" -ForegroundColor Green

# 2. Abrir navegador
if (-not $NoBrowser) {
    Write-Host "[2/3] Programando apertura del Dashboard en http://localhost:8888..." -ForegroundColor Magenta
    Start-Job -ScriptBlock { Start-Sleep -Seconds 2; Start-Process "http://localhost:8888" } | Out-Null
} else {
    Write-Host "[2/3] Dashboard disponible en http://localhost:8888" -ForegroundColor DarkGray
}

# 3. Argumentos adicionales
$ArgsList = @("-u", "paper_trading_agent.py")
if ($Reset) {
    $ArgsList += "--reset"
    Write-Host "⚠️ MODO RESET ACTIVO: Reiniciando capital a `$80.00 USDT..." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[3/3] Ejecutando bot en tiempo real... (Ctrl+C para salir)" -ForegroundColor Cyan
Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host ""

if ($PythonCmd -eq "py -3.12") {
    & py -3.12 @ArgsList
} else {
    & python @ArgsList
}
