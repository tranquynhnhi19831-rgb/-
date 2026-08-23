# Jianghe Feature & Setup Engine (S2-S3)

本目录不是“江河本人公式”的复刻，而是把其公开视频中反复出现的**市场结构 / 强弱 / 动能转换 / 顺势回调**语言翻译成可回测特征和候选 Setup。

## 证据边界

- `A/B`：来自公开内容中直接表述或反复体现的概念，例如趋势/震荡、强弱转换、突破、回调、二推失败。
- 本目录的具体数学公式、权重和阈值统一标记为：
  `D_EXPERIMENTAL_QUANT_TRANSLATION`。
- 后续必须通过 walk-forward、手续费/滑点后收益、消融测试判断这些数学翻译是否有效。

## S2 — Structure Engine

`structure.py`

### Confirmed Swings

局部高/低点使用左右窗口确认。假设 pivot 在 `i`，右侧确认窗口为 `right`，则：

```text
confirmed_at = i + right
```

回测只能在 `confirmed_at` 之后使用该 swing，防止未来函数 / look-ahead bias。

### Regime

第一版使用最近两个**已确认** swing high / low：

```text
HH + HL -> BULL_TREND
LH + LL -> BEAR_TREND
其余      -> RANGE
不足两组  -> UNKNOWN
```

`trend_efficiency` 单独返回，不混入 Regime 判定，方便后续消融测试。

## S2 — Strength Engine

`strength.py`

第一版显式输出：

1. `displacement_atr`：窗口净位移 / ATR；
2. `speed_atr_per_bar`：ATR 标准化位移 / bar 数；
3. `body_efficiency`：实体总长度 / K 线总振幅；
4. `directional_consistency`：与净方向一致的 K 线比例；
5. `close_location`：收盘是否靠近推进方向一侧；
6. `overlap_ratio`：相邻 K 线区间重叠程度；
7. `trend_efficiency`：净位移 / 实际路径长度。

### Composite Score v0

为了方便第一轮排序，暂时使用：

```text
0.25 * displacement
0.20 * speed
0.15 * body efficiency
0.15 * directional consistency
0.15 * close location
0.10 * (1 - overlap)
```

所有归一化尺度、权重和 `compare_strength` 的默认 `min_delta=0.10` 都是 D 级实验参数。

**不能把 composite score 当作直接买卖信号。**

## S3 — Trend Pullback Continuation

`pullback.py`

顺势回调第一次把“势 / 位 / 态 / 动”组合成完整候选 Setup，但仍然**不下单**。

### 四个 Gate

```text
1. CONTEXT / 势
   大周期必须已经形成确认后的 BULL_TREND 或 BEAR_TREND

2. LEVEL / 位
   回调必须进入最近结构 Higher Low / Lower High 附近
   同时不能有效破坏该结构位

3. STATE / 态
   前面必须存在顺趋势 impulse
   当前必须是反向 pullback
   pullback 强度要弱于前一段 impulse
   回调深度必须在实验区间内

4. TRIGGER / 动
   原趋势方向重新增强
   trigger 强度满足绝对与相对门槛
   收盘重新夺回最后一根 pullback bar 的微结构
```

全部通过后才会返回：

```text
candidate = true
setup = TREND_PULLBACK_CONTINUATION
side = LONG / SHORT
```

### 输出不是订单

S3 返回：

- `candidate`
- `side`
- `level_price`
- `level_distance_atr`
- `pullback_depth_atr`
- `impulse_strength`
- `pullback_strength`
- `trigger_strength`
- `invalidation_reference`
- `gates`
- `reason_codes`
- `failed_gates`

`entry_reference` 与 `invalidation_reference` 都只是研究/展示参考，不是 Binance Order。

### 第一版实验参数

默认值包括：

```text
impulse_bars                   = 8
pullback_bars                  = 5
trigger_bars                   = 3
level_tolerance_atr            = 0.75
invalidation_buffer_atr        = 0.20
min_pullback_depth_atr         = 0.30
max_pullback_depth_atr         = 4.00
min_impulse_strength           = 0.50
max_pullback_to_impulse_ratio  = 0.85
min_trigger_strength           = 0.45
min_trigger_to_pullback_ratio  = 0.75
```

这些数字全部是 D 级待检验参数。后续回测必须做参数稳定性、walk-forward 与 ablation；禁止只选择历史收益最高的一组。

## 下一阶段

S4 将独立实现 `Breakout Continuation`，不与 S3 共用最终入场阈值。S5 再实现 `Second-Push Failure`。等三类 Setup 都独立可测后，才进入统一回测和交易成本建模。
