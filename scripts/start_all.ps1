$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendScript = Join-Path $PSScriptRoot "start_backend.ps1"
$publicScript = Join-Path $PSScriptRoot "start_public_dashboard.ps1"
$frontendScript = Join-Path $PSScriptRoot "start_frontend.ps1"

Write-Host "Starting local Paper stack in three terminals..." -ForegroundColor Cyan
Write-Host "Private/Admin API : http://127.0.0.1:8000" -ForegroundColor DarkGray
Write-Host "Public Read-Only  : http://127.0.0.1:8001" -ForegroundColor DarkGray
Write-Host "Frontend          : http://localhost:5173" -ForegroundColor DarkGray

Start-Process powershell.exe -WorkingDirectory $repoRoot -ArgumentList "-NoExit -ExecutionPolicy Bypass -File `"$backendScript`""
Start-Process powershell.exe -WorkingDirectory $repoRoot -ArgumentList "-NoExit -ExecutionPolicy Bypass -File `"$publicScript`""
Start-Process powershell.exe -WorkingDirectory $repoRoot -ArgumentList "-NoExit -ExecutionPolicy Bypass -File `"$frontendScript`""

Write-Host "Started. Open http://localhost:5173/live for the read-only board." -ForegroundColor Green
Write-Host "Binance Demo credentials are intentionally NOT loaded by start_all.ps1." -ForegroundColor Yellow
