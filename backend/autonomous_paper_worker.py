from __future__ import annotations

import asyncio
import os
import signal

from init_db import init_db
from models.database import SessionLocal
from services.autonomous_paper_runtime import AutonomousPaperRuntime


REQUIRED_CONFIRM = "RUN_AUTONOMOUS_PAPER_ONLY"


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


async def _main() -> None:
    if os.getenv("AUTONOMOUS_PAPER_CONFIRM", "").strip() != REQUIRED_CONFIRM:
        raise RuntimeError(f"explicit environment confirmation required: {REQUIRED_CONFIRM}")
    if _truthy("ENABLE_BINANCE_TESTNET_ORDERS"):
        raise RuntimeError("autonomous Paper worker refuses to start while Binance Demo order routes are enabled")

    init_db()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop(*_):
        loop.call_soon_threadsafe(stop_event.set)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_stop)
        except (NotImplementedError, RuntimeError):
            try:
                signal.signal(sig, request_stop)
            except (ValueError, OSError):
                pass

    runtime = AutonomousPaperRuntime()

    # Fail closed before acquiring the long-running worker lease. Paper is
    # required to monitor exactly the fixed seven-symbol universe; silently
    # degrading to six symbols because one contract is missing/inactive would
    # change both strategy opportunity set and arbitration semantics.
    runtime.provider.require_universe_health()

    await runtime.run_forever(db_factory=SessionLocal, stop_event=stop_event)


if __name__ == "__main__":
    asyncio.run(_main())
