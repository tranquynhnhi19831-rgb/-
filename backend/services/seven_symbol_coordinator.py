from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from time import monotonic
from typing import Awaitable, Callable

from config import INITIAL_TRADING_UNIVERSE
from services.universe_scanner import AuditedCandidate, CandidateIntent, audit_and_select_candidate

Evaluator = Callable[[str], CandidateIntent | None | Awaitable[CandidateIntent | None]]
Executor = Callable[[AuditedCandidate], object | Awaitable[object]]


@dataclass(frozen=True)
class ScanResult:
    cycle_id: str
    scanned_symbols: tuple[str, ...]
    candidate_count: int
    selected: AuditedCandidate | None


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


class SevenSymbolScanCoordinator:
    """Evaluate the fixed seven-symbol universe on every scan cycle.

    Synchronous evaluators (for example CCXT REST market-data reads) run in
    worker threads so one slow symbol cannot serialize the whole universe scan.
    Async evaluators run directly. All qualified candidates are audited before
    deterministic global arbitration.
    """

    universe = INITIAL_TRADING_UNIVERSE

    async def scan_once(self, db, evaluator: Evaluator) -> ScanResult:
        async def evaluate(symbol: str):
            if inspect.iscoroutinefunction(evaluator):
                return await evaluator(symbol)
            value = await asyncio.to_thread(evaluator, symbol)
            return await _maybe_await(value)

        evaluated = await asyncio.gather(*(evaluate(symbol) for symbol in self.universe))
        candidates = [item for item in evaluated if item is not None]
        cycle_id, selected = audit_and_select_candidate(db, candidates)
        return ScanResult(
            cycle_id=cycle_id,
            scanned_symbols=self.universe,
            candidate_count=len(candidates),
            selected=selected,
        )

    async def run_forever(
        self,
        *,
        db_factory,
        evaluator: Evaluator,
        executor: Executor,
        stop_event: asyncio.Event,
        cadence_seconds: float = 60.0,
    ) -> None:
        """Run closed-candle scan cycles until explicitly stopped.

        The default cadence is one minute. The real-time evaluator is responsible
        for exposing only fully closed 1m/15m/1h candles, preserving the no-
        lookahead convention used in backtests. This loop is infrastructure only;
        S7 does not auto-start it until Paper/Demo acceptance is complete.
        """
        if cadence_seconds <= 0:
            raise ValueError("cadence_seconds must be > 0")

        while not stop_event.is_set():
            started = monotonic()
            db = db_factory()
            try:
                result = await self.scan_once(db, evaluator)
                if result.selected is not None:
                    await _maybe_await(executor(result.selected))
            finally:
                db.close()

            elapsed = monotonic() - started
            wait_seconds = max(0.0, cadence_seconds - elapsed)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=wait_seconds)
            except asyncio.TimeoutError:
                pass
