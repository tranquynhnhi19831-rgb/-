# binance-deepseek-n-trading-bot

本项目是 **VSCode 一站式本地量化系统**：
- 后端：FastAPI + SQLite + SQLAlchemy + WebSocket + ccxt(Binance USDT-M)
- 前端：React + Vite + TypeScript + Tailwind + Recharts
- 默认安全：`dry_run=true`、`testnet=true`、逐仓、低风险。

## 风险提示
- 量化交易有亏损风险，20U 本金非常脆弱。
- 默认仅建议 dry-run + testnet。
- API Key **禁止开启提现权限**，只开读取和交易。

## Windows PowerShell 一键运行
```powershell
cd 项目路径
code .
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\init_db.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start_backend.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start_frontend.ps1
```
访问：`http://127.0.0.1:5173`

## 关键脚本
- `scripts/setup.ps1`：创建 `.venv`、安装后端/前端依赖。
- `scripts/init_db.ps1`：创建 `backend/data/trading.db` + 自动建表。
- `scripts/start_backend.ps1`：进入 `backend/` 后执行 `uvicorn main:app`。
- `scripts/start_frontend.ps1`：启动 Vite。
- `scripts/start_all.ps1`：并行启动前后端。
- `scripts/run_backtest.ps1`：调用真实行情回测接口。
- `scripts/stop_help.ps1`：查看停止方法。

## 新手操作流程
1. 先运行 `setup.ps1`。
2. 运行 `init_db.ps1`。
3. 启动后端与前端。
4. 打开网页 Settings 页面填写 Binance / DeepSeek Key。
5. 默认保持 `dry-run=true` + `testnet=true`。
6. 去 Dashboard 点击“启动交易系统”。

## 配置安全逻辑
- `GET /api/config` 不返回真实 key，也不返回脱敏 key。
- 仅返回 `has_binance_api_key/has_binance_secret/has_deepseek_api_key`。
- 输入框默认空；如已保存会显示“已保存，如需修改请重新输入”。
- `POST /api/config`：空 key 不覆盖已有 key。

## 交易与回测
- 实时交易引擎：后台循环（默认每 60 秒一次），可 start/stop，异常阈值自动停止。
- 行情：仅使用 Binance USDT-M Futures 真实 K 线（1h + 15m）。
- 回测：真实历史 K 线 + N 型信号 + 止损止盈撮合 + 手续费扣减 + 最大回撤/胜率/盈亏比。

## API 清单
- GET `/api/status`
- POST `/api/start`
- POST `/api/stop`
- GET `/api/config`
- POST `/api/config`
- POST `/api/config/test-binance`
- POST `/api/config/test-deepseek`
- GET `/api/account`
- GET `/api/positions`
- GET `/api/open-orders`
- GET `/api/trades`
- GET `/api/signals`
- GET `/api/logs`
- GET `/api/risk-events`
- POST `/api/backtest/run`
- WebSocket `/ws/dashboard`

## 常见问题
1. `python` 不存在：安装 Python 3.11+。
2. `npm` 不存在：安装 Node.js 18+。
3. 依赖安装失败：检查网络与代理配置。
4. API 连接失败：检查 Key 权限和 testnet 设置。
