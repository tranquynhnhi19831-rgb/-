from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from exchange.testnet_gateway import BinanceTestnetGateway, TestnetCredentials


def run_acceptance(symbol: str, notional: float) -> dict:
    credentials = TestnetCredentials.from_env()
    gateway = BinanceTestnetGateway(credentials)
    report = {
        "stage": "S7_TESTNET_AUTH",
        "environment": "TESTNET",
        "mainnet_orders_supported": False,
        "credentials_configured": credentials.configured,
        "signed_order_test_creates_order": False,
        "passed": False,
    }
    if not credentials.configured:
        report["error"] = "BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_SECRET are not configured"
        return report

    try:
        report["account"] = gateway.authenticated_health()
        client_order_id = f"jh_s7test_{int(time.time())}"[:36]
        report["order_test"] = gateway.test_market_order(
            symbol=symbol,
            side="BUY",
            target_notional_usdt=notional,
            client_order_id=client_order_id,
            confirm="TESTNET_ORDER_TEST",
        )
        report["snapshot"] = gateway.account_snapshot()
        report["passed"] = True
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        report["error"] = str(exc)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Binance USD-M Testnet credentials without creating an order.")
    parser.add_argument("--symbol", default="ETH/USDT")
    parser.add_argument("--notional", type=float, default=10.0)
    parser.add_argument("--output", default="artifacts/s7_testnet_acceptance.json")
    args = parser.parse_args()

    report = run_acceptance(args.symbol, args.notional)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
