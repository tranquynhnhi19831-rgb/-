from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_UP


class OrderRuleError(ValueError):
    """Raised when an order cannot satisfy the exchange market rules."""


@dataclass(frozen=True)
class MarketRules:
    symbol: str
    min_amount: float | None = None
    max_amount: float | None = None
    amount_step: float | None = None
    min_notional: float | None = None
    price_tick: float | None = None


def _d(value: float) -> Decimal:
    return Decimal(str(value))


def ceil_to_step(value: float, step: float | None) -> float:
    """Round a positive value up to the next exchange step size."""
    if value <= 0:
        raise OrderRuleError("quantity must be greater than zero")
    if not step or step <= 0:
        return float(value)

    units = (_d(value) / _d(step)).to_integral_value(rounding=ROUND_UP)
    return float(units * _d(step))


def normalize_order_quantity(
    requested_quantity: float,
    price: float,
    rules: MarketRules,
) -> float:
    """Return the smallest valid quantity that is at least the requested size.

    The function is deliberately pure so it can be unit tested without a live
    Binance connection. It enforces amount step/minimum and minimum notional.
    """
    if requested_quantity <= 0:
        raise OrderRuleError("requested quantity must be greater than zero")
    if price <= 0:
        raise OrderRuleError("price must be greater than zero")

    minimum = rules.min_amount or 0.0
    if rules.min_notional:
        minimum = max(minimum, rules.min_notional / price)

    quantity = ceil_to_step(max(requested_quantity, minimum), rules.amount_step)

    # A floating-point conversion can leave the notional microscopically below
    # the exchange minimum. Add one step if needed.
    if rules.min_notional and quantity * price + 1e-12 < rules.min_notional:
        step = rules.amount_step or quantity * 1e-9
        quantity = ceil_to_step(quantity + step, rules.amount_step)

    if rules.max_amount and quantity > rules.max_amount + 1e-12:
        raise OrderRuleError(
            f"normalized quantity {quantity} exceeds max amount {rules.max_amount}"
        )

    return quantity
