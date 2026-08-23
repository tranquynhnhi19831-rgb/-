from __future__ import annotations

import csv
import io
import zipfile

import httpx
import pandas as pd

BASE_URL = "https://data.binance.vision/data/futures/um/daily/klines"
KLINE_COLUMNS = [
    "open_time_ms",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time_ms",
    "quote_volume",
    "trade_count",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
]


def _raw_usdm_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if ":" in value:
        value = value.split(":", 1)[0]
    return value.replace("/", "")


def _timestamp(value: str | int | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _parse_kline_zip(payload: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if not names:
            raise ValueError("Binance Data Vision archive is empty")
        with archive.open(names[0]) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8")
            rows: list[list[str]] = []
            for row in csv.reader(text):
                if not row or len(row) < 7:
                    continue
                try:
                    int(row[0])
                except (TypeError, ValueError):
                    # Some archive generations include a CSV header.
                    continue
                rows.append(row[:12])

    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    frame = pd.DataFrame(rows, columns=KLINE_COLUMNS)
    frame["open_time_ms"] = pd.to_numeric(frame["open_time_ms"], errors="raise")
    frame["close_time_ms"] = pd.to_numeric(frame["close_time_ms"], errors="raise")
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)
    frame["timestamp"] = pd.to_datetime(frame["close_time_ms"], unit="ms", utc=True)
    return frame[["timestamp", "open", "high", "low", "close", "volume"]]


def fetch_usdm_ohlcv_vision(
    symbol: str,
    timeframe: str,
    start: str | int | pd.Timestamp,
    end: str | int | pd.Timestamp,
    *,
    timeout_seconds: float = 30.0,
) -> pd.DataFrame:
    """Fetch official Binance USD-M daily kline archives from Data Vision.

    This path is intended for deterministic CI/research history. It avoids the
    production Futures REST host, which can be unavailable from some CI runner
    regions. The returned timestamp is the exchange-provided candle close time.
    """
    start_ts = _timestamp(start)
    end_ts = _timestamp(end)
    if end_ts <= start_ts:
        raise ValueError("end must be after start")

    raw_symbol = _raw_usdm_symbol(symbol)
    first_day = start_ts.floor("D")
    last_day = (end_ts - pd.Timedelta(nanoseconds=1)).floor("D")
    frames: list[pd.DataFrame] = []

    with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
        for day in pd.date_range(first_day, last_day, freq="D", tz="UTC"):
            date_text = day.strftime("%Y-%m-%d")
            filename = f"{raw_symbol}-{timeframe}-{date_text}.zip"
            url = f"{BASE_URL}/{raw_symbol}/{timeframe}/{filename}"
            response = client.get(url)
            if response.status_code == 404:
                raise ValueError(f"Binance Data Vision archive not found: {filename}")
            response.raise_for_status()
            frames.append(_parse_kline_zip(response.content))

    if not frames:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    result = pd.concat(frames, ignore_index=True)
    result = result.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
    result = result[(result["timestamp"] >= start_ts) & (result["timestamp"] < end_ts)]
    return result.reset_index(drop=True)
