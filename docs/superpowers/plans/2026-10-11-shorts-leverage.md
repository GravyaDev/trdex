# Shorts and leverage — design

Status: implemented on `feat/shorts-leverage` (PR #18), stacked on #17.
Decisions by the operator (2026-10-11):
- live venue is Binance USDⓈ-M perpetuals;
- default max leverage is 3x, isolated margin, editable in the dashboard;
- this lands before the entry-confirmation work.

## Principles

- **Risk per trade does not change with leverage.**
  - Sizing stays risk-based: notional = `risk_per_trade / stop`, capped by `max_position_pct`.
  - Leverage only reduces the margin locked for that notional.
  - The portfolio risk budget (#17) is the real cap on what can be lost.
- **The danger that leverage adds is liquidation before the stop.**
  - Every leveraged entry is checked: the stop must sit well inside the liquidation distance.
  - The leverage applied to an entry is the largest one, up to the maximum, that satisfies this check.
- **One venue setting decides the mode.**
  - `thresholds.execution_venue = usdm` (default): every crypto position is a perpetual. Shorts are on, leverage is on, funding is charged.
  - `spot`: the previous behaviour — long-only, 1x, no funding.
- **One-way perp accounts net positions per symbol.** trdex therefore never holds opposite sides on the same symbol, whatever the source (agent, Telegram, manual).

## Formulas (`trdex.risk.leverage`)

Notation:
- `mmr` = `maintenance_margin_rate`, default 0.005, conservative for alts;
- `buffer` = `liquidation_buffer`, default 0.5.

Formulas:
- Liquidation distance, as a fraction of entry, isolated margin, fees ignored: `liq(L) = 1/L − mmr`.
- Leverage for an entry with stop distance `s`: `L = floor(min(max_leverage, 1 / (s/buffer + mmr)))`.
  - If `L < 1`, the entry is rejected: liquidation would come before the stop.
- With the defaults, 3x is allowed for stops up to 16.4 %, 2x up to 24.7 %, and 1x up to 49.7 %.
- Liquidation price: long `entry × (1 − liq(L))`; short `entry × (1 + liq(L))`.
- Margin: `notional / L`.
- Funding (simulation and backtest): `funding_rate_8h`, default 0.01 %.
  - It is charged at 00, 08 and 16 UTC on `qty × price`.
  - Longs pay and shorts receive when the rate is positive.

## Changes

| Area | Change |
|---|---|
| Intents | `signal_to_intent` gets `shorts`: SELL when flat → `OPEN_SHORT`; BUY with a short → `CLOSE_SHORT`; no flip within one cycle. |
| Analyst | Reads the venue; the prompt explains the signal semantics and the current position on the symbol. |
| Risk node | OPEN_SHORT only on `usdm`. Opposite-side guard (any source). Cluster cap counts the same direction. The leverage/liquidation gate sets `RiskDecision.leverage`. |
| Executor | OPEN_SHORT → SELL, CLOSE_SHORT → BUY; all closes `reduce_only`; leverage passed to the gateway. |
| Runner / PortfolioService | Records SELL opens with `leverage`; closes are already side-aware. |
| Migration 017 | `positions.venue` (old rows `spot`; closes are routed by it), `positions.leverage` (default 1) and `positions.funding_paid_until`. |
| StopLossMonitor | Already side-aware. Adds simulated liquidation and funding accrual (ledger `funding` events) on `usdm`. |
| Live | `LivePerpExecutor` through ccxt `binanceusdm`, with rate limiting. Isolated margin and leverage are set per symbol before the first order; closes are reduce-only; amounts use the exchange's precision. |
| Telegram | SELL signals open shorts on `usdm`, with the same leverage/liquidation gate, opposite-side guard and directional clusters. |
| Backtest | `EngineParams`: leverage, mmr, buffer, funding. Margin-based cash, liquidation capped at the margin, funding per 8h boundary. `LiveRuleEngine(shorts=True)` mirrors live. The refresher revalidates long and short together. |
| Dashboard | Venue and leverage settings; side, leverage, margin and liquidation price per position. |

## Known limits

- **Live funding and liquidations** happen on the exchange and are not reconciled into the ledger yet. This is the existing D15 gap, to be closed by fill reconciliation.
  - If a position is liquidated on the exchange, its reduce-only close fails and trips the kill switch, which is the safe outcome.
- **Funding rate**: simulation uses a fixed configurable rate, not the historical one.
- **Margin model**: tiered maintenance margin is approximated by one rate.
