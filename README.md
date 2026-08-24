# jianghe-quant-system

面向 Binance USDT-M 的江河交易逻辑量化系统。目标是把“势 / 位 / 态 / 动、趋势回调、突破延续、二推失败”等主观 Price Action 规则翻译为可回测、可审计、可验证、可部署的交易系统。

> 当前阶段：**S7.2 Local Paper 已完成核心闭环验收，S7 Binance USD-M Demo 正在做真实 API 联调。**
>
> Local Paper / Demo / 回测结果都不是盈利证明。Mainnet 下单仍不支持。

## 当前系统边界

- 策略：江河三套核心 Setup
  - `TREND_PULLBACK_CONTINUATION`
  - `BREAKOUT_CONTINUATION`
  - `SECOND_PUSH_FAILURE`
- 风控：100U 基线、结构止损、仓位上限、日亏损限制、单日交易次数限制、连续亏损限制、最多 1 个持仓。
- 本地 Paper：确定性场景只用于验证工程闭环，不代表真实行情表现。
- Binance Demo：USD-M Demo Gateway 已实现；Demo 私有凭证只从服务端环境变量读取。
- Mainnet：当前代码没有 Mainnet 下单开关，Demo Gateway 会检查 USD-M REST URL 必须落在 Demo Host。
- Public Dashboard：只读 API 与管理/交易 API 分离，公开展示端无下单、启动、停止、配置能力。

## 已验证的 Local Paper 闭环

```text
江河策略评估
→ 风控
→ 仓位计算
→ Paper 开仓
→ Position / Trade / AccountSnapshot
→ 只读 API
→ /live Dashboard
→ Paper 平仓
→ 手续费 / PnL / Equity / Max Drawdown
```

当前已覆盖：

- LONG 与 SHORT；
- TARGET 与 STOP 两种退出路径；
- 手续费与净 PnL；
- 历史峰值最大回撤；
- 单日最多 3 笔的硬风控；
- 稳定的 ASCII 风控 `reason_code`，避免终端中文编码影响诊断；
- UTC 日界线下的 daily PnL / daily trade count 重建；
- Public Dashboard 生命周期统计不受“最近 30 笔展示窗口”影响。

## 100U 风控基线

这些参数是安全起点，不是收益最优参数：

- 参考启动资金：100 USDT
- 默认单笔风险：0.5%（100U 时为 0.5U 风险预算）
- 单笔风险硬上限：1%
- 默认日亏损上限：2%
- 日亏损硬上限：3%
- 默认最大杠杆：3x
- 系统硬杠杆上限：5x
- 保证金模式：isolated
- 同时最多 1 个持仓
- 连亏 3 笔停止开新仓
- 单日最多 3 笔（当前本地验收配置）

风险预算是上限，不要求强行用满。如果结构止损或最大名义仓位先触发约束，实际风险必须更小。

## 本地端口约定

| 服务 | 默认地址 | 能力 |
|---|---|---|
| Private/Admin API | `127.0.0.1:8000` | Paper / 配置 / 私有管理 |
| Public Read-Only API | `127.0.0.1:8001` | 只读账户、持仓、交易统计 |
| Binance Demo Validation API | `127.0.0.1:8010` | 私有 Demo 联调，默认禁止真实 Demo 下单 |
| Vite Frontend | `localhost:5173` | 管理 UI + `/live` |

启动脚本默认使用**单进程、不带 `--reload`** 的模式，避免 Windows 上 reload 父子进程残留并自动重启。需要开发热重载时显式传 `-Reload`。

## 一键启动 Local Paper 展示栈

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_all.ps1
```

它会分别启动：

- `8000` Private/Admin API
- `8001` Public Read-Only API
- `5173` Vite Frontend

只读展示盘：

```text
http://localhost:5173/live
```

安全停止：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop_local_stack.ps1
```

不要使用 `Get-Process node,python | Stop-Process`，因为那会误杀与本项目无关的 Python / Node 程序。

## Binance USD-M Demo：Windows 本地联调

Demo 不要求云服务器。只要本机运行环境能访问 Binance Demo REST/WSS，就可以直接联调。

当前 Gateway：

- 使用 `ccxt.binanceusdm()`；
- 在任何请求之前启用 Demo Trading；
- 强制校验 USD-M REST 路由必须是 Demo Host；
- 支持从 `HTTP_PROXY` / `HTTPS_PROXY` 显式给 CCXT 配置代理；
- Demo Key / Secret 只从 `BINANCE_TESTNET_API_KEY` / `BINANCE_TESTNET_SECRET` 读取；
- `ENABLE_BINANCE_TESTNET_ORDERS=false` 时真实 Demo 市价单、取消和平仓接口 fail-closed；
- `/fapi/v1/order/test` 只校验签名和订单参数，不创建订单。

### 推荐启动方式

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_demo_backend.ps1
```

默认端口 `8010`。脚本会：

1. 从项目自身路径启动，不依赖当前工作目录；
2. 复用已有 `HTTPS_PROXY/HTTP_PROXY`，必要时读取 Windows 当前用户代理；
3. 隐藏输入 Demo API Key 与 Secret；
4. 强制 `ENABLE_BINANCE_TESTNET_ORDERS=false`；
5. 检查端口冲突并显示占用 PID；
6. 先执行无下单的 Demo 公共 API preflight；
7. 再启动私有 Demo 验证 API。

不要把 API Key / Secret 发到聊天、截图、日志或 GitHub。若凭证曾公开暴露，应撤销并重新生成。

### Demo 联调顺序

先检查本地状态：

```powershell
Invoke-RestMethod http://127.0.0.1:8010/api/testnet/status | ConvertTo-Json -Depth 8
```

目标：

```text
credentials_configured = true
proxy_configured       = true   # 使用代理时
order_routes_enabled   = false
mainnet_orders_supported = false
```

再做只读私有账户认证：

```powershell
Invoke-RestMethod http://127.0.0.1:8010/api/testnet/health | ConvertTo-Json -Depth 8
```

通过后才进入 `/api/testnet/order-test`。在 `order-test` 成功前，不开启真实 Demo order routes。

## 两个 API 服务的生产隔离原则

### Private/Admin API

入口：`backend/main.py`

包含配置、Paper、回测和 Binance Demo 私有路由。生产环境不应直接暴露公网。

### Public Read-Only API

入口：`backend/public_main.py`

只注册只读路由：

```text
GET /api/public/health
GET /api/public/snapshot
```

没有 BUY / SELL / CLOSE / START / STOP / CONFIG 路由，也不读取 Binance Secret。

## Dashboard

`/live` 当前展示：

- 初始资金；
- 当前权益；
- 累计收益；
- 今日已实现 PnL；
- 未实现 PnL；
- 历史最大回撤；
- 当前持仓；
- 数量 / 名义仓位 / 杠杆；
- 最近交易；
- 手续费；
- 生命周期交易数与胜率；
- Setup 与策略 reason codes。

## 测试 / CI

本地：

```powershell
$env:PYTHONPATH = "$PWD\backend"
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

前端：

```powershell
cd frontend
npm run build
```

GitHub Actions 会执行后端 import smoke、pytest 和前端 TypeScript/Vite build。

## 当前下一阶段

```text
S7.2  Local Paper 三策略闭环                 ✅
S7    Binance Demo 公共网络 / CCXT 代理      ✅
S7    Demo 私有 health                       ← 下一检查点
S7    /fapi/v1/order/test                     待验收
S7    Demo 虚拟开仓 / 查询 / reduceOnly 平仓  待验收
S7.3  真实历史行情自动 Paper Replay           待开发
S7.x  Demo 行情流 / reconciliation / kill switch 强化
S8    100U Live                               仅全部上线门槛通过后
S9    24/7 云部署 + HTTPS + CI/CD             后续
```

## 风险提示

量化交易可能产生实际亏损。历史回测、确定性 Paper 场景和 Binance Demo 都不能证明未来盈利能力。系统的首要目标是：策略规则可验证、风险边界不可绕过、订单状态可审计、异常时 fail-closed，然后才讨论收益优化。
