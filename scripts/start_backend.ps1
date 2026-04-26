Write-Host "启动 FastAPI 后端 (http://127.0.0.1:8000) ..." -ForegroundColor Cyan
Push-Location .\backend
..\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
Pop-Location
