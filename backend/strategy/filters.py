def volume_filter(curr: float, avg: float) -> bool:
    return curr >= avg


def atr_filter(curr: float, min_v: float, max_v: float) -> bool:
    return min_v <= curr <= max_v
