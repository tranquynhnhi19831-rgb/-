import pandas as pd

from strategy.jianghe.strength import calculate_directional_strength, compare_strength


def strong_bullish_frame():
    return pd.DataFrame(
        {
            "open": [100, 102, 104, 106, 108, 110, 112, 114],
            "high": [103, 105, 107, 109, 111, 113, 115, 117],
            "low": [99, 101, 103, 105, 107, 109, 111, 113],
            "close": [102.5, 104.5, 106.5, 108.5, 110.5, 112.5, 114.5, 116.5],
        }
    )


def weak_overlapping_bullish_frame():
    return pd.DataFrame(
        {
            "open": [100.0, 100.6, 100.4, 100.9, 100.7, 101.0, 100.9, 101.1],
            "high": [101.5, 101.6, 101.5, 101.8, 101.7, 101.9, 101.8, 102.0],
            "low": [99.5, 99.8, 99.9, 100.0, 100.1, 100.2, 100.3, 100.4],
            "close": [100.7, 100.4, 100.9, 100.7, 101.0, 100.9, 101.1, 101.2],
        }
    )


def test_strong_directional_push_scores_above_overlapping_push():
    strong = calculate_directional_strength(strong_bullish_frame())
    weak = calculate_directional_strength(weak_overlapping_bullish_frame())

    assert strong.direction == 1
    assert weak.direction == 1
    assert strong.composite_score > weak.composite_score
    assert strong.directional_consistency > weak.directional_consistency
    assert strong.overlap_ratio < weak.overlap_ratio


def test_compare_strength_detects_weakening():
    strong = calculate_directional_strength(strong_bullish_frame())
    weak = calculate_directional_strength(weak_overlapping_bullish_frame())

    transition = compare_strength(strong, weak, min_delta=0.05)
    assert transition.state == "WEAKENING"
    assert transition.score_delta < 0
    assert not transition.direction_changed


def test_compare_strength_detects_direction_change():
    bullish = calculate_directional_strength(strong_bullish_frame())
    bearish_df = strong_bullish_frame().iloc[::-1].reset_index(drop=True).copy()
    # Reconstruct coherent bearish candles rather than relying on reversed OHLC bodies.
    bearish_df["open"] = [117, 115, 113, 111, 109, 107, 105, 103]
    bearish_df["high"] = [118, 116, 114, 112, 110, 108, 106, 104]
    bearish_df["low"] = [114, 112, 110, 108, 106, 104, 102, 100]
    bearish_df["close"] = [114.5, 112.5, 110.5, 108.5, 106.5, 104.5, 102.5, 100.5]
    bearish = calculate_directional_strength(bearish_df)

    transition = compare_strength(bullish, bearish)
    assert bearish.direction == -1
    assert transition.state == "DIRECTION_CHANGE"
    assert transition.direction_changed


def test_strength_features_are_explicitly_experimental_translation():
    snapshot = calculate_directional_strength(strong_bullish_frame())
    assert snapshot.evidence_grade == "D_EXPERIMENTAL_QUANT_TRANSLATION"
    assert 0 <= snapshot.composite_score <= 1
