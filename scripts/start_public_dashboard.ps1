Write-Host "启动只读展示 API (http://127.0.0.1:8001) ..." -ForegroundColor Cyan
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m uvicorn public_main:app --app-dir backend --reload --host 127.0.0.1 --port 8001
