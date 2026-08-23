Write-Host "启动管理/交易 FastAPI 后端 (http://127.0.0.1:8000) ..." -ForegroundColor Cyan
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
