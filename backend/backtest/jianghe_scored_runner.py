from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backtest.jianghe_multitimeframe_runner import (
    MultiTimeframeRunnerConfig,
    _frame,
    multitimeframe_alignment_allowed,
)
from backtest.types import CandidateSignal
from strategy.jianghe.pullback_event import EventPullbackConfig, evaluate_event_pullback_from_structure
from strategy.jianghe.pullback_score import score_event_pullback
from strategy.jianghe.structure import classify_structure
from strategy.jianghe.types import StructureSnapshot


@dataclass(frozen=True)
class ScoredMultiTimeframeRunnerConfig:
    macro_lookback: int = 120
    context_lookback: int = 120
    execution_lookback: int = 64
    min_macro_bars: int = 30
    min_context_bars: int = 30
    min_execution_bars: int = 16
    signal_cooldown_bars: int = 6
    min_macro_efficiency: float = 0.18
    min_context_efficiency: float = 0.22
    min_quality_score: float = 0.55
    execution_timeframe_label: str = "1m"
    setup_version: str = "V5_SCORED_MTF_PULLBACK"
    setup_name: str = "TREND_PULLBACK_EVENT_V5_SCORED_MTF"
    event_config: EventPullbackConfig = field(default_factory=EventPullbackConfig)

    def alignment_config(self) -> MultiTimeframeRunnerConfig:
        return MultiTimeframeRunnerConfig(
            macro_lookback=self.macro_lookback,
            context_lookback=self.context_lookback,
            execution_lookback=self.execution_lookback,
            min_macro_bars=self.min_macro_bars,
            min_context_bars=self.min_context_bars,
            min_execution_bars=self.min_execution_bars,
            signal_cooldown_bars=self.signal_cooldown_bars,
            min_macro_efficiency=self.min_macro_efficiency,
            min_context_efficiency=self.min_context_efficiency,
            require_macro_context_same_direction=True,
            event_config=self.event_config,
        )

    def validate(self) -> None:
        self.alignment_config().validate()
        if not 0.0 <= self.min_quality_score <= 1.0:
            raise ValueError("min_quality_score must be between 0 and 1")
        if not self.execution_timeframe_label.strip():
            raise ValueError("execution_timeframe_label is required")
        if not self.setup_version.strip():
            raise ValueError("setup_version is required")
        if not self.setup_name.strip():
            raise ValueError("setup_name is required")


def generate_scored_multitimeframe_pullback_signals_fast(
    macro_bars: pd.DataFrame,
    context_bars: pd.DataFrame,
    execution_bars: pd.DataFrame,
    config: ScoredMultiTimeframeRunnerConfig | None = None,
) -> list[CandidateSignal]:
    """Hard structural validity + soft quality ranking.

    V5 used this on 1m execution. V6 reuses exactly the same structural/score
    code on a coarser execution frame. The timeframe label and setup identity
    are metadata only; they do not alter candidate mathematics.
    """
    cfg = config or ScoredMultiTimeframeRunnerConfig()
    cfg.validate()
    alignment_cfg = cfg.alignment_config()

    macro = _frame(macro_bars, "macro_bars")
    context = _frame(context_bars, "context_bars")
    execution = _frame(execution_bars, "execution_bars")

    macro_times = macro["timestamp"].astype("int64").to_numpy()
    ctx_times = context["timestamp"].astype("int64").to_numpy()
    ex_times = execution["timestamp"].astype("int64").to_numpy()
    macro_ohlc = macro[["open", "high", "low", "close"]]
    ctx_ohlc = context[["open", "high", "low", "close"]]
    ex_ohlc = execution[["open", "high", "low", "close"]]

    signals: list[CandidateSignal] = []
    seen_events: set[tuple[str, int]] = set()
    last_emitted: dict[str, int] = {}
    last_macro_end = -1
    last_ctx_end = -1
    macro_structure: StructureSnapshot | None = None
    context_structure: StructureSnapshot | None = None

    for i, now_ns in enumerate(ex_times):
        if i + 1 < cfg.min_execution_bars:
            continue

        macro_end = int(np.searchsorted(macro_times, now_ns, side="right"))
        ctx_end = int(np.searchsorted(ctx_times, now_ns, side="right"))
        if macro_end < cfg.min_macro_bars or ctx_end < cfg.min_context_bars:
            continue

        if macro_end != last_macro_end:
            macro_start = max(0, macro_end - cfg.macro_lookback)
            macro_structure = classify_structure(macro_ohlc.iloc[macro_start:macro_end])
            last_macro_end = macro_end

        if ctx_end != last_ctx_end:
            ctx_start = max(0, ctx_end - cfg.context_lookback)
            context_structure = classify_structure(ctx_ohlc.iloc[ctx_start:ctx_end])
            last_ctx_end = ctx_end

        assert macro_structure is not None
        assert context_structure is not None
        if not multitimeframe_alignment_allowed(macro_structure, context_structure, alignment_cfg):
            continue

        ex_start = max(0, i + 1 - cfg.execution_lookback)
        ex = ex_ohlc.iloc[ex_start : i + 1]
        evaluation = evaluate_event_pullback_from_structure(context_structure, ex, cfg.event_config)
        if evaluation.side is None or evaluation.invalidation_reference is None:
            continue

        score = score_event_pullback(
            evaluation,
            ex,
            cfg.event_config,
            min_quality_score=cfg.min_quality_score,
        )
        if not score.eligible or evaluation.pullback_end_index is None:
            continue

        event_anchor = ex_start + int(evaluation.pullback_end_index)
        event_key = (evaluation.side, event_anchor)
        if event_key in seen_events:
            continue

        previous = last_emitted.get(evaluation.side)
        if previous is not None and i - previous <= cfg.signal_cooldown_bars:
            continue

        metadata = evaluation.to_dict()
        metadata.update(
            {
                "setup_version": cfg.setup_version,
                "quality_score": float(score.quality_score),
                "quality_components": score.components,
                "quality_hard_gates": score.hard_gates,
                "quality_reason_codes": list(score.reason_codes),
                "event_pullback_index_abs": int(event_anchor),
                "macro_timeframe": "1h",
                "macro_regime": macro_structure.regime.value,
                "macro_efficiency": float(macro_structure.trend_efficiency),
                "context_timeframe": "15m",
                "context_regime": context_structure.regime.value,
                "context_efficiency": float(context_structure.trend_efficiency),
                "execution_timeframe": cfg.execution_timeframe_label,
                "multitimeframe_alignment": True,
            }
        )
        signals.append(
            CandidateSignal(
                index=i,
                timestamp=execution.loc[i, "timestamp"],
                setup=cfg.setup_name,
                side=evaluation.side,
                entry_reference=evaluation.entry_reference,
                invalidation_reference=float(evaluation.invalidation_reference),
                metadata=metadata,
            )
        )
        seen_events.add(event_key)
        last_emitted[evaluation.side] = i

    return signals
