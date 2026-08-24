import pytest

from execution.order_manager import OrderManager


def test_legacy_order_manager_fails_closed_before_any_database_write():
    with pytest.raises(RuntimeError, match="legacy OrderManager is disabled"):
        OrderManager().execute(None, None, None, 0, 0, 0, 0, "", "")
