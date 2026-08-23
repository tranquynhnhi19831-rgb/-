from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp

    def to_dict(self) -> dict[str, str]:
        return {
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "test_start": self.test_start.isoformat(),
            "test_end": self.test_end.isoformat(),
        }


def build_walk_forward_windows(
    start: str,
    end: str,
    *,
    train_days: int = 21,
    test_days: int = 7,
    step_days: int = 7,
) -> list[WalkForwardWindow]:
    """Build chronological train/test windows with no overlap leakage.

    S6 does not silently optimize parameters yet. These windows are the hard
    boundary that later parameter-selection code must respect: any parameter
    selection uses only the train interval, while reported performance comes
    from the following test interval.
    """
    if min(train_days, test_days, step_days) < 1:
        raise ValueError("train_days/test_days/step_days must be >= 1")

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize("UTC")
    else:
        start_ts = start_ts.tz_convert("UTC")
    if end_ts.tzinfo is None:
        end_ts = end_ts.tz_localize("UTC")
    else:
        end_ts = end_ts.tz_convert("UTC")
    if end_ts <= start_ts:
        raise ValueError("end must be after start")

    train_delta = pd.Timedelta(days=train_days)
    test_delta = pd.Timedelta(days=test_days)
    step_delta = pd.Timedelta(days=step_days)
    windows: list[WalkForwardWindow] = []
    train_start = start_ts

    while True:
        train_end = train_start + train_delta
        test_start = train_end
        test_end = test_start + test_delta
        if test_end > end_ts:
            break
        windows.append(
            WalkForwardWindow(
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
        train_start = train_start + step_delta

    return windows
