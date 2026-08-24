from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.jianghe_runner import (
    SETUP_BREAKOUT,
    SETUP_PULLBACK,
    SETUP_SECOND_PUSH,
    JiangheRunnerConfig,
    _append_candidates,
    _runner_context_allowed,
    _second_push_allowed,
    _validate_frame,
)
from backtest.types import CandidateSignal
from strategy.jianghe.breakout import evaluate_breakout_continuation_from_structure
from strategy.jianghe.pullback import evaluate_trend_pullback_from_structure
from strategy.jianghe.second_push import evaluate_second_push_failure_from_structure
from strategy.jianghe.structure import classify_structure
from strategy.jianghe.types import MarketRegime, StructureSnapshot


TREND_REGIMES = {MarketRegime.BULL_TREND, MarketRegime.BEAR_TREND}


def generate_jianghe_signals_research_fast(
    context_bars: pd.DataFrame,
    execution_bars: pd.DataFrame,
    config: JiangheRunnerConfig | None = None,
) -> list[CandidateSignal]:
    """Semantics-preserving research runner with regime short-circuiting."""

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

        if not _runner_context_allowed(structure, cfg):
            continue

        has_trend = structure.regime in TREND_REGIMES
        if not has_trend and (
            structure.regime == MarketRegime.UNKNOWN
            or SETUP_SECOND_PUSH not in cfg.enabled_setups
            or not cfg.allow_second_push_range
        ):
            continue

        ex_start = max(0, i + 1 - cfg.execution_lookback)
        ex = ex_ohlc.iloc[ex_start : i + 1]
        evaluations = []

        if has_trend and SETUP_PULLBACK in cfg.enabled_setups:
            evaluations.append(
                evaluate_trend_pullback_from_structure(structure, ex, cfg.pullback_config)
            )
        if has_trend and SETUP_BREAKOUT in cfg.enabled_setups:
            evaluations.append(
                evaluate_breakout_continuation_from_structure(structure, ex, cfg.breakout_config)
            )
        if SETUP_SECOND_PUSH in cfg.enabled_setups and structure.regime != MarketRegime.UNKNOWN:
            if structure.regime != MarketRegime.RANGE or cfg.allow_second_push_range:
                second_push = evaluate_second_push_failure_from_structure(
                    structure,
                    ex,
                    cfg.second_push_config,
                )
                if _second_push_allowed(second_push, structure, cfg):
                    evaluations.append(second_push)

        _append_candidates(
            signals,
            evaluations,
            index=i,
            now=execution.loc[i, "timestamp"],
            last_emitted=last_emitted,
            cooldown_bars=cfg.signal_cooldown_bars,
        )

    return signals
