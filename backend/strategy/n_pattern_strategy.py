import pandas as pd
from strategy.indicators import ema, atr, adx
from strategy.filters import volume_filter, atr_filter
from strategy.scoring import trend_score


def generate_signal(symbol: str, h1_df: pd.DataFrame, m15_df: pd.DataFrame) -> dict | None:
    if len(h1_df) < 220 or len(m15_df) < 100:
        return None

    h1_close = h1_df["close"]
    ema20 = ema(h1_close, 20).iloc[-1]
    ema60 = ema(h1_close, 60).iloc[-1]
    ema200 = ema(h1_close, 200).iloc[-1]
    last_price = h1_close.iloc[-1]

    trend_up = ema20 > ema60 and last_price > ema200
    trend_down = ema20 < ema60 and last_price < ema200

    m15_adx = adx(m15_df).iloc[-1]
    m15_atr = atr(m15_df).iloc[-1]
    avg_vol = m15_df["volume"].tail(30).mean()
    curr_vol = m15_df["volume"].iloc[-1]

    recent_high = m15_df["high"].tail(20).max()
    recent_low = m15_df["low"].tail(20).min()
    breakout_long = m15_df["close"].iloc[-1] >= recent_high
    breakout_short = m15_df["close"].iloc[-1] <= recent_low

    structure_ok = True
    vol_ok = volume_filter(curr_vol, avg_vol)
    adx_ok = m15_adx >= 18
    atr_ok = atr_filter(m15_atr, 0.0001, max(0.0002, m15_df["close"].iloc[-1] * 0.03))

    if trend_up and breakout_long:
        score = trend_score(True, structure_ok, vol_ok, adx_ok, atr_ok, True)
        if score >= 70:
            return {"symbol": symbol, "signal_type": "long", "score": score, "reason": "N字多头突破确认"}

    if trend_down and breakout_short:
        score = trend_score(True, structure_ok, vol_ok, adx_ok, atr_ok, True)
        if score >= 70:
            return {"symbol": symbol, "signal_type": "short", "score": score, "reason": "N字空头跌破确认"}

    return None
