from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EconomicViability:
    allowed: bool
    friction_to_planned_risk: float
    estimated_fees: float
    estimated_slippage_cost: float
    planned_risk: float
    planned_notional: float
    reason_code: str


def assess_round_trip_economics(
    *,
    entry_price: float,
    stop_price: float,
    quantity: float,
    side: str,
    reward_risk: float,
    fee_rate: float,
    slippage_bps: float,
    max_friction_to_risk: float,
) -> EconomicViability:
    """Pre-trade cost-vs-risk guard for small-account execution.

    With a 100U account and a hard notional cap, very tight 1m stops can make
    the actual planned stop risk tiny while two-sided fees/slippage stay tied to
    notional. A trade can therefore hit its nominal R target and still have most
    of the edge consumed by friction. We never increase size to fix this; the
    economically inefficient trade is skipped instead.

    The estimate is deliberately conservative and deterministic. It assumes an
    exit near the configured R target only to estimate the second-side notional;
    it is not a profitability forecast.
    """
    if entry_price <= 0 or stop_price <= 0 or quantity <= 0:
        raise ValueError("entry/stop/quantity must be positive")
    if side not in {"LONG", "SHORT"}:
        raise ValueError("side must be LONG or SHORT")
    if reward_risk <= 0:
        raise ValueError("reward_risk must be positive")
    if fee_rate < 0 or slippage_bps < 0:
        raise ValueError("fee/slippage must be non-negative")
    if not 0 < max_friction_to_risk < 1:
        raise ValueError("max_friction_to_risk must be in (0, 1)")

    stop_distance = abs(entry_price - stop_price)
    planned_risk = stop_distance * quantity
    if planned_risk <= 0:
        raise ValueError("planned risk must be positive")

    direction = 1.0 if side == "LONG" else -1.0
    target_price = entry_price + direction * reward_risk * stop_distance
    entry_notional = abs(entry_price * quantity)
    target_notional = abs(target_price * quantity)
    estimated_fees = (entry_notional + target_notional) * fee_rate

    slip_rate = slippage_bps / 10_000.0
    estimated_slippage_cost = (entry_notional + target_notional) * slip_rate
    friction = estimated_fees + estimated_slippage_cost
    ratio = friction / planned_risk
    allowed = ratio <= max_friction_to_risk

    return EconomicViability(
        allowed=allowed,
        friction_to_planned_risk=float(ratio),
        estimated_fees=float(estimated_fees),
        estimated_slippage_cost=float(estimated_slippage_cost),
        planned_risk=float(planned_risk),
        planned_notional=float(entry_notional),
        reason_code="OK" if allowed else "FRICTION_TOO_LARGE_VS_PLANNED_RISK",
    )
