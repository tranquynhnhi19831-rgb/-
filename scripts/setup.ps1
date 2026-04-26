Write-Host "[1/4] 创建 Python 虚拟环境..." -ForegroundColor Cyan
if (!(Test-Path .venv)) { python -m venv .venv }

Write-Host "[2/4] 安装后端依赖..." -ForegroundColor Cyan
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt

Write-Host "[3/4] 安装前端依赖..." -ForegroundColor Cyan
Push-Location .\frontend
npm install
Pop-Location

Write-Host "[4/4] 完成。" -ForegroundColor Green
Write-Host "接下来可运行: .\scripts\init_db.ps1" -ForegroundColor Yellow
