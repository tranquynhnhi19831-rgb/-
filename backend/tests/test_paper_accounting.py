import pytest

from services.trading_engine import TradingEngine


def test_drawdown_uses_equity_peak_not_initial_capital():
    peak = 100.23082764550514
    current = 100.09557747043738

    drawdown = TradingEngine._drawdown_fraction(peak, current)

    assert drawdown == pytest.approx(0.00134938699245424)
    assert drawdown * 100 == pytest.approx(0.134938699245424)


def test_drawdown_is_zero_at_new_equity_high():
    assert TradingEngine._drawdown_fraction(100.0, 100.25) == 0.0


def test_drawdown_handles_nonpositive_peak_defensively():
    assert TradingEngine._drawdown_fraction(0.0, 99.0) == 0.0
