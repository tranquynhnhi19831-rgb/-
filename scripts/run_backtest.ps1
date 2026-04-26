Write-Host "调用后端回测接口..." -ForegroundColor Cyan
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/backtest/run -ContentType 'application/json' -Body '{"symbol":"BTC/USDT","start":"2025-01-01","end":"2025-12-31"}'
