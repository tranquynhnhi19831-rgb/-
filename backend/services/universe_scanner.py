from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from config import INITIAL_TRADING_UNIVERSE
from services.trade_audit_service import add_trade_decision, new_cycle_id, new_decision_id


@dataclass(frozen=True)
class CandidateIntent:
    symbol: str
    setup: str
    side: str
    score: float
    entry_reference: float
    stop_reference: float
    target_reference: float | None = None
    reason_codes: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditedCandidate:
    intent: CandidateIntent
    decision_id: str


def _universe_rank(symbol: str) -> int:
    try:
        return INITIAL_TRADING_UNIVERSE.index(symbol)
    except ValueError:
        return len(INITIAL_TRADING_UNIVERSE)


def rank_candidates(candidates: Iterable[CandidateIntent]) -> list[CandidateIntent]:
    """Rank simultaneous candidates without depending on scan order.

    Higher strategy quality score wins. Ties are resolved by the fixed universe
    order so the result is deterministic and reproducible in replay/backtest.
    """
    items = list(candidates)
    unknown = [c.symbol for c in items if c.symbol not in INITIAL_TRADING_UNIVERSE]
    if unknown:
        raise ValueError(f"candidate outside fixed universe: {sorted(set(unknown))}")
    return sorted(items, key=lambda c: (-float(c.score), _universe_rank(c.symbol), c.setup, c.side))


def audit_and_select_candidate(db, candidates: Iterable[CandidateIntent], *, cycle_id: str | None = None):
    """Persist every qualified intent, then choose at most one global winner.

    This function does not place orders. The selected intent must still pass the
    global RiskManager and exchange preflight. Every non-selected simultaneous
    candidate remains in the database with ``ARBITRATION/NOT_SELECTED`` so we
    can later answer why a valid signal was not traded.
    """
    cycle = cycle_id or new_cycle_id("universe")
    ranked = rank_candidates(candidates)
    audited: list[AuditedCandidate] = []

    for intent in ranked:
        decision_id = new_decision_id()
        add_trade_decision(
            db,
            cycle_id=cycle,
            decision_id=decision_id,
            symbol=intent.symbol,
            setup=intent.setup,
            side=intent.side,
            stage="CANDIDATE",
            outcome="QUALIFIED",
            candidate=True,
            selected=False,
            score=float(intent.score),
            entry_reference=float(intent.entry_reference),
            stop_reference=float(intent.stop_reference),
            target_reference=(None if intent.target_reference is None else float(intent.target_reference)),
            reason_codes=list(intent.reason_codes),
            evidence=intent.evidence,
        )
        audited.append(AuditedCandidate(intent=intent, decision_id=decision_id))

    if not audited:
        return cycle, None

    winner = audited[0]
    for item in audited:
        selected = item.decision_id == winner.decision_id
        add_trade_decision(
            db,
            cycle_id=cycle,
            decision_id=item.decision_id,
            symbol=item.intent.symbol,
            setup=item.intent.setup,
            side=item.intent.side,
            stage="ARBITRATION",
            outcome="SELECTED" if selected else "NOT_SELECTED",
            candidate=True,
            selected=selected,
            score=float(item.intent.score),
            entry_reference=float(item.intent.entry_reference),
            stop_reference=float(item.intent.stop_reference),
            target_reference=(None if item.intent.target_reference is None else float(item.intent.target_reference)),
            reason_codes=list(item.intent.reason_codes),
            evidence={
                **item.intent.evidence,
                "selection_policy": "HIGHEST_SCORE_THEN_FIXED_UNIVERSE_ORDER",
                "qualified_candidates": len(audited),
            },
        )

    return cycle, winner
