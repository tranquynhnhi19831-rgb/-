Write-Host "启动 FastAPI 后端 (http://127.0.0.1:8000) ..." -ForegroundColor Cyan
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
