# Jianghe Feature & Setup Engine (S2-S4)

本目录不是“江河本人公式”的复刻，而是把其公开视频中反复出现的**市场结构 / 强弱 / 动能转换 / 顺势回调 / 突破延续**语言翻译成可回测特征和候选 Setup。

## 证据边界

- `A/B`：来自公开内容中直接表述或反复体现的概念，例如趋势/震荡、强弱转换、突破、回调、二推失败。
- 本目录的具体数学公式、窗口、权重和阈值统一标记为：`D_EXPERIMENTAL_QUANT_TRANSLATION`。
- 后续必须通过 walk-forward、手续费/滑点/funding 后收益、参数稳定性和消融测试判断这些数学翻译是否有效。

## S2 — Structure Engine

`structure.py`

### Confirmed Swings

局部高/低点使用左右窗口确认。假设 pivot 在 `i`，右侧确认窗口为 `right`：

```text
confirmed_at = i + right
```

回测只能在 `confirmed_at` 之后使用该 swing，防止 look-ahead bias。

### Regime

```text
HH + HL -> BULL_TREND
LH + LL -> BEAR_TREND
其余      -> RANGE
不足两组  -> UNKNOWN
```

`trend_efficiency` 单独返回，不混入 Regime 判定，方便后续消融测试。

## S2 — Strength Engine

`strength.py`

显式输出：

1. `displacement_atr`：窗口净位移 / ATR；
2. `speed_atr_per_bar`：ATR 标准化位移 / bar 数；
3. `body_efficiency`：实体总长度 / K 线总振幅；
4. `directional_consistency`：与净方向一致的 K 线比例；
5. `close_location`：收盘是否靠近推进方向一侧；
6. `overlap_ratio`：相邻 K 线区间重叠程度；
7. `trend_efficiency`：净位移 / 实际路径长度。

### Composite Score v0

```text
0.25 * displacement
0.20 * speed
0.15 * body efficiency
0.15 * directional consistency
0.15 * close location
0.10 * (1 - overlap)
```

所有归一化尺度、权重和 `compare_strength` 的门槛都是 D 级实验参数。

**Composite score 不能单独作为买卖信号。**

## S3 — Trend Pullback Continuation

`pullback.py`

顺势回调把“势 / 位 / 态 / 动”组合成完整候选 Setup，但仍然**不下单**。

### 四个 Gate

```text
CONTEXT / 势
大周期必须是确认后的 BULL_TREND 或 BEAR_TREND

LEVEL / 位
回调进入最近 Higher Low / Lower High 附近
且不能有效破坏该结构位

STATE / 态
前面存在顺趋势 impulse
当前为反向 pullback
pullback 弱于 impulse
回调深度处于实验区间

TRIGGER / 动
原趋势方向重新增强
并重新夺回最后一根 pullback bar 的微结构
```

全部通过：

```text
candidate = true
setup = TREND_PULLBACK_CONTINUATION
side = LONG / SHORT
```

`entry_reference` 与 `invalidation_reference` 都只是研究/展示参考，不是 Binance Order。

## S4 — Breakout Continuation

`breakout.py`

S4 把江河公开视频里“关键位反复测试 / 压缩 / 一方增强 / 有效突破 / 突破后接受”的思路翻译成四个独立 Gate。核心目标不是识别“价格曾经穿过关键位”，而是区分**真突破延续**和**假突破回落**。

### 四个 Gate

```text
1. CONTEXT / 势
   大周期必须是确认后的趋势
   BULL_TREND 只研究向上突破最近结构阻力
   BEAR_TREND 只研究向下突破最近结构支撑

2. PRESSURE / 位 + 态
   突破前价格要向关键位靠近
   在 ATR 容差内至少测试关键位若干次
   突破窗口之前不能已经有效收盘越过关键位
   默认要求后半段 K 线 True Range 小于前半段，形成压缩

3. BREAKOUT / 动
   必须有收盘价有效越过关键位，而不是只靠影线刺穿
   突破距离以 ATR 标准化
   突破 K 实体效率和方向性收盘位置必须达标
   突破窗口方向强度必须与大趋势一致

4. HOLD / 共识确认
   突破后的 follow-through K 线必须大部分/全部维持在关键位外侧
   最终价格必须继续保留正向 extension
   follow-through 方向与强度必须与突破方向一致
   如果重新收回关键位内侧超过容差，则标记 FAILED_BREAKOUT_REENTRY
```

全部通过：

```text
candidate = true
setup = BREAKOUT_CONTINUATION
side = LONG / SHORT
```

### 主要输出

S4 返回：

- `test_count`：关键位测试次数；
- `compression_ratio`：突破前后半段 True Range 比；
- `approach_distance_atr`：突破前最后收盘距离关键位多少 ATR；
- `breakout_extension_atr`：突破收盘超出关键位多少 ATR；
- `breakout_body_efficiency`；
- `breakout_close_location`；
- `breakout_strength`；
- `hold_fraction`：突破后维持在关键位外的收盘比例；
- `final_extension_atr`；
- `followthrough_strength`；
- `gates / reason_codes / failed_gates`。

### 假突破过滤

第一版至少拒绝这些情况：

```text
影线越过但收盘未突破
突破前没有形成测试/压力
没有压缩（默认）
突破 K 质量太差
突破后重新跌回/涨回关键位内侧
突破后没有继续扩展
follow-through 方向反转或明显过弱
```

这并不代表这些过滤条件一定有统计优势。S6 必须分别做消融测试，检验删掉 `compression`、`test_count`、`hold` 等变量以后净收益是否显著变化。

### 第一版实验参数

```text
pressure_bars                   = 12
breakout_window_bars            = 2
followthrough_bars              = 3
min_tests                       = 2
test_tolerance_atr              = 0.40
max_approach_distance_atr       = 0.80
max_compression_ratio           = 0.90
min_breakout_extension_atr      = 0.10
min_breakout_body_efficiency    = 0.45
min_breakout_close_location     = 0.65
min_breakout_strength           = 0.40
max_reentry_atr                 = 0.15
min_hold_fraction               = 1.00
min_followthrough_extension_atr = 0.05
min_followthrough_strength      = 0.25
```

这些数字全部是 D 级待检验参数，禁止在完整历史数据上反复调到最赚钱后再把结果当作真实优势。

## 执行安全边界

S2-S4 都只生成研究特征或 `candidate`。这些模块中没有：

```text
create_order
BUY / SELL
CLOSE
change_leverage
Binance private API
```

只有后续 Risk Engine、Execution Engine 通过独立验收后，candidate 才可能进入 Testnet。

## 下一阶段

S5 实现 `Second-Push Failure`：比较第一次推进和第二次推进的效率、结果、结构突破能力，并要求反向动能确认。S5 完成后，三类核心 Setup 才进入 S6 统一回测、交易成本、walk-forward 和 ablation。
