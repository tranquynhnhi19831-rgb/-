Write-Host "并行启动后端和前端..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList '-ExecutionPolicy Bypass -File .\scripts\start_backend.ps1'
Start-Process powershell -ArgumentList '-ExecutionPolicy Bypass -File .\scripts\start_frontend.ps1'
Write-Host "已启动。请打开 http://127.0.0.1:5173" -ForegroundColor Green
