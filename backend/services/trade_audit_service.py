from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

from sqlalchemy import desc

from models.trade_decision import TradeDecision

_SENSITIVE_KEY_PARTS = (
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "signature",
    "password",
    "private_key",
)


def new_cycle_id(prefix: str = "scan") -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def new_decision_id() -> str:
    return uuid.uuid4().hex


def safe_error_text(value: Any, max_length: int = 2000) -> str:
    """Redact credentials/signatures before an exchange error reaches SQLite."""
    text = str(value)
    for env_name in ("BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_SECRET"):
        secret = os.getenv(env_name, "")
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)(signature=)[^&\s]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(x-mbx-apikey[\"':=\s]+)[^,}\s]+", r"\1[REDACTED]", text)
    return text[:max_length]


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            name = str(key)
            lowered = name.lower()
            if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
                cleaned[name] = "[REDACTED]"
            else:
                cleaned[name] = _scrub(item)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [_scrub(item) for item in value]
    if isinstance(value, str):
        return safe_error_text(value)
    return value


def _json(value: Any, fallback: Any) -> str:
    if value is None:
        value = fallback
    return json.dumps(_scrub(value), ensure_ascii=False, sort_keys=True, default=str)


def add_trade_decision(
    db,
    *,
    cycle_id: str,
    symbol: str,
    stage: str,
    outcome: str,
    decision_id: str | None = None,
    setup: str = "",
    side: str = "",
    candidate: bool = False,
    selected: bool = False,
    score: float | None = None,
    entry_reference: float | None = None,
    stop_reference: float | None = None,
    target_reference: float | None = None,
    quantity: float | None = None,
    planned_risk_usdt: float | None = None,
    planned_notional_usdt: float | None = None,
    reason_codes: list[str] | tuple[str, ...] | None = None,
    evidence: dict[str, Any] | None = None,
    risk_code: str = "",
    risk_message: str = "",
    client_order_id: str = "",
    exchange_order_id: str = "",
    trade_id: int | None = None,
) -> TradeDecision:
    """Append one immutable decision-lifecycle event.

    The service performs a second defensive redaction pass even if callers
    accidentally include an exchange payload containing credentials/signatures.
    Strategy/risk/order metadata remains queryable; secrets do not.
    """

    row = TradeDecision(
        decision_id=decision_id or new_decision_id(),
        cycle_id=cycle_id,
        symbol=symbol,
        setup=setup,
        side=side,
        stage=stage,
        outcome=outcome,
        candidate=bool(candidate),
        selected=bool(selected),
        score=score,
        entry_reference=entry_reference,
        stop_reference=stop_reference,
        target_reference=target_reference,
        quantity=quantity,
        planned_risk_usdt=planned_risk_usdt,
        planned_notional_usdt=planned_notional_usdt,
        reason_codes_json=_json(reason_codes, []),
        evidence_json=_json(evidence, {}),
        risk_code=risk_code,
        risk_message=safe_error_text(risk_message),
        client_order_id=safe_error_text(client_order_id, max_length=256),
        exchange_order_id=safe_error_text(exchange_order_id, max_length=256),
        trade_id=trade_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def decision_id_for_trade(db, trade_id: int) -> str | None:
    row = (
        db.query(TradeDecision)
        .filter(TradeDecision.trade_id == trade_id)
        .order_by(desc(TradeDecision.id))
        .first()
    )
    return str(row.decision_id) if row else None


def decode_json_field(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback
