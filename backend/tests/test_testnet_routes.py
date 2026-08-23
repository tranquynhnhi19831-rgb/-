import pytest

from api.routes_testnet import _required


def test_demo_order_payloads_require_explicit_fields():
    with pytest.raises(ValueError, match="symbol"):
        _required({}, "symbol")
    with pytest.raises(ValueError, match="confirm"):
        _required({"confirm": ""}, "confirm")

    assert _required({"side": "BUY"}, "side") == "BUY"
