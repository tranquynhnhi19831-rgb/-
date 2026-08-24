from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backtest.types import CandidateSignal
from strategy.jianghe.breakout import (
    BreakoutConfig,
    evaluate_breakout_continuation_from_structure,
)
from strategy.jianghe.pullback import (
    PullbackConfig,
    evaluate_trend_pullback_from_structure,
)
from strategy.jianghe.second_push import (
    SecondPushConfig,
    evaluate_second_push_failure_from_structure,
)
from strategy.jianghe.structure import classify_structure
from strategy.jianghe.types import MarketRegime, StructureSnapshot

SETUP_PULLBACK = "TREND_PULLBACK_CONTINUATION"
SETUP_BREAKOUT = "BREAKOUT_CONTINUATION"
SETUP_SECOND_PUSH = "SECOND_PUSH_FAILURE"
ALL_SETUPS = (SETUP_PULLBACK, SETUP_BREAKOUT, SETUP_SECOND_PUSH)


@dataclass(frozen=True)
class JiangheRunnerConfig:
    context_lookback: int = 120
    execution_lookback: int = 96
    min_context_bars: int = 30
    min_execution_bars: int = 24
    signal_cooldown_bars: int = 3
    enabled_setups: tuple[str, ...] = ALL_SETUPS

    # Runner-level context filters. Baseline defaults preserve S7 behavior.
    min_context_efficiency: float = 0.0
    require_context_direction_alignment: bool = False
    allow_second_push_range: bool = True
    require_second_push_trend_alignment: bool = False

    # Explicit setup configs make research profiles reproducible instead of
    # relying on hidden/default parameter mutations inside the evaluators.
    pullback_config: PullbackConfig = field(default_factory=PullbackConfig)
    breakout_config: BreakoutConfig = field(default_factory=BreakoutConfig)
    second_push_config: SecondPushConfig = field(default_factory=SecondPushConfig)

    def validate(self) -> None:
        if self.context_lookback < self.min_context_bars:
            raise ValueError("context_lookback must be >= min_context_bars")
        if self.execution_lookback < self.min_execution_bars:
            raise ValueError("execution_lookback must be >= min_execution_bars")
        if self.signal_cooldown_bars < 0:
            raise ValueError("signal_cooldown_bars must be >= 0")
        if not 0.0 <= self.min_context_efficiency <= 1.0:
            raise ValueError("min_context_efficiency must be between 0 and 1")
        unknown = set(self.enabled_setups).difference(ALL_SETUPS)
        if unknown:
            raise ValueError(f"unknown setups: {sorted(unknown)}")


def quality_first_v2_config() -> JiangheRunnerConfig:
    """Return the first quality-first research profile after the long-history baseline.

    This is deliberately a *research* profile, not a production promotion. The
    baseline backtest showed that the initial translation admitted too many low
    quality candidates. V2 therefore tightens only rules that map directly to
    the Jianghe framework: the higher-timeframe trend must have directional
    agreement, impulse/trigger quality must be clearer, breakout acceptance must
    be cleaner, and second-push reversal is not allowed from generic range noise.

    The values are intentionally coarse quality thresholds, not an optimized
    parameter fit. They must survive walk-forward / out-of-sample validation
    before they can replace the S7 defaults.
    """

    return JiangheRunnerConfig(
        signal_cooldown_bars=6,
        min_context_efficiency=0.22,
        require_context_direction_alignment=True,
        allow_second_push_range=False,
        require_second_push_trend_alignment=True,
        pullback_config=PullbackConfig(
            min_context_efficiency=0.22,
            max_pullback_depth_atr=2.50,
            min_impulse_strength=0.55,
            max_pullback_to_impulse_ratio=0.75,
            min_trigger_strength=0.50,
            min_trigger_to_pullback_ratio=0.95,
            require_micro_reclaim=True,
        ),
        breakout_config=BreakoutConfig(
            min_context_efficiency=0.28,
            min_tests=3,
            max_approach_distance_atr=0.65,
            max_compression_ratio=0.82,
            require_compression=True,
            min_breakout_extension_atr=0.15,
            min_breakout_body_efficiency=0.55,
            min_breakout_close_location=0.72,
            min_breakout_strength=0.50,
            max_reentry_atr=0.10,
            min_hold_fraction=1.0,
            min_followthrough_extension_atr=0.10,
            min_followthrough_strength=0.35,
        ),
        second_push_config=SecondPushConfig(
            allow_range_context=False,
            level_tolerance_atr=0.65,
            min_reset_depth_atr=0.40,
            max_reset_depth_atr=3.00,
            min_push1_strength=0.55,
            max_push2_to_push1_strength_ratio=0.75,
            max_push2_to_push1_displacement_ratio=0.80,
            max_push2_to_push1_speed_ratio=0.80,
            max_push2_result_extension_atr=0.10,
            max_acceptance_fraction=0.17,
            min_trigger_strength=0.50,
            min_trigger_to_push2_ratio=1.00,
            require_micro_break=True,
        ),
    )


def _validate_frame(df: pd.DataFrame, name: str) -> pd.DataFrame:
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"{name} missing columns: {sorted(missing)}")
    result = df.copy()
    result["timestamp"] = pd.to_datetime(result["timestamp"], utc=True)
    return result.sort_values("timestamp").reset_index(drop=True)


def _trend_direction(structure: StructureSnapshot) -> int:
    if structure.regime == MarketRegime.BULL_TREND:
        return 1
    if structure.regime == MarketRegime.BEAR_TREND:
        return -1
    return 0


def _runner_context_allowed(structure: StructureSnapshot, cfg: JiangheRunnerConfig) -> bool:
    if structure.trend_efficiency < cfg.min_context_efficiency:
        return False
    direction = _trend_direction(structure)
    if cfg.require_context_direction_alignment and direction != 0:
        return structure.net_direction == direction
    return True


def _second_push_allowed(evaluation, structure: StructureSnapshot, cfg: JiangheRunnerConfig) -> bool:
    if structure.regime == MarketRegime.RANGE and not cfg.allow_second_push_range:
        return False
    if not cfg.require_second_push_trend_alignment:
        return True
    trend_direction = _trend_direction(structure)
    if trend_direction == 0:
        return True
    push_direction = 1 if evaluation.push_direction == "UP" else -1 if evaluation.push_direction == "DOWN" else 0
    return push_direction == trend_direction


def _evaluate(
    structure: StructureSnapshot,
    execution_ohlc: pd.DataFrame,
    cfg: JiangheRunnerConfig,
):
    if not _runner_context_allowed(structure, cfg):
        return []

    evaluations = []
    if SETUP_PULLBACK in cfg.enabled_setups:
        evaluations.append(
            evaluate_trend_pullback_from_structure(
                structure,
                execution_ohlc,
                cfg.pullback_config,
            )
        )
    if SETUP_BREAKOUT in cfg.enabled_setups:
        evaluations.append(
            evaluate_breakout_continuation_from_structure(
                structure,
                execution_ohlc,
                cfg.breakout_config,
            )
        )
    if SETUP_SECOND_PUSH in cfg.enabled_setups:
        second_push = evaluate_second_push_failure_from_structure(
            structure,
            execution_ohlc,
            cfg.second_push_config,
        )
        if _second_push_allowed(second_push, structure, cfg):
            evaluations.append(second_push)
    return evaluations


def _append_candidates(
    signals: list[CandidateSignal],
    evaluations,
    *,
    index: int,
    now: pd.Timestamp,
    last_emitted: dict[tuple[str, str], int],
    cooldown_bars: int,
) -> None:
    for evaluation in evaluations:
        if not evaluation.candidate or evaluation.side is None or evaluation.invalidation_reference is None:
            continue
        key = (evaluation.setup, evaluation.side)
        previous_index = last_emitted.get(key)
        if previous_index is not None and index - previous_index <= cooldown_bars:
            continue

        metadata = evaluation.to_dict()
        metadata["runner_context_efficiency"] = float(metadata.get("context_efficiency", 0.0))
        signals.append(
            CandidateSignal(
                index=index,
                timestamp=now,
                setup=evaluation.setup,
                side=evaluation.side,
                entry_reference=evaluation.entry_reference,
                invalidation_reference=float(evaluation.invalidation_reference),
                metadata=metadata,
            )
        )
        last_emitted[key] = index


def generate_jianghe_signals(
    context_bars: pd.DataFrame,
    execution_bars: pd.DataFrame,
    config: JiangheRunnerConfig | None = None,
) -> list[CandidateSignal]:
    """Generate candidate signals without look-ahead.

    Both inputs must use candle CLOSE timestamps. For each execution candle, the
    runner only exposes context candles whose close timestamp is <= the current
    execution close timestamp. Signals are therefore known only after the
    current execution candle closes; BacktestEngine enters no earlier than the
    following candle open.
    """
    cfg = config or JiangheRunnerConfig()
    cfg.validate()
    context = _validate_frame(context_bars, "context_bars")
    execution = _validate_frame(execution_bars, "execution_bars")

    signals: list[CandidateSignal] = []
    last_emitted: dict[tuple[str, str], int] = {}

    for i in range(len(execution)):
        if i + 1 < cfg.min_execution_bars:
            continue
        now = execution.loc[i, "timestamp"]
        ctx = context[context["timestamp"] <= now].tail(cfg.context_lookback)
        if len(ctx) < cfg.min_context_bars:
            continue

        ex = execution.iloc[max(0, i + 1 - cfg.execution_lookback) : i + 1]
        structure = classify_structure(ctx[["open", "high", "low", "close"]])
        evaluations = _evaluate(
            structure,
            ex[["open", "high", "low", "close"]],
            cfg,
        )
        _append_candidates(
            signals,
            evaluations,
            index=i,
            now=now,
            last_emitted=last_emitted,
            cooldown_bars=cfg.signal_cooldown_bars,
        )

    return signals


def generate_jianghe_signals_fast(
    context_bars: pd.DataFrame,
    execution_bars: pd.DataFrame,
    config: JiangheRunnerConfig | None = None,
) -> list[CandidateSignal]:
    """Equivalent long-history runner with cached context classification.

    The strategy semantics are the same as :func:`generate_jianghe_signals`.
    It avoids re-filtering the entire context frame on every execution candle
    and only re-classifies the higher-timeframe structure when a new context
    candle becomes visible. This is important for multi-year parameter research.
    """
    cfg = config or JiangheRunnerConfig()
    cfg.validate()
    context = _validate_frame(context_bars, "context_bars")
    execution = _validate_frame(execution_bars, "execution_bars")

    ctx_times = context["timestamp"].astype("int64").to_numpy()
    ex_times = execution["timestamp"].astype("int64").to_numpy()
    ctx_ohlc = context[["open", "high", "low", "close"]]
    ex_ohlc = execution[["open", "high", "low", "close"]]

    signals: list[CandidateSignal] = []
    last_emitted: dict[tuple[str, str], int] = {}
    last_ctx_end = -1
    structure: StructureSnapshot | None = None

    for i, now_ns in enumerate(ex_times):
        if i + 1 < cfg.min_execution_bars:
            continue
        ctx_end = int(np.searchsorted(ctx_times, now_ns, side="right"))
        if ctx_end < cfg.min_context_bars:
            continue

        if ctx_end != last_ctx_end:
            ctx_start = max(0, ctx_end - cfg.context_lookback)
            structure = classify_structure(ctx_ohlc.iloc[ctx_start:ctx_end])
            last_ctx_end = ctx_end
        assert structure is not None

        ex_start = max(0, i + 1 - cfg.execution_lookback)
        ex = ex_ohlc.iloc[ex_start : i + 1]
        evaluations = _evaluate(structure, ex, cfg)
        _append_candidates(
            signals,
            evaluations,
            index=i,
            now=execution.loc[i, "timestamp"],
            last_emitted=last_emitted,
            cooldown_bars=cfg.signal_cooldown_bars,
        )

    return signals
