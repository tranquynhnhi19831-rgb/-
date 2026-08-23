from __future__ import annotations

from dataclasses import dataclass

from backtest.jianghe_runner import SETUP_BREAKOUT, SETUP_PULLBACK, SETUP_SECOND_PUSH


@dataclass(frozen=True)
class AblationCase:
    name: str
    enabled_setups: tuple[str, ...]


def setup_ablation_cases() -> tuple[AblationCase, ...]:
    """Return a deterministic first-layer ablation matrix.

    This answers whether each whole setup family contributes incremental value.
    Feature/gate-level ablations (for example removing compression or micro
    reclaim) require explicit strategy-config toggles and are a later S6 layer.
    """
    all_setups = (SETUP_PULLBACK, SETUP_BREAKOUT, SETUP_SECOND_PUSH)
    return (
        AblationCase("ALL_SETUPS", all_setups),
        AblationCase("ONLY_PULLBACK", (SETUP_PULLBACK,)),
        AblationCase("ONLY_BREAKOUT", (SETUP_BREAKOUT,)),
        AblationCase("ONLY_SECOND_PUSH", (SETUP_SECOND_PUSH,)),
        AblationCase("WITHOUT_PULLBACK", (SETUP_BREAKOUT, SETUP_SECOND_PUSH)),
        AblationCase("WITHOUT_BREAKOUT", (SETUP_PULLBACK, SETUP_SECOND_PUSH)),
        AblationCase("WITHOUT_SECOND_PUSH", (SETUP_PULLBACK, SETUP_BREAKOUT)),
    )
