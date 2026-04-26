from __future__ import annotations

import pandas as pd
from exchange.binance_client import BinanceClient


def fetch_ohlcv_df(client: BinanceClient, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    rows = client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    if not rows:
        raise ValueError(f"行情为空 {symbol} {timeframe}")
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df


def fetch_historical_range(client: BinanceClient, symbol: str, timeframe: str, since_ms: int, until_ms: int) -> pd.DataFrame:
    all_rows: list[list] = []
    cursor = since_ms
    while cursor < until_ms:
        batch = client.exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=1000)
        if not batch:
            break
        all_rows.extend(batch)
        cursor = batch[-1][0] + 1
        if len(batch) < 1000:
            break
    df = pd.DataFrame(all_rows, columns=["ts", "open", "high", "low", "close", "volume"])
    if df.empty:
        return df
    df = df[df["ts"] <= until_ms].drop_duplicates(subset=["ts"]).reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df
