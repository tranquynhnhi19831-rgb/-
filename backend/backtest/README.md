# S6 Unified Backtest

S6 replaces the repository's original random-number backtest placeholder with a deterministic Binance USDT-M historical backtest path.

## Non-negotiable chronology

```text
current execution candle CLOSE
        ↓
candidate becomes known
        ↓
NEXT candle OPEN at earliest
        ↓
position simulation
```

Higher-timeframe candles use **close timestamps**. A 15m candle is unavailable to the 1m runner until the 15m candle has actually closed.

## Cost model

The first production-research assumptions are explicit and configurable:

- initial equity: `100 USDT`
- risk per trade: `0.5%`
- fee rate: `0.04%` each side by default (research assumption; configure for actual account tier/order type)
- adverse slippage: `2 bps` each fill by default
- leverage cap used for sizing: `3x`
- margin fraction: `10%` of equity
- optional Binance historical funding events
- same-bar stop/target ambiguity: `STOP_FIRST`
- adverse gap through stop: fill from the gap open, then apply slippage

These are **execution assumptions**, not Jianghe's own claimed parameters.

## Three setup families

`jianghe_runner.py` can evaluate independently or together:

- `TREND_PULLBACK_CONTINUATION`
- `BREAKOUT_CONTINUATION`
- `SECOND_PUSH_FAILURE`

The backtest API can enable any subset so each family can be evaluated independently before combining them.

## Public Binance history

`binance_data.py` uses public Binance USDT-M market/funding endpoints via CCXT. No private API key is required for S6 historical research.

The API route limits a single request to 31 days. Longer research should be split chronologically rather than silently truncating 1m history.

## Metrics

The engine returns at least:

- final equity / total return
- net PnL
- trades / wins / losses / win rate
- average win / average loss
- expectancy
- profit factor
- max drawdown
- max consecutive losses
- total fees
- total funding cost/credit
- per-setup metrics
- skipped overlapping signals

## Walk-forward

`walk_forward.py` creates hard chronological train/test windows. Parameter selection must only use the train interval; reported out-of-sample performance belongs to the following test interval.

S6 does **not** yet claim optimized parameters. The splitter exists first so later optimization cannot casually leak test data into training.

## Ablation

`ablation.py` currently provides setup-family ablations:

- all setups
- each setup alone
- all setups minus one family

Gate/feature-level ablations (e.g. removing breakout compression, removing micro reclaim, removing second-push speed comparison) require explicit config switches and are the next S6 refinement.

## What S6 does not prove

A profitable historical backtest does not prove live profitability. Before Mainnet the required sequence remains:

```text
S6 historical validation
→ Binance USDT-M Testnet
→ 24/7 cloud simulated execution
→ reconciliation / reconnect / idempotency / risk acceptance tests
→ 100U Mainnet
```
