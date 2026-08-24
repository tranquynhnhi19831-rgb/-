# Trade decision audit and fixed seven-symbol universe

## Initial universe

The initial autonomous scanner is intentionally fixed for reproducibility. As of
2026-08-24, after excluding stablecoins (USDT and USDC), the market-cap universe
is:

1. BTC/USDT
2. ETH/USDT
3. XRP/USDT
4. BNB/USDT
5. SOL/USDT
6. TRX/USDT
7. HYPE/USDT

The scanner evaluates all seven on each cycle. It must not stop at the first
symbol in the list. If multiple symbols qualify on the same closed-candle cycle,
all qualified intents are persisted and the highest strategy-quality score wins;
a tie is resolved by the fixed universe order. The global risk policy still
allows at most one open position.

Because exchange listings can change, `GET /api/testnet/universe-health` verifies
that every configured symbol resolves to an active linear USDT perpetual on the
Binance Demo environment. A partial universe fails the preflight instead of being
silently skipped.

## Why `trade_decisions` is separate from `trades`

`trades` can only describe an order that became a trade. Forensics also needs to
preserve attempts that never became trades: a valid strategy candidate can lose
arbitration to a better simultaneous candidate, be blocked by risk, fail exchange
filters, fail signed `/order/test`, or be rejected by Binance.

`trade_decisions` therefore stores an append-only lifecycle. The same
`decision_id` follows one intended trade through its stages. Typical stages are:

```text
CANDIDATE / QUALIFIED
ARBITRATION / SELECTED | NOT_SELECTED
RISK / ALLOWED | BLOCKED
ORDER_INTENT / READY | REQUESTED
ORDER_TEST / VALIDATED | REJECTED
EXCHANGE_ORDER / ACCEPTED | REJECTED
FILL / FILLED
EXIT_INTENT / REQUESTED
EXIT_ORDER / ACCEPTED | REJECTED
EXIT / CLOSED
```

Each record can contain setup, side, quality score, entry/stop/target, quantity,
planned risk/notional, machine-readable reason codes, strategy evidence, risk
code/message, client order id, exchange order id and trade id. API keys, secrets,
auth headers and confirmation secrets must never be stored in the evidence JSON.

Private forensic query endpoint:

```text
GET /api/audit/trade-decisions
```

Optional filters: `symbol`, `decision_id`, `stage`, `outcome`, and `limit`.

## Execution boundary

The scanner/coordinator only evaluates and selects a candidate. Selection is not
permission to trade. The selected candidate must still pass the global
`RiskManager`, Binance contract/filter preflight, idempotency/reconciliation and
the environment execution gate. In S7, autonomous Demo execution remains disabled
until the private health, universe preflight and `/fapi/v1/order/test` acceptance
sequence has passed.
