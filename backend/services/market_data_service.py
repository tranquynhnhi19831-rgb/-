import numpy as np
import pandas as pd


def fake_ohlcv(rows: int = 300, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base = np.cumsum(rng.normal(0, 1, rows)) + 100
    high = base + rng.normal(0.6, 0.2, rows)
    low = base - rng.normal(0.6, 0.2, rows)
    close = base + rng.normal(0, 0.3, rows)
    open_ = base + rng.normal(0, 0.3, rows)
    vol = rng.uniform(100, 500, rows)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol})
