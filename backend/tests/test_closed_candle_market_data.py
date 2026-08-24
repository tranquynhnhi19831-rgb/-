from __future__ import annotations

from services.market_data_service import BinanceDemoClosedCandleProvider, _normalize_ohlcv


class FakeExchange:
    def __init__(self, rows, now_ms=180_000):
        self.rows = rows
        self.now_ms = now_ms
        self.demo_enabled = False

    def enable_demo_trading(self, enabled):
        self.demo_enabled = bool(enabled)

    def milliseconds(self):
        return self.now_ms

    def fetch_ohlcv(self, symbol, timeframe, limit):
        return list(self.rows)


def test_normalize_drops_current_open_candle():
    rows = [
        [0, 100, 101, 99, 100.5, 10],
        [60_000, 100.5, 102, 100, 101.5, 11],
        [120_000, 101.5, 103, 101, 102.5, 12],
        [180_000, 102.5, 104, 102, 103.5, 13],
    ]
    # At t=180s, the candle opened at 120s has just closed. The candle opened
    # at 180s is still forming and must not be visible.
    frame = _normalize_ohlcv(rows, "1m", 180_000)
    assert len(frame) == 3
    assert float(frame.iloc[-1]["close"]) == 102.5


def test_provider_enables_demo_and_returns_only_closed_bars():
    rows = [
        [0, 100, 101, 99, 100.5, 10],
        [60_000, 100.5, 102, 100, 101.5, 11],
        [120_000, 101.5, 103, 101, 102.5, 12],
        [180_000, 102.5, 104, 102, 103.5, 13],
    ]
    exchange = FakeExchange(rows, now_ms=180_000)
    provider = BinanceDemoClosedCandleProvider(exchange=exchange)
    frame = provider.fetch_closed_ohlcv("BTC/USDT", "1m", limit=3)
    assert exchange.demo_enabled is True
    assert len(frame) == 3
    assert float(frame.iloc[-1]["close"]) == 102.5


def test_provider_rejects_symbol_outside_fixed_universe():
    provider = BinanceDemoClosedCandleProvider(exchange=FakeExchange([]))
    try:
        provider.fetch_closed_ohlcv("ARB/USDT", "1m", limit=10)
    except ValueError as exc:
        assert "outside fixed universe" in str(exc)
    else:
        raise AssertionError("expected fixed-universe validation failure")
