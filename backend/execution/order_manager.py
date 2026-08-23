class OrderManager:
    """Deprecated pre-S7 execution shim kept only for import compatibility.

    The historical implementation wrote a closed Trade and an open Position in
    the same call, which is an inconsistent ledger state. S7 uses the dedicated
    Local Paper engine and BinanceTestnetGateway instead. Fail closed here so a
    stale import can never mutate the trading database accidentally.
    """

    def execute(self, *args, **kwargs):
        raise RuntimeError(
            "legacy OrderManager is disabled: use services.trading_engine for Local Paper "
            "or exchange.testnet_gateway for Binance Demo execution"
        )
