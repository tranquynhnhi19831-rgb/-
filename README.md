# binance-deepseek-n-trading-bot

一个可在 **VSCode 一站式运行** 的本地量化交易系统示例：
- 后端：FastAPI + SQLite + SQLAlchemy
- 前端：React + Vite + TypeScript + Tailwind + Recharts
- 默认：**dry-run=true**、**testnet=true**（防止误实盘）

---

## 1. 项目说明
本项目用于演示 Binance USDT-M 合约量化系统完整流程：配置、风控、策略、回测、可视化与日志。

## 2. 风险提示（非常重要）
- 量化交易存在高风险，**不保证收益**。
- 默认仅建议在 dry-run/testnet 模式使用。
- API Key 请只开读取与交易，**禁止开启提现权限**。

## 3. 20U 本金风险说明
20U 本金波动容忍度极低，系统默认采用极保守风控：
- 单笔风险 <= 1%
- 杠杆 <= 5（默认 1）
- 单日最多 3 笔交易
- 同时最多 1 持仓
- 连亏 3 笔自动暂停
- 日亏损达到 3% 自动停止

## 4. VSCode 使用方法（Windows PowerShell）
```powershell
cd 项目路径
code .
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\init_db.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start_backend.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start_frontend.ps1
```
打开浏览器：`http://127.0.0.1:5173`

## 5. 新手从 0 到 1 运行步骤
1. 打开 VSCode 项目目录。
2. 运行 `setup.ps1` 自动创建虚拟环境并安装依赖。
3. 运行 `init_db.ps1` 自动创建 `backend/data/trading.db`。
4. 运行 `start_backend.ps1` 启动后端。
5. 运行 `start_frontend.ps1` 启动前端。
6. 打开网页进入 Settings 填写 Binance/DeepSeek API。
7. 保持 `testnet=true`、`dry_run=true`，点击保存。
8. 到 Dashboard 点击“启动交易系统”。

## 6. 脚本清单
- `scripts/setup.ps1`：安装后端与前端依赖。
- `scripts/init_db.ps1`：初始化 SQLite 数据库。
- `scripts/start_backend.ps1`：启动 FastAPI。
- `scripts/start_frontend.ps1`：启动 React。
- `scripts/start_all.ps1`：同时启动前后端。
- `scripts/run_backtest.ps1`：调用回测接口。
- `scripts/stop_help.ps1`：显示停止系统方法。

## 7. 如何保持 dry-run + testnet
- Settings 页面中勾选 `dry-run`、`testnet`。
- 只有关闭 testnet、关闭 dry-run、并勾选 live 二次确认才允许 live 请求。

## 8. 如何停止系统
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop_help.ps1
```
或在启动终端按 `Ctrl + C`。

## 9. 如何查看交易记录
- 前端 Trades 页面查看交易历史。
- Dashboard 页面查看最近交易、风控记录、日志。
- 数据库文件：`backend/data/trading.db`（可用 DB Browser for SQLite 打开）。

## 10. 常见错误
1. `python` 命令不存在：安装 Python 3.11+ 并勾选 PATH。
2. `npm` 命令不存在：安装 Node.js 18+。
3. 端口占用：改 `start_backend.ps1` 或 `start_frontend.ps1` 端口。
4. Binance/DeepSeek 连通失败：先检查网络与 API Key 权限。

## 11. API 列表
- GET `/api/status`
- POST `/api/start`
- POST `/api/stop`
- GET `/api/config`
- POST `/api/config`
- POST `/api/config/test-binance`
- POST `/api/config/test-deepseek`
- GET `/api/account`
- GET `/api/positions`
- GET `/api/trades`
- GET `/api/signals`
- GET `/api/logs`
- GET `/api/risk-events`
- POST `/api/backtest/run`
- WebSocket `/ws/dashboard`
