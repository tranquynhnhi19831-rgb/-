from __future__ import annotations

import ccxt
import pandas as pd


def _to_ms(value: str | int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    dt = pd.Timestamp(value)
    if dt.tzinfo is None:
        dt = dt.tz_localize("UTC")
    else:
        dt = dt.tz_convert("UTC")
    return int(dt.timestamp() * 1000)


def _normalize_usdm_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if ":" in value:
        return value
    if value.endswith("/USDT"):
        return f"{value}:USDT"
    if value.endswith("USDT") and "/" not in value:
        base = value[:-4]
        return f"{base}/USDT:USDT"
    return value


def fetch_usdm_ohlcv(
    symbol: str,
    timeframe: str,
    start: str | int,
    end: str | int,
    *,
    limit: int = 1500,
    max_bars: int = 100_000,
) -> pd.DataFrame:
    """Fetch Binance USDT-M public historical candles without API credentials.

    `timestamp` is the candle CLOSE time, not open time. This matters for
    multi-timeframe backtests: a higher-timeframe bar cannot be used until it
    has actually closed.
    """
    start_ms = _to_ms(start)
    end_ms = _to_ms(end)
    if start_ms is None or end_ms is None or end_ms <= start_ms:
        raise ValueError("end must be after start")
    if max_bars < 1:
        raise ValueError("max_bars must be >= 1")

    exchange = ccxt.binanceusdm({"enableRateLimit": True})
    market_symbol = _normalize_usdm_symbol(symbol)
    tf_seconds = exchange.parse_timeframe(timeframe)
    tf_ms = int(tf_seconds * 1000)
    cursor = start_ms
    rows: list[list[float]] = []
    exhausted_by_limit = False

    while cursor < end_ms:
        if len(rows) >= max_bars:
            exhausted_by_limit = True
            break
        batch = exchange.fetch_ohlcv(market_symbol, timeframe=timeframe, since=cursor, limit=limit)
        if not batch:
            break
        for row in batch:
            open_ms = int(row[0])
            if open_ms >= end_ms:
                break
            rows.append(row)
            if len(rows) >= max_bars:
                exhausted_by_limit = True
                break
        last_open = int(batch[-1][0])
        next_cursor = last_open + tf_ms
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if last_open >= end_ms - tf_ms:
            break

    if exhausted_by_limit and cursor < end_ms - tf_ms:
        raise ValueError(
            f"requested range exceeds max_bars={max_bars} for timeframe={timeframe}; split the backtest range"
        )

    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(rows, columns=["open_time_ms", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset=["open_time_ms"]).sort_values("open_time_ms")
    df = df[df["open_time_ms"] < end_ms].copy()
    df["timestamp"] = pd.to_datetime(df["open_time_ms"] + tf_ms, unit="ms", utc=True)
    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = df[column].astype(float)
    return df[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def fetch_usdm_funding_rates(
    symbol: str,
    start: str | int,
    end: str | int,
    *,
    limit: int = 1000,
) -> pd.DataFrame:
    """Fetch public Binance USDT-M funding history.

    Returned `funding_rate` follows the exchange convention: positive rates are
    paid by longs and received by shorts.
    """
    start_ms = _to_ms(start)
    end_ms = _to_ms(end)
    if start_ms is None or end_ms is None or end_ms <= start_ms:
        raise ValueError("end must be after start")

    exchange = ccxt.binanceusdm({"enableRateLimit": True})
    market_symbol = _normalize_usdm_symbol(symbol)
    cursor = start_ms
    rows: list[dict] = []
    while cursor < end_ms:
        batch = exchange.fetch_funding_rate_history(market_symbol, since=cursor, limit=limit)
        if not batch:
            break
        for item in batch:
            ts = int(item["timestamp"])
            if ts >= end_ms:
                break
            rows.append({"timestamp": pd.to_datetime(ts, unit="ms", utc=True), "funding_rate": float(item["fundingRate"])})
        last_ts = int(batch[-1]["timestamp"])
        if last_ts + 1 <= cursor:
            break
        cursor = last_ts + 1
        if last_ts >= end_ms:
            break

    if not rows:
        return pd.DataFrame(columns=["timestamp", "funding_rate"])
    return pd.DataFrame(rows).drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)


def attach_funding_rates(bars: pd.DataFrame, funding: pd.DataFrame) -> pd.DataFrame:
    """Attach each funding event to the first candle closing at/after the event."""
    result = bars.copy()
    result["funding_rate"] = 0.0
    if result.empty or funding.empty:
        return result

    bar_times = pd.to_datetime(result["timestamp"], utc=True)
    for row in funding.itertuples(index=False):
        event_time = pd.Timestamp(row.timestamp)
        index = bar_times.searchsorted(event_time, side="left")
        if index < len(result):
            result.loc[result.index[index], "funding_rate"] += float(row.funding_rate)
    return result
