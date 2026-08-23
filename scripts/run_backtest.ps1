[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$Symbol = "BTC/USDT",
    [string]$Start = "2025-01-01",
    [string]$End = "2025-12-31"
)

$ErrorActionPreference = "Stop"
$body = @{
    symbol = $Symbol
    start = $Start
    end = $End
} | ConvertTo-Json -Compress

Write-Host "Calling backtest API: $BaseUrl/api/backtest/run" -ForegroundColor Cyan
Invoke-RestMethod `
    -Method Post `
    -Uri "$BaseUrl/api/backtest/run" `
    -ContentType "application/json" `
    -Body $body
