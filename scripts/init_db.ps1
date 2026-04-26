Write-Host "初始化 SQLite 数据库 backend/data/trading.db ..." -ForegroundColor Cyan
.\.venv\Scripts\python.exe .\backend\init_db.py
Write-Host "数据库初始化完成。" -ForegroundColor Green
