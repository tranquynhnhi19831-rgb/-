from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from services.backtest_service import run_backtest

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


@router.post("/run")
def backtest(payload: dict):
    end_default = datetime.now(timezone.utc)
    start_default = end_default - timedelta(days=7)
    symbol = payload.get("symbol", "BTC/USDT")
    start = payload.get("start", start_default.isoformat())
    end = payload.get("end", end_default.isoformat())
    setups = tuple(payload.get("enabled_setups") or (
        "TREND_PULLBACK_CONTINUATION",
        "BREAKOUT_CONTINUATION",
        "SECOND_PUSH_FAILURE",
    ))

    try:
        return run_backtest(
            symbol,
            start,
            end,
            context_timeframe=payload.get("context_timeframe", "15m"),
            execution_timeframe=payload.get("execution_timeframe", "1m"),
            enabled_setups=setups,
            initial_equity=float(payload.get("initial_equity", 100.0)),
            risk_per_trade=float(payload.get("risk_per_trade", 0.005)),
            fee_rate=float(payload.get("fee_rate", 0.0004)),
            slippage_bps=float(payload.get("slippage_bps", 2.0)),
            reward_risk=float(payload.get("reward_risk", 1.5)),
            leverage=float(payload.get("leverage", 3.0)),
            max_margin_fraction=float(payload.get("max_margin_fraction", 0.10)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"historical backtest failed: {exc}") from exc
