# TelegramSignalExecutor — Design Spec

**Date**: 2026-04-19
**Author**: Daniele + Kloud (session `.claude/session-timer.json`)
**Related Task Board items**: 2.1 (Symbol router), 2.2 (TelegramSignalExecutor), 2.3 (TG risk gates), 2.4 (SL adattato), 2.5 (Wire-up lifespan), 2.6 (Dashboard panel), 2.7 (Test simulation mode)
**Status**: approved — ready for implementation plan

## Objective

Promote Telegram signals from observe-only to actual trade execution, respecting the existing `TRDEX_MODE` pattern (`simulation` uses the simulator gateway; `live` uses the default gateway — same as every other trdex signal source). Fail-closed behind a RuntimeConfig flag, hot-reloadable from the dashboard.

## Context

Today:
- `src/trdex/telegram/parser.py` → `TelegramSignal` dataclass already parses messages into `(symbol, direction, entry, targets[], stop_loss)`.
- `src/trdex/telegram/monitor.py` → live stream.
- `src/trdex/api/app.py::_telegram_background` → ingests signals into Qdrant + records outcomes (`signal_outcomes` table) for observe-only. **No order placement.**
- `src/trdex/execution/` → `gateway.py` (abstract), `default_gateway.py` (Binance real), `simulator.py`, `live_executor.py`.
- `settings.telegram_signal_budget = 100.0` (quote currency per signal, `config.py:141`).
- `TRDEX_MODE` env var selects `simulation` vs `live`. Every existing signal source follows this contract.

Gap: no component translates a parsed Telegram signal into an executable order, applies risk gates, and writes the resulting position to the ledger with the signal's SL/TP attached. Task Board items 2.1–2.7 fill this gap.

## Non-goals (deferred)

These are out-of-scope for this spec. They live on the roadmap and will get their own spec when the upstream dependencies land:

- **Forex / commodity routing** — blocked on the Multi-asset Forex epic (Task Board section "Multi-asset Forex", OandaFeed + OandaExecutor). Symbol router raises `SymbolNotRoutable` for non-crypto symbols today.
- **Multiple take-profit scaling** — `signal.targets[1:]` ignored. Position uses `targets[0]` only.
- **Cancel / adjust on signal update** — if a channel posts a follow-up for the same signal, we do not mutate the open position. YAGNI until measured.
- **Binance Square signals integration** — separate signal source, separate executor. Different parser, different reliability tracking.
- **Limit orders with TTL** — entry drift gate (±0.5%) is the chosen compromise. Rejected limit-order approach because it adds pending-order lifecycle management (cancellation, race with close, TTL expiry) for marginal benefit.

## Architecture

### New files

| Path | Purpose |
|---|---|
| `src/trdex/execution/symbol_router.py` | `route(symbol) → (PriceFeed, Gateway)`. Today only crypto; forex/commodity raise `SymbolNotRoutable`. |
| `src/trdex/execution/telegram_executor.py` | Orchestrator: risk gates → price fetch → qty sizing → order placement → persistence. |
| `src/trdex/execution/telegram_gates.py` | Five pure gate functions. Each returns `GateResult(passed: bool, reason: str)`. Testable in isolation. |
| `migrations/017_telegram_signal_execution.sql` | Adds `executed_mode TEXT NULL` (`null` / `'simulation'` / `'live'`) to `signal_outcomes`. |
| `tests/execution/test_symbol_router.py` | Crypto routes correctly; forex raises. |
| `tests/execution/test_telegram_gates.py` | One test per gate (5) + happy path + ordering test. |
| `tests/execution/test_telegram_executor.py` | Integration: mock monitor → fake signal → assert position opened / skipped with expected reason. |
| `tests/execution/test_telegram_simulation.py` | End-to-end with `TRDEX_MODE=simulation`: position opened in simulator ledger, SL/TP from signal, outcome tracked, `executed_mode='simulation'` in DB. |

### Modified files

| Path | Change |
|---|---|
| `src/trdex/api/app.py::_telegram_background` | After observe-only record and dedup check, if `telegram_executor_enabled` is true, call `telegram_executor.execute(signal, session_factory)`. |
| `src/trdex/risk/stop_loss.py::_compute_stop_loss` | When `position.note` (JSON) has `source == 'telegram'` with `stop_loss` / `targets`, use those. Otherwise fallback to existing CV-adaptive SL. |
| `src/trdex/dashboard/app.py` (positions panel) | Add "Telegram" filter chip next to existing source filters. No new component. |
| `src/trdex/services/runtime_config.py` (or equivalent seed) | Register four new RuntimeConfig keys (see below). |

### Risk gates — order of precedence

Gates short-circuit on first failure. Ordering is intentional: cheapest checks first, external calls last.

1. **Position dedup** — `max 1 open position per (symbol, direction)`.
   Query: `positions WHERE symbol=? AND direction=? AND status='open' LIMIT 1`.
   Rationale: state-based is more robust than time-based. A second BUY on BTC from any channel while one is already open does not add pnl potential.

2. **Asset class cap** — `max 3 open per asset class`.
   Today only `crypto` counts. When forex lands, separate bucket.
   Query: `SELECT COUNT(*) FROM positions WHERE asset_class=? AND status='open'`.

3. **Budget** — `settings.telegram_signal_budget` must be available in the ledger.
   Hardcoded single-value today (no per-channel budget). Not hot-reload in this spec (lives in `settings`, not RuntimeConfig); see Open Questions.

4. **Reliability** — `win_rate(channel) >= reliability_win_rate_min` **only after** `reliability_min_samples` signals from the channel (observe + executed, both count).
   Query: `SELECT COUNT(*), AVG(CASE WHEN is_win = 1 THEN 1.0 ELSE 0 END) FROM signal_outcomes WHERE source_channel = ?`.
   Below sample threshold: pass-through (reliability unknown, not reliable-low).

5. **Entry drift** — if `signal.entry is not None`, require `abs(current_price - signal.entry) / signal.entry <= entry_drift_tolerance` (default 0.005 = 0.5%).
   If `signal.entry is None`: pass-through (at-market order).
   Fetches current price via `PriceFeedManager`, so this is the most expensive gate — intentionally last.

### Execution flow (after all gates pass)

1. Fetch current price from routed `PriceFeed`.
2. `qty = telegram_signal_budget / current_price` (quote currency budget ÷ current price).
3. Build `position.note` JSON:
   ```json
   {
     "source": "telegram",
     "channel": signal.source,
     "signal_id": <signal_outcomes.id>,
     "targets": signal.targets,
     "stop_loss": signal.stop_loss
   }
   ```
4. Call `gateway.place_order(symbol, direction, qty, market=True, note=json_note)`.
5. Write `signal_outcomes` row with `executed_mode = 'simulation'` or `'live'` matching `settings.mode`.
6. Log at INFO with channel, symbol, direction, qty, mode.

### SL/TP policy

- `stop_loss.py::_compute_stop_loss` reads `position.note` JSON.
- If `note.get('source') == 'telegram'`:
  - If `note.get('stop_loss') is not None` → use it. Else fall back to CV-adaptive.
  - If `note.get('targets')` is non-empty → TP = `targets[0]`. Else fall back to global TP (4%).
- The signal is the source of truth when present. Hybrid min/max logic rejected: it blurs what `signal_outcomes` measures (you want to measure the channel's performance as posted, not a watered-down version).

### Wire-up in lifespan

`_telegram_background` adds a conditional branch after dedup / observe-only record:

```python
if config_service.get_typed("integrations", "telegram_executor_enabled", False):
    try:
        await telegram_executor.execute(signal, session_factory)
    except Exception:
        logger.exception("[telegram] executor failed for %s %s from %s",
                         signal.direction, signal.symbol, signal.source)
```

Executor failure must NOT break the observe-only path. Exception is logged, signal_outcomes write already happened above.

### Dashboard change

Current `Open Positions` panel has source filter. Add `'telegram'` as a selectable value. `position.source = 'telegram'` is already written (app.py:63 shows `source="telegram_signal"` for Qdrant; for positions we'll use `'telegram'` — match existing convention in ledger). Zero new components.

## Data

### Migration 017 — `executed_mode` column on `signal_outcomes`

```sql
ALTER TABLE signal_outcomes
  ADD COLUMN IF NOT EXISTS executed_mode TEXT CHECK (executed_mode IN ('simulation', 'live'));

COMMENT ON COLUMN signal_outcomes.executed_mode IS
  'NULL = observe-only (no order placed). simulation = order placed in simulator gateway. live = order placed in live gateway.';

-- Index for reliability gate query
CREATE INDEX IF NOT EXISTS ix_signal_outcomes_source_channel
  ON signal_outcomes(source_channel);
```

Reliability gate query counts observe + simulation + live together — all three measure the channel's posted-signal performance. The `executed_mode` column is additive, not a gate.

### RuntimeConfig keys (new)

| Section | Key | Type | Default | Hot-reload | Purpose |
|---|---|---|---|---|---|
| `integrations` | `telegram_executor_enabled` | `bool` | `false` | ✅ | Master switch. If false, `_telegram_background` behaves exactly as today. |
| `telegram` | `entry_drift_tolerance` | `float` | `0.005` | ✅ | Max relative drift between `signal.entry` and `current_price` before skip. |
| `telegram` | `reliability_min_samples` | `int` | `20` | ✅ | Min signals per channel before reliability gate activates. |
| `telegram` | `reliability_win_rate_min` | `float` | `0.5` | ✅ | Reliability threshold once sample count is met. |

## Testing strategy

- **Unit (gates)**: each of the 5 gates in isolation. Dedicated test per failure reason + happy path.
- **Unit (router)**: crypto routes to `(PriceFeedManager, DefaultGateway)`; forex/commodity raises `SymbolNotRoutable`.
- **Unit (executor)**: mock gateway, mock feed, inject fake signal, assert happy path writes position with correct qty, note JSON, `executed_mode`.
- **Unit (stop_loss)**: `source='telegram'` note → signal SL used; `source='llm'` → CV-adaptive unchanged; malformed note → fallback.
- **Integration (Task 2.7)**: `TRDEX_MODE=simulation`, inject signal through `_telegram_background`, assert:
  - position exists in simulator ledger with `source='telegram'`
  - `position.note` JSON contains channel, targets, stop_loss
  - `signal_outcomes` row has `executed_mode='simulation'`
  - SL = signal.stop_loss, TP = signal.targets[0]
- **Integration (gate ordering)**: construct a scenario where multiple gates would fail and assert the first one in order is the reported reason.

## Error handling

- Gateway failures: caught in `_telegram_background`, logged, signal_outcomes already has the observe-only record. No retry (telegraphed: reliability gate will catch patterns).
- Price fetch failures in entry-drift gate: treat as skip with reason `"price unavailable"` (conservative — never execute without a sane current price).
- Malformed `position.note` in `stop_loss.py`: fallback to CV-adaptive + log warning (belt-and-suspenders; the executor owns the schema but a third party might mutate).

## Open questions / decisions captured

1. **Budget not hot-reload**. Today `telegram_signal_budget` lives in `settings` (env-driven). Moving to RuntimeConfig is an orthogonal refactor and is not part of this scope. Flagged for a future pass.
2. **Gate telemetry**. Skipped signals should be logged with reason for dashboard visibility. Spec captures this as log-only; if we need a gate-skip-count dashboard widget later, it's additive (read `signal_outcomes` + a new `skipped_reason` col, or rely on log scraping).
3. **Multiple TP evolution**. `targets[1:]` ignored today. If we later want scale-out, we'll need either (a) partial close orders at each target, or (b) a trailing SL that advances through targets. Captured as roadmap item.

## Rollout plan

1. Migration 017 applied on startup (lifespan already runs migrations).
2. `telegram_executor_enabled = false` in prod → zero behavior change, purely new code paths dormant.
3. Unit + integration tests pass (400+ baseline must stay green).
4. Flip flag to `true` in simulation first. Observe for N days (budget $100/signal × expected volume; small enough that $ burn is trivial).
5. Flip to live only after simulation mode shows reliability-gated channels produce net-positive outcomes.

## Success criteria

- Zero regressions in existing observe-only flow (`telegram_executor_enabled = false`).
- When `true`, signals that pass all 5 gates open positions in the correct gateway (simulator in `simulation`, Binance in `live`).
- SL/TP on these positions match the signal's `stop_loss` / `targets[0]`.
- `signal_outcomes.executed_mode` populated correctly.
- Dashboard "Telegram" filter surfaces these positions with the standard columns + close-now.
