import pandas as pd

from backtest.ablation import setup_ablation_cases
from backtest.binance_data import _normalize_usdm_symbol, attach_funding_rates
from backtest.jianghe_runner import ALL_SETUPS
from backtest.walk_forward import build_walk_forward_windows


def test_binance_usdm_symbol_normalization():
    assert _normalize_usdm_symbol("BTC/USDT") == "BTC/USDT:USDT"
    assert _normalize_usdm_symbol("btcusdt") == "BTC/USDT:USDT"
    assert _normalize_usdm_symbol("ETH/USDT:USDT") == "ETH/USDT:USDT"


def test_funding_is_attached_to_first_bar_closing_at_or_after_event():
    bars = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-01-01T00:01:00Z", "2026-01-01T00:02:00Z", "2026-01-01T00:03:00Z"],
                utc=True,
            ),
            "open": [100, 100, 100],
            "high": [101, 101, 101],
            "low": [99, 99, 99],
            "close": [100, 100, 100],
        }
    )
    funding = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-01-01T00:01:30Z"], utc=True),
            "funding_rate": [0.0001],
        }
    )
    result = attach_funding_rates(bars, funding)

    assert result["funding_rate"].tolist() == [0.0, 0.0001, 0.0]


def test_walk_forward_windows_never_overlap_train_with_following_test():
    windows = build_walk_forward_windows(
        "2026-01-01",
        "2026-02-20",
        train_days=21,
        test_days=7,
        step_days=7,
    )

    assert windows
    for window in windows:
        assert window.train_start < window.train_end
        assert window.train_end == window.test_start
        assert window.test_start < window.test_end
    assert all(windows[i].test_start < windows[i + 1].test_start for i in range(len(windows) - 1))


def test_setup_ablation_matrix_contains_full_and_single_setup_cases():
    cases = setup_ablation_cases()
    by_name = {case.name: case for case in cases}

    assert by_name["ALL_SETUPS"].enabled_setups == ALL_SETUPS
    assert len(by_name["ONLY_PULLBACK"].enabled_setups) == 1
    assert len(by_name["ONLY_BREAKOUT"].enabled_setups) == 1
    assert len(by_name["ONLY_SECOND_PUSH"].enabled_setups) == 1
    assert len(by_name["WITHOUT_PULLBACK"].enabled_setups) == 2
