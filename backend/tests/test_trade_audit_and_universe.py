import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config import INITIAL_TRADING_UNIVERSE
from models.database import Base
from models.trade_decision import TradeDecision
from services.trade_audit_service import add_trade_decision, decode_json_field
from services.universe_scanner import CandidateIntent, audit_and_select_candidate, rank_candidates


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_initial_universe_is_fixed_top_seven_non_stable_assets():
    assert INITIAL_TRADING_UNIVERSE == (
        "BTC/USDT",
        "ETH/USDT",
        "XRP/USDT",
        "BNB/USDT",
        "SOL/USDT",
        "TRX/USDT",
        "HYPE/USDT",
    )


def test_candidate_ranking_uses_score_then_fixed_universe_order():
    candidates = [
        CandidateIntent("SOL/USDT", "PULLBACK", "LONG", 0.80, 100, 98),
        CandidateIntent("ETH/USDT", "PULLBACK", "LONG", 0.90, 100, 98),
        CandidateIntent("BTC/USDT", "BREAKOUT", "LONG", 0.90, 100, 98),
    ]

    ranked = rank_candidates(candidates)

    assert [c.symbol for c in ranked] == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


def test_audit_persists_all_qualified_candidates_and_one_selected_winner():
    db = _db()
    try:
        cycle_id, winner = audit_and_select_candidate(
            db,
            [
                CandidateIntent(
                    "BTC/USDT",
                    "TREND_PULLBACK_CONTINUATION",
                    "LONG",
                    0.81,
                    100.0,
                    98.0,
                    103.6,
                    ("BULL_TREND_CONTEXT", "PULLBACK_WEAKER_THAN_IMPULSE"),
                    {"context_efficiency": 0.42},
                ),
                CandidateIntent(
                    "SOL/USDT",
                    "BREAKOUT_CONTINUATION",
                    "LONG",
                    0.77,
                    50.0,
                    49.0,
                    51.8,
                    ("BREAKOUT_ACCEPTED",),
                    {"context_efficiency": 0.37},
                ),
            ],
            cycle_id="cycle-test-1",
        )

        assert cycle_id == "cycle-test-1"
        assert winner is not None
        assert winner.intent.symbol == "BTC/USDT"

        rows = db.query(TradeDecision).order_by(TradeDecision.id).all()
        assert len(rows) == 4
        assert [r.stage for r in rows] == ["CANDIDATE", "CANDIDATE", "ARBITRATION", "ARBITRATION"]

        selected = [r for r in rows if r.stage == "ARBITRATION" and r.selected]
        skipped = [r for r in rows if r.stage == "ARBITRATION" and not r.selected]
        assert len(selected) == 1
        assert selected[0].symbol == "BTC/USDT"
        assert selected[0].outcome == "SELECTED"
        assert len(skipped) == 1
        assert skipped[0].symbol == "SOL/USDT"
        assert skipped[0].outcome == "NOT_SELECTED"

        candidate = rows[0]
        assert "BULL_TREND_CONTEXT" in decode_json_field(candidate.reason_codes_json, [])
        assert decode_json_field(candidate.evidence_json, {})["context_efficiency"] == 0.42
    finally:
        db.close()


def test_audit_redacts_sensitive_fields_and_signature_query(monkeypatch):
    monkeypatch.setenv("BINANCE_TESTNET_API_KEY", "demo-key-value")
    monkeypatch.setenv("BINANCE_TESTNET_SECRET", "demo-secret-value")
    db = _db()
    try:
        row = add_trade_decision(
            db,
            cycle_id="redact-1",
            symbol="BTC/USDT",
            setup="TEST",
            side="LONG",
            stage="EXCHANGE_ORDER",
            outcome="REJECTED",
            evidence={
                "apiKey": "demo-key-value",
                "secret": "demo-secret-value",
                "nested": {"signature": "abc123", "safe": "keep-me"},
            },
            risk_message=(
                "request failed api=demo-key-value secret=demo-secret-value "
                "?symbol=BTCUSDT&signature=abcdef123456"
            ),
        )

        evidence = json.loads(row.evidence_json)
        assert evidence["apiKey"] == "[REDACTED]"
        assert evidence["secret"] == "[REDACTED]"
        assert evidence["nested"]["signature"] == "[REDACTED]"
        assert evidence["nested"]["safe"] == "keep-me"
        assert "demo-key-value" not in row.risk_message
        assert "demo-secret-value" not in row.risk_message
        assert "abcdef123456" not in row.risk_message
        assert "signature=[REDACTED]" in row.risk_message
    finally:
        db.close()


def test_outside_universe_candidate_is_rejected_before_audit():
    candidate = CandidateIntent("ARB/USDT", "PULLBACK", "LONG", 0.9, 1.0, 0.9)

    try:
        rank_candidates([candidate])
    except ValueError as exc:
        assert "outside fixed universe" in str(exc)
    else:
        raise AssertionError("expected fixed-universe validation failure")
