# Jianghe Feature Engine (S2)

本目录不是“江河本人公式”的复刻，而是把其公开视频中反复出现的**市场结构 / 强弱 / 动能转换**语言翻译成可回测特征。

## 证据边界

- `A/B`：来自公开内容中直接表述或反复体现的概念，例如趋势/震荡、强弱转换、突破、回调、二推失败。
- 本目录的具体数学公式、权重和阈值统一标记为：
  `D_EXPERIMENTAL_QUANT_TRANSLATION`。
- 后续必须通过 walk-forward、手续费/滑点后收益、消融测试判断这些数学翻译是否有效。

## Structure Engine

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

## Strength Engine

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

## S3 以后如何使用

策略 Setup 应该组合：

```text
Context / 势
+ Level / 位
+ State / 态
+ Strength Transition / 动
= Setup candidate
```

例如顺势回调的候选逻辑应先确认大周期上涨结构，再等待回调方向动能衰减与原趋势方向重新增强；不能因为 `strength_score > X` 单独开仓。
