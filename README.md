# jianghe-quant-system

面向 Binance USDT-M 的江河交易逻辑量化系统。目标是把“势 / 位 / 态 / 动、突破、回调、二推失败”等主观 Price Action 规则逐步翻译为可回测、可审计、可部署的交易系统。

> 当前阶段：**S1 基础设施与安全边界**。尚未加入真实 Binance 下单路径，默认只允许 dry-run / testnet 验证。

## 当前技术栈

- 后端：Python + FastAPI + SQLAlchemy + SQLite（开发期）
- 交易所适配：CCXT + Binance USDT-M
- 前端：React + Vite + TypeScript + Tailwind
- 测试：pytest + GitHub Actions
- 目标部署：GitHub → Tencent Cloud

## S1 已完成

### Binance 执行前校验

`backend/exchange/binance_client.py` 当前支持：

- Binance USDT-M testnet / sandbox；
- `BTC/USDT` → `BTC/USDT:USDT` 合约符号解析；
- 市场规则读取；
- `MARKET_LOT_SIZE / LOT_SIZE` 最小数量与步进校验；
- `MIN_NOTIONAL / NOTIONAL` 最小名义价值校验；
- 按交易所精度生成合法订单数量；
- **订单预览**（只计算，不下单）。

预览接口：

```text
POST /api/config/binance-order-preview
```

示例：

```json
{
  "symbol": "BTC/USDT",
  "target_notional_usdt": 10
}
```

返回结果包含 `places_order: false`，S1 不允许通过该接口下单。

## 100U 小账户风控基线

当前参数是安全起点，不是收益最优参数；后续必须由回测、Paper 和 Testnet 结果决定是否修改。

- 参考启动资金：100 USDT
- 默认单笔风险：0.5%（0.5U / 100U）
- 单笔风险硬上限：1%
- 默认日亏损上限：2%
- 日亏损硬上限：3%
- 默认最大杠杆：3x
- 系统硬杠杆上限：5x
- 保证金模式：仅 isolated
- 同时最多 1 个持仓
- 连亏 3 笔停止继续开新仓

## 两个 API 服务：交易端与展示端隔离

### 1. 管理 / 交易 API

入口：`backend/main.py`

包含配置、回测、Start/Stop 等管理能力。生产部署时不应直接暴露到公网。

本地启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_backend.ps1
```

默认：`http://127.0.0.1:8000`

### 2. Public Read-Only API

入口：`backend/public_main.py`

这个 FastAPI 应用**没有注册**配置、启动、停止、回测或下单路由，只包含：

```text
GET /api/public/health
GET /api/public/snapshot
```

本地启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_public_dashboard.ps1
```

默认：`http://127.0.0.1:8001`

未来腾讯云只把这个服务暴露给展示网站；管理/交易 API 保持内网或 loopback 可访问。

## 实时展示盘

前端路由：

```text
/live
```

展示：

- 初始资金；
- 当前权益；
- 累计收益率；
- 当前仓位；
- 买入/开仓价格；
- 标记价格；
- 数量与仓位价值；
- 杠杆；
- 未实现盈亏；
- 最近交易；
- 手续费；
- 胜率；
- 策略理由。

`/live` 不显示 Dashboard / Settings / Start / Stop 导航。生产环境配合 `backend.public_main` 后，公开链接在 API 层也不具备交易操作能力。

## 本地开发

安装后端和前端依赖：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\init_db.ps1
```

启动管理 API：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_backend.ps1
```

启动只读 Public API：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_public_dashboard.ps1
```

启动前端：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_frontend.ps1
```

管理界面：`http://127.0.0.1:5173/`

只读展示盘：`http://127.0.0.1:5173/live`

## 测试 / CI

本地：

```powershell
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

GitHub Actions 会执行：

1. 安装 Python 3.12 依赖；
2. smoke import 管理 API 与 Public API；
3. pytest；
4. Node 20 前端 TypeScript/Vite build。

## API Key 安全原则

- Binance Key 永远不能写进 GitHub；
- 交易 Key 禁止开启提现权限；
- 未来 Live Key 应绑定腾讯云服务器固定 IP；
- Public API / `/live` 不读取或返回 Binance Secret；
- Public API 不提供 BUY / SELL / CLOSE / START / STOP / CONFIG 路由；
- S1 仍然没有真实下单执行路径。

## 开发阶段

```text
S1  Binance 规则 + 100U 风控 + Read-Only 展示盘   ← 当前
S2  江河 Market Structure / Strength Engine
S3  Trend Pullback Continuation
S4  Breakout Continuation
S5  Second-Push Failure
S6  回测 + 手续费/滑点/资金费率 + 消融测试
S7  Binance Testnet 订单状态机
S8  100U Live（通过全部上线门槛后才允许）
S9  Tencent Cloud + HTTPS + GitHub CI/CD
```

## 风险提示

量化交易可能产生实际亏损，历史回测、模拟盘和 Testnet 表现均不能保证实盘收益。项目的第一目标是验证策略与系统可靠性，而不是通过提高杠杆放大 100U 账户的短期收益。
