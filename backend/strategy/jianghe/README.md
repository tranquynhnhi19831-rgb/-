# Jianghe Feature & Setup Engine (S2-S5)

本目录不是“江河本人公式”的复刻，而是把其公开视频中反复出现的**市场结构 / 强弱 / 动能转换 / 顺势回调 / 突破延续 / 二推失败**语言翻译成可回测特征和候选 Setup。

## 证据边界

- `A/B`：来自公开内容中直接表述或反复体现的概念，例如趋势/震荡、强弱转换、突破、回调、二推失败。
- 本目录的具体公式、窗口、权重和阈值统一标记为 `D_EXPERIMENTAL_QUANT_TRANSLATION`。
- 后续必须通过手续费、滑点、funding、walk-forward、参数稳定性与消融测试判断这些数学翻译是否真的有信息增益。

## S2 — Structure / Strength Engine

`structure.py` 使用已确认 swing high / low 分类：

```text
HH + HL -> BULL_TREND
LH + LL -> BEAR_TREND
其余      -> RANGE
不足两组  -> UNKNOWN
```

pivot 只有在右侧窗口出现后才确认：

```text
confirmed_at = pivot_index + right
```

回测只能在 `confirmed_at` 之后使用，防止 look-ahead bias。

`strength.py` 显式输出：

```text
displacement_atr
speed_atr_per_bar
body_efficiency
directional_consistency
close_location
overlap_ratio
trend_efficiency
composite_score
```

Composite score 只是实验排序特征，不能单独作为买卖信号。

## S3 — Trend Pullback Continuation

`pullback.py`

```text
CONTEXT  大周期趋势确认
LEVEL    回调进入 Higher Low / Lower High 附近且结构未失效
STATE    顺势 impulse 后出现更弱的反向 pullback
TRIGGER  原趋势重新增强并夺回微结构
```

四个 Gate 全部通过后才返回：

```text
candidate = true
setup = TREND_PULLBACK_CONTINUATION
```

## S4 — Breakout Continuation

`breakout.py`

```text
CONTEXT  大周期趋势与突破方向一致
PRESSURE 关键位反复测试、靠近、默认要求压缩
BREAKOUT 收盘有效突破，K 线与窗口动能质量达标
HOLD     突破后维持在关键位外并出现 follow-through
```

第一版会拒绝：影线刺穿但未收盘突破、测试不足、无压缩、突破质量差、突破后重新进入关键位、没有延续等情形。

## S5 — Second-Push Failure

`second_push.py`

S5 把“二推不破”拆成**弱点识别**和**反转候选**两个阶段，避免把“第二推变弱”直接等同于反向开仓。

### 四个 Gate

```text
1. CONTEXT / 关键环境
   高周期必须存在可使用的结构位。
   第一版允许 RANGE 边界，因为二推失败常发生在区间阻力/支撑；
   UNKNOWN 上下文直接拒绝。

2. LOCATION / 同一战场
   Push #1 与 Push #2 必须朝同一方向推进；
   两次都要测试同一个结构阻力/支撑；
   中间必须有方向相反或中性的 reset，并产生足够分离。

3. FAILURE / 投入-结果恶化
   Push #1 必须具备最低质量；
   Push #2 的 composite strength 更弱；
   Push #2 的 ATR 位移更弱；
   Push #2 的推进速度更弱；
   第二推不能相对第一推取得过大的新高/新低扩展；
   关键位外侧不能形成持续收盘接受。

4. TRIGGER / 反向接管
   反方向动能必须真正出现；
   Trigger 强度满足绝对门槛和相对门槛；
   默认要求最终收盘破坏 Push #2 的微结构。
```

### 两级状态

```text
CONTEXT + LOCATION + FAILURE 通过
TRIGGER 未通过
    -> signal_state = SECOND_PUSH_WEAKNESS
    -> weakness_detected = true
    -> candidate = false

四个 Gate 全部通过
    -> signal_state = REVERSAL_CANDIDATE
    -> candidate = true
```

这条边界很重要：**观察到多头/空头衰竭，不代表另一方已经获得控制权。**

### 主要输出

S5 返回：

```text
push1_distance_atr
push2_distance_atr
reset_depth_atr
push1_strength
push2_strength
strength_ratio
displacement_ratio
speed_ratio
result_extension_atr
acceptance_fraction
trigger_strength
entry_reference
invalidation_reference
gates
reason_codes
failed_gates
signal_state
```

其中 `entry_reference` / `invalidation_reference` 仍然只是研究和展示字段，不是 Binance Order。

### 第一版实验参数

```text
push1_bars                              = 6
reset_bars                              = 4
push2_bars                              = 6
trigger_bars                            = 3
level_tolerance_atr                     = 0.80
min_reset_depth_atr                     = 0.35
min_push1_strength                      = 0.45
max_push2_to_push1_strength_ratio       = 0.82
max_push2_to_push1_displacement_ratio   = 0.90
max_push2_to_push1_speed_ratio          = 0.90
max_push2_result_extension_atr          = 0.20
max_acceptance_fraction                 = 0.34
min_trigger_strength                    = 0.40
min_trigger_to_push2_ratio              = 0.75
```

这些数字全部是 D 级实验参数。S6 必须做参数扰动和消融，不能把历史最优参数当成真实规律。

## 执行安全边界

S2-S5 只生成特征或 `candidate`，模块中不允许出现：

```text
create_order
BUY / SELL
CLOSE
change_leverage
Binance private order API
```

候选信号必须先进入独立 Risk Engine；只有通过后续 Testnet 验收，才考虑接 Execution Engine。

## 下一阶段 — S6

三类核心 Setup 已具备第一版：

```text
Trend Pullback Continuation
Breakout Continuation
Second-Push Failure
```

下一步进入统一回测框架：历史数据切片、手续费、滑点、funding、无未来函数事件循环、每种 Setup 独立统计、组合统计、walk-forward、参数稳定性和 ablation。第一目标不是“调到赚钱”，而是判断哪些规则在样本外仍有统计价值。
