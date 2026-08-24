from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.market_data_service import BinanceDemoClosedCandleProvider, MultiTimeframeBars
from services.universe_scanner import CandidateIntent
from strategy.jianghe.breakout import evaluate_breakout_continuation_from_structure
from strategy.jianghe.pullback import evaluate_trend_pullback_from_structure
from strategy.jianghe.second_push import evaluate_second_push_failure_from_structure
from strategy.jianghe.structure import classify_structure

BASELINE_PROFILE = "JIANGHE_V1_BASELINE_RESEARCH_ONLY"
ARBITRATION_SCORE_VERSION = "V0_TRANSPARENT_EVIDENCE_SCORE"
DEFAULT_REWARD_RISK = 1.8


def _clip01(value: float | None) -> float:
    if value is None:
        return 0.0
    return max(0.0, min(1.0, float(value)))


def candidate_quality_score(evaluation: Any) -> tuple[float, dict[str, float]]:
    """Return a transparent, versioned engineering score for arbitration.

    This is not a profitability claim and is not used to decide whether a setup
    is valid: each setup's own hard gates decide candidate=True first. The score
    exists only to deterministically rank simultaneous already-qualified intents
    until a research profile with a validated native score is promoted.
    """

    setup = str(getattr(evaluation, "setup", ""))
    if setup == "TREND_PULLBACK_CONTINUATION":
        components = {
            "context": _clip01(getattr(evaluation, "context_efficiency", None)),
            "impulse": _clip01(getattr(evaluation, "impulse_strength", None)),
            "trigger": _clip01(getattr(evaluation, "trigger_strength", None)),
        }
    elif setup == "BREAKOUT_CONTINUATION":
        components = {
            "context": _clip01(getattr(evaluation, "context_efficiency", None)),
            "breakout": _clip01(getattr(evaluation, "breakout_strength", None)),
            "followthrough": _clip01(getattr(evaluation, "followthrough_strength", None)),
        }
    elif setup == "SECOND_PUSH_FAILURE":
        strength_ratio = getattr(evaluation, "strength_ratio", None)
        acceptance_fraction = getattr(evaluation, "acceptance_fraction", None)
        components = {
            "trigger": _clip01(getattr(evaluation, "trigger_strength", None)),
            "weakening": _clip01(1.0 - float(strength_ratio)) if strength_ratio is not None else 0.0,
            "failure_acceptance": _clip01(1.0 - float(acceptance_fraction)) if acceptance_fraction is not None else 0.0,
        }
    else:
        components = {"fallback": 0.0}

    score = sum(components.values()) / max(1, len(components))
    return float(score), components


@dataclass(frozen=True)
class SymbolEvaluationResult:
    symbol: str
    profile: str
    latest_closed_1m: Any
    candidate: CandidateIntent | None
    setup_evaluations: tuple[dict[str, Any], ...]
    macro_evidence: dict[str, Any]


class JiangheV1ClosedCandleEvaluator:
    """Adapter from closed Binance Demo candles to the current V1 setup rules.

    The profile is intentionally labelled research-only because historical
    validation has not demonstrated positive expectancy. Building this adapter
    now lets the runtime architecture be tested without silently promoting V1.
    """

    profile_name = BASELINE_PROFILE

    def __init__(self, provider: BinanceDemoClosedCandleProvider | None = None) -> None:
        self.provider = provider or BinanceDemoClosedCandleProvider()

    def evaluate_frames(self, frames: MultiTimeframeBars) -> SymbolEvaluationResult:
        if len(frames.context_15m) < 30 or len(frames.execution_1m) < 30:
            return SymbolEvaluationResult(
                symbol=frames.symbol,
                profile=self.profile_name,
                latest_closed_1m=frames.latest_execution_close,
                candidate=None,
                setup_evaluations=(),
                macro_evidence={"status": "INSUFFICIENT_CLOSED_BARS"},
            )

        context_ohlc = frames.context_15m[["open", "high", "low", "close"]]
        execution_ohlc = frames.execution_1m[["open", "high", "low", "close"]]
        structure = classify_structure(context_ohlc)

        macro_evidence: dict[str, Any] = {}
        if len(frames.macro_1h) >= 30:
            macro = classify_structure(frames.macro_1h[["open", "high", "low", "close"]])
            macro_evidence = {
                "macro_regime": macro.regime.value,
                "macro_efficiency": float(macro.trend_efficiency),
                "macro_net_direction": int(macro.net_direction),
                "macro_is_evidence_only": True,
            }

        evaluations = (
            evaluate_trend_pullback_from_structure(structure, execution_ohlc),
            evaluate_breakout_continuation_from_structure(structure, execution_ohlc),
            evaluate_second_push_failure_from_structure(structure, execution_ohlc),
        )

        candidate_intents: list[CandidateIntent] = []
        evaluation_payloads: list[dict[str, Any]] = []
        for evaluation in evaluations:
            payload = evaluation.to_dict()
            payload["profile"] = self.profile_name
            evaluation_payloads.append(payload)
            if not evaluation.candidate or evaluation.side is None or evaluation.invalidation_reference is None:
                continue
            if evaluation.entry_reference is None:
                continue

            entry = float(evaluation.entry_reference)
            stop = float(evaluation.invalidation_reference)
            distance = abs(entry - stop)
            if distance <= 0:
                continue
            direction = 1.0 if str(evaluation.side).upper() == "LONG" else -1.0
            target = entry + direction * DEFAULT_REWARD_RISK * distance
            score, score_components = candidate_quality_score(evaluation)
            candidate_intents.append(
                CandidateIntent(
                    symbol=frames.symbol,
                    setup=str(evaluation.setup),
                    side=str(evaluation.side).upper(),
                    score=score,
                    entry_reference=entry,
                    stop_reference=stop,
                    target_reference=target,
                    reason_codes=tuple(evaluation.reason_codes),
                    evidence={
                        "strategy_profile": self.profile_name,
                        "arbitration_score_version": ARBITRATION_SCORE_VERSION,
                        "arbitration_score_components": score_components,
                        "latest_closed_1m": str(frames.latest_execution_close),
                        "context_structure": {
                            "regime": structure.regime.value,
                            "trend_efficiency": float(structure.trend_efficiency),
                            "net_direction": int(structure.net_direction),
                        },
                        **macro_evidence,
                        "evaluation": payload,
                    },
                )
            )

        best = None
        if candidate_intents:
            best = sorted(candidate_intents, key=lambda item: (-item.score, item.setup, item.side))[0]

        return SymbolEvaluationResult(
            symbol=frames.symbol,
            profile=self.profile_name,
            latest_closed_1m=frames.latest_execution_close,
            candidate=best,
            setup_evaluations=tuple(evaluation_payloads),
            macro_evidence=macro_evidence,
        )

    def evaluate_symbol(self, symbol: str) -> CandidateIntent | None:
        provider = self.provider.fork()
        frames = provider.fetch_multitimeframe(symbol)
        return self.evaluate_frames(frames).candidate
