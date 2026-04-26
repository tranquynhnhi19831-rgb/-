from __future__ import annotations

from datetime import datetime, UTC
import pandas as pd
from strategy.indicators import ema, atr, adx
from strategy.filters import volume_filter, atr_filter
from strategy.scoring import trend_score


def _n_long_structure(m15: pd.DataFrame) -> tuple[bool, float, float, float]:
    window = m15.tail(60).reset_index(drop=True)
    pivot_high = window["high"].iloc[10:30].max()
    pullback_low = window["low"].iloc[30:45].min()
    breakout = float(window["close"].iloc[-1])
    first_leg = pivot_high - float(window["low"].iloc[10])
    valid = first_leg > 0 and pullback_low > float(window["low"].iloc[10]) and breakout > pivot_high
    return valid, breakout, pullback_low, pivot_high


def _n_short_structure(m15: pd.DataFrame) -> tuple[bool, float, float, float]:
    window = m15.tail(60).reset_index(drop=True)
    pivot_low = window["low"].iloc[10:30].min()
    rebound_high = window["high"].iloc[30:45].max()
    breakdown = float(window["close"].iloc[-1])
    first_leg = float(window["high"].iloc[10]) - pivot_low
    valid = first_leg > 0 and rebound_high < float(window["high"].iloc[10]) and breakdown < pivot_low
    return valid, breakdown, rebound_high, pivot_low


def generate_signal(symbol: str, h1_df: pd.DataFrame, m15_df: pd.DataFrame) -> dict | None:
    if len(h1_df) < 240 or len(m15_df) < 120:
        return None

    h1_close = h1_df["close"]
    ema20 = ema(h1_close, 20).iloc[-1]
    ema60 = ema(h1_close, 60).iloc[-1]
    ema200 = ema(h1_close, 200).iloc[-1]
    h1_adx = adx(h1_df).iloc[-1]
    h1_atr = atr(h1_df).iloc[-1]
    last_price = float(h1_close.iloc[-1])

    trend_up = ema20 > ema60 and last_price > ema200 and h1_adx >= 18
    trend_down = ema20 < ema60 and last_price < ema200 and h1_adx >= 18

    m15_adx = adx(m15_df).iloc[-1]
    m15_atr = atr(m15_df).iloc[-1]
    avg_vol = float(m15_df["volume"].tail(30).mean())
    curr_vol = float(m15_df["volume"].iloc[-1])
    vol_ok = volume_filter(curr_vol, avg_vol)
    atr_ok = atr_filter(m15_atr, 0.0001, max(0.0002, last_price * 0.04)) and atr_filter(h1_atr, 0.0001, max(0.0002, last_price * 0.08))
    adx_ok = m15_adx >= 18

    if trend_up:
        structure_ok, entry, stop_loss, pivot = _n_long_structure(m15_df)
        take_profit = entry + 2 * (entry - stop_loss)
        rr = (take_profit - entry) / max(entry - stop_loss, 1e-9)
        score = trend_score(True, structure_ok, vol_ok, adx_ok, atr_ok, entry > pivot)
        if structure_ok and score >= 70 and rr >= 1.5:
            return {
                "symbol": symbol,
                "side": "long",
                "entry": float(entry),
                "stop_loss": float(stop_loss),
                "take_profit": float(take_profit),
                "rr": float(rr),
                "score": float(score),
                "reason": "1H上升趋势 + 15m N字突破 + 成交量确认",
                "timeframe": "1h/15m",
                "created_at": datetime.now(UTC).isoformat(),
            }

    if trend_down:
        structure_ok, entry, stop_loss, pivot = _n_short_structure(m15_df)
        take_profit = entry - 2 * (stop_loss - entry)
        rr = (entry - take_profit) / max(stop_loss - entry, 1e-9)
        score = trend_score(True, structure_ok, vol_ok, adx_ok, atr_ok, entry < pivot)
        if structure_ok and score >= 70 and rr >= 1.5:
            return {
                "symbol": symbol,
                "side": "short",
                "entry": float(entry),
                "stop_loss": float(stop_loss),
                "take_profit": float(take_profit),
                "rr": float(rr),
                "score": float(score),
                "reason": "1H下降趋势 + 15m N字跌破 + 成交量确认",
                "timeframe": "1h/15m",
                "created_at": datetime.now(UTC).isoformat(),
            }
    return None
