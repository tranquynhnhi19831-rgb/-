from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import ccxt
import numpy as np
import pandas as pd

from config import INITIAL_TRADING_UNIVERSE

TIMEFRAME_MS = {
    "1m": 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
}


def _proxy_config_from_env() -> dict[str, str]:
    http_proxy = (os.getenv("HTTP_PROXY") or os.getenv("http_proxy") or "").strip()
    https_proxy = (os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or "").strip()
    if not http_proxy and not https_proxy:
        return {}
    if not http_proxy:
        http_proxy = https_proxy
    if not https_proxy:
        https_proxy = http_proxy
    return {"http": http_proxy, "https": https_proxy}


def _utc_now_ms() -> int:
    return int(time.time() * 1000)


def _normalize_ohlcv(rows: list[list[Any]], timeframe: str, now_ms: int) -> pd.DataFrame:
    if timeframe not in TIMEFRAME_MS:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    width = TIMEFRAME_MS[timeframe]
    normalized = []
    for row in rows or []:
        if len(row) < 6:
            continue
        open_ms = int(row[0])
        close_ms = open_ms + width
        # Never expose an in-progress candle to a strategy. A candle is usable
        # only after its full interval has elapsed.
        if close_ms > int(now_ms):
            continue
        normalized.append(
            {
                "timestamp": pd.to_datetime(close_ms, unit="ms", utc=True),
                "open_time": pd.to_datetime(open_ms, unit="ms", utc=True),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
        )

    frame = pd.DataFrame(
        normalized,
        columns=["timestamp", "open_time", "open", "high", "low", "close", "volume"],
    )
    if frame.empty:
        return frame
    frame = frame.drop_duplicates(subset=["open_time"], keep="last").sort_values("open_time").reset_index(drop=True)
    numeric = frame[["open", "high", "low", "close", "volume"]]
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise RuntimeError("market data contains non-finite OHLCV values")
    if (frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any():
        raise RuntimeError("market data contains invalid high values")
    if (frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any():
        raise RuntimeError("market data contains invalid low values")
    return frame


@dataclass(frozen=True)
class MultiTimeframeBars:
    symbol: str
    macro_1h: pd.DataFrame
    context_15m: pd.DataFrame
    execution_1m: pd.DataFrame

    @property
    def latest_execution_close(self):
        if self.execution_1m.empty:
            return None
        return self.execution_1m["timestamp"].iloc[-1]


class BinanceDemoClosedCandleProvider:
    """Public Binance USD-M Demo market-data provider.

    This class intentionally has no credentials and no order methods. It uses
    Binance Demo Trading public endpoints so autonomous Paper can be developed
    without creating an execution path. Every returned bar is fully closed.
    """

    def __init__(self, exchange: Any | None = None) -> None:
        if exchange is None:
            config: dict[str, Any] = {
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
            }
            proxies = _proxy_config_from_env()
            if proxies:
                config["proxies"] = proxies
            exchange = ccxt.binanceusdm(config)
        self.exchange = exchange
        enable_demo = getattr(self.exchange, "enable_demo_trading", None)
        if enable_demo is None:
            raise RuntimeError("CCXT build does not support Binance Demo Trading")
        enable_demo(True)

    def _now_ms(self) -> int:
        fn = getattr(self.exchange, "milliseconds", None)
        return int(fn()) if callable(fn) else _utc_now_ms()

    def fetch_closed_ohlcv(self, symbol: str, timeframe: str, *, limit: int) -> pd.DataFrame:
        if symbol not in INITIAL_TRADING_UNIVERSE:
            raise ValueError(f"symbol outside fixed universe: {symbol}")
        if timeframe not in TIMEFRAME_MS:
            raise ValueError(f"unsupported timeframe: {timeframe}")
        if limit < 2:
            raise ValueError("limit must be >= 2")

        # Request a small cushion because the exchange commonly includes the
        # currently forming candle, which is removed below.
        rows = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit + 2)
        frame = _normalize_ohlcv(rows, timeframe, self._now_ms())
        if len(frame) > limit:
            frame = frame.tail(limit).reset_index(drop=True)
        return frame

    def fetch_multitimeframe(
        self,
        symbol: str,
        *,
        macro_limit: int = 120,
        context_limit: int = 120,
        execution_limit: int = 80,
    ) -> MultiTimeframeBars:
        return MultiTimeframeBars(
            symbol=symbol,
            macro_1h=self.fetch_closed_ohlcv(symbol, "1h", limit=macro_limit),
            context_15m=self.fetch_closed_ohlcv(symbol, "15m", limit=context_limit),
            execution_1m=self.fetch_closed_ohlcv(symbol, "1m", limit=execution_limit),
        )


def fake_ohlcv(rows: int = 300, seed: int = 42) -> pd.DataFrame:
    """Deterministic synthetic fixture retained only for unit tests/dev smoke."""
    rng = np.random.default_rng(seed)
    base = np.cumsum(rng.normal(0, 1, rows)) + 100
    high = base + rng.normal(0.6, 0.2, rows)
    low = base - rng.normal(0.6, 0.2, rows)
    close = base + rng.normal(0, 0.3, rows)
    open_ = base + rng.normal(0, 0.3, rows)
    vol = rng.uniform(100, 500, rows)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol})
