import io
import zipfile

import pandas as pd

from backtest.binance_vision import _parse_kline_zip, _raw_usdm_symbol


def _archive(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("BTCUSDT-1m-2026-08-01.csv", text)
    return buffer.getvalue()


def test_symbol_normalization_for_data_vision_paths():
    assert _raw_usdm_symbol("BTCUSDT") == "BTCUSDT"
    assert _raw_usdm_symbol("BTC/USDT") == "BTCUSDT"
    assert _raw_usdm_symbol("BTC/USDT:USDT") == "BTCUSDT"


def test_parse_data_vision_kline_uses_exchange_close_timestamp_and_skips_header():
    payload = _archive(
        "open_time,open,high,low,close,volume,close_time,quote_volume,trades,taker_base,taker_quote,ignore\n"
        "1785542400000,100.0,101.0,99.0,100.5,12.3,1785542459999,1234.5,42,6.1,612.0,0\n"
    )

    result = _parse_kline_zip(payload)

    assert len(result) == 1
    assert result.loc[0, "open"] == 100.0
    assert result.loc[0, "close"] == 100.5
    assert result.loc[0, "volume"] == 12.3
    assert result.loc[0, "timestamp"] == pd.to_datetime(1785542459999, unit="ms", utc=True)
