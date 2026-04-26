def trend_score(
    ema_ok: bool,
    structure_ok: bool,
    volume_ok: bool,
    adx_ok: bool,
    atr_ok: bool,
    breakout_ok: bool,
) -> int:
    return (
        (20 if ema_ok else 0)
        + (25 if structure_ok else 0)
        + (15 if volume_ok else 0)
        + (15 if adx_ok else 0)
        + (10 if atr_ok else 0)
        + (15 if breakout_ok else 0)
    )
