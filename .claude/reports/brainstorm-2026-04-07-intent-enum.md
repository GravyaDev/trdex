# Multi-Agent Brainstorming — Intent Enum Refactor (Opzione 2)

**Date**: 2026-04-07
**Trigger**: Daniele identified that the runner long-only / signal-vs-close paradox is a critical architectural bug that must be fixed properly, not patched. Earlier in the day the WIP commit `815614d` had added the PortfolioService write path but the calling logic in AgentRunner did not exercise it (a `SELL` signal that should logically CLOSE an existing long position is blocked by Risk Gate 4 and never reaches the executor; the long-only PortfolioService refuses SELL fills as "open short").
**Disposition**: **APPROVED**
**Implementation status**: NOT YET STARTED — refactor scheduled for next session (~7h focused work)
**Related WIP commit**: `815614d` (`wip(portfolio): fill persistence + inspect_runs (calling logic still TODO)`)

---

## Scope

This brainstorming was a **stress-test** of the chosen design ("Opzione 2 — Intent enum"), not a re-decision between Opzione 2 and Opzione 4. The decision Opzione 2 vs Opzione 4 was made earlier in the same session, with explicit reasoning:

- **User's roadmap (Q3)**: trend-following parametric strategies for the next 3-6 months (SMA cross variants, RSI threshold, MACD divergence). All in the same family, all naturally compatible with close-on-opposite-signal policy.
- **Opzione 2 cost**: ~7 hours of focused work; extension-friendly toward future Opzione 4
- **Opzione 4 cost**: ~3-5 days; would block Phase 2 observation; requires architectural decisions that are better made *after* observation data is collected

The brainstorming was tasked with three goals:
1. Validate that Opzione 2 holds under Skeptic/Constraint Guardian/User Advocate stress
2. Design Opzione 2 in a way that is extension-friendly toward Opzione 4
3. Produce an explicit decision log

---

## The original bug

In live mode, the agent runner has a paradoxical behaviour:

```
Tick 1: signal=BUY, no position    → opens BTC/USDT long
Tick 2: signal=HOLD                → no-op
Tick 3: signal=SELL                → BLOCKED by Risk Gate 4 ("no pyramiding")
        → the position is NEVER closed by the agent
        → it can only exit via SL/TP/trailing/kill switch
```

Root cause: the system uses `BUY/SELL/HOLD` (3 values) to express 4 distinct intents (`OPEN_LONG`, `CLOSE_LONG`, `OPEN_SHORT`, `CLOSE_SHORT`). The meaning of "BUY" or "SELL" depends on portfolio state, but Risk Gate 4 doesn't know that — it blocks all signals when a position exists. Classic primitive obsession.

Consequence: backtest engine simulates close-on-opposite-signal (BUY opens, SELL closes); live agent simulates open-only-then-stops-handle-exits. The two policies diverge structurally, and no metric can be safely compared between them.

---

## Understanding Lock — confirmed answers

| Q | Question | Answer |
|---|---|---|
| **Q1** | Enum: 3 values (long-only) or 5 values (long+short)? | **5 values** — corrected after user noticed inconsistency in Designer's reasoning. Initial answer was "3 values for YAGNI", but the Designer also said "adding 2 more in the future is 1 line + tests". User pointed out: if it's 1 line, YAGNI doesn't apply. Designer admitted the "comodo" bias and switched to 5 values for semantic honesty + type-checker safety. |
| **Q2** | Translation lives in rule engine (Strada A) or in a separate function (Strada B)? | **Strada B** — single responsibility (rule engine ignores portfolio); decomposes the refactor cleanly. |
| **Q3** | Backtest engine adopts Intent (Strada β) or stays on `{-1, 0, 1}` (Strada α)? | **Strada α** — backtest is a single-policy in-memory sandbox; forcing Intent there would be ceremony without benefit. The "two worlds" (batch backtest vs concurrent live with persistent state) deserve different abstractions. |

The Q1 correction is documented separately because it was a meta-lesson: "comodo coincides with rational" should always trigger a verification. The user's question ("if it's 1 line, why create future debt?") was a process-quality check, not an indecision.

---

## Decision Log (24 numbered decisions, all accepted)

| # | Decision | Rationale |
|---|---|---|
| **D1** | Enum `Intent` with 5 values: `OPEN_LONG`, `CLOSE_LONG`, `OPEN_SHORT`, `CLOSE_SHORT`, `HOLD` | Semantic honesty; type-checker enforces exhaustive handling; ~0 cost; corrects YAGNI misapplication |
| **D2** | Enum lives in new module `agents/intent.py` | Separation of concerns; importable from risk and runner without cycles |
| **D3** | Helper boolean properties: `is_open`, `is_close`, `is_long`, `is_short` | Reduces repetitive match statements at call sites |
| **D4** (rev) | Translator signature: `signal_to_intent(signal: str, symbol: str, portfolio_ctx: PortfolioContext) -> Intent` | Skeptic S4: passing the symbol explicitly prevents misuse where the boolean has-position flag is computed for the wrong symbol |
| **D5** | `_rule_based_signal()` is **not** modified — returns BUY/SELL/HOLD as before; translation happens downstream in the Analyst node | Q2 Strada B: single responsibility (rule engine ignores portfolio state); decomposes the refactor; testable in isolation |
| **D6** | Backtest engine and `BacktestSMACross` continue using `pl.Series` of `{-1, 0, 1}` | Q3 Strada α: backtest has no shared persistent state; in-memory `in_position` is sufficient; DRY argument (only one engine instead of N strategies needs translation logic) |
| **D7** | Risk Gate 4 distinguishes OPEN from CLOSE: blocks only OPEN intents on existing positions | The core fix; allows SELL signals to close existing long positions instead of being blocked |
| ~~D8~~ | ~~New gate: CLOSE intent on no-position is blocked~~ | **REMOVED** — User Advocate U2: defensive code that never fires today; the translator's truth table prevents the case at the source. Eliminating the check reduces noise and test theatre. |
| **D9** | Runner method `_persist_open_fill` renamed to `_dispatch_fill` with switch on intent | Single point of decision = easier to test and reason about |
| **D10** | `PortfolioService` interface does **not** change to accept Intent | Reduces refactor cascade; the dispatch lives in the runner instead, calling either `record_open_fill(side="BUY")` or `record_close_fill(position=...)` |
| **D11** (rev) | DB schema: column `agent_runs.signal` keeps its name but stores Intent string values (`open_long`, `close_long`, ...). No migration. Backward compat is broken for historical queries. | Skeptic S7: avoids unscheduled migration debt. The current dataset is essentially empty (3 rows from smoke_level4) so the cost of breaking backward compat is trivial. |
| ~~D12~~ | ~~Future migration 010 to drop the old `signal` column~~ | **REMOVED** by D11 rev (no new column was added in the first place) |
| **D13** | `_record_close` re-reads the portfolio from the **live DB** at dispatch time, not from `state.portfolio` (which is a cached snapshot from cycle start) | Skeptic S1: prevents TOCTOU race with StopLossMonitor that may have closed the position between cycle start and dispatch |
| **D14** | If `_record_close` cannot find the position in the live DB, abort + write a structured `fill_orphan_warning` log entry | Skeptic S1: observability for the race-loss case |
| **D15** | `_dispatch_fill` docstring explicitly flags the residual risk that local DB and exchange state can diverge in live mode if persistence fails post-fill; flagged for future `fill_reconciliation` table | Skeptic S2: acknowledge the rare-but-real risk without scope creep into building reconciliation now |
| **D16** | In-flight position race between dispatch and next scheduler tick: documented as no-op today (interval=300s makes it impossible in practice) | Skeptic S5: accepted as theoretical, will revisit if interval ever drops below cycle duration |
| **D17** | `PortfolioService.record_close_fill` refactored for **single atomic commit**: position update + balance ledger insert in one transaction (today the WIP commits twice, leaving a window where positions.status='closed' but no trade_fill row) | Constraint Guardian G2: atomicity to prevent silent PnL loss on crash mid-write |
| **D18** | **Big bang refactor**: all 280 existing tests updated in the same commit. No compat layer, no `xfail`, no partial rollout. | Constraint Guardian G4: avoids the same kind of unscheduled debt that S7 just fixed |
| **D19** | Executor becomes **intent-aware**: for `CLOSE_LONG`/`CLOSE_SHORT` intents, it queries the DB for the position id and uses `close:{position.id}` as idempotency key (matching the StopLossMonitor's key) | Constraint Guardian G12: prevents double-close in live mode if agent and SL try to close the same position concurrently |
| **D20** | `PortfolioService.record_close_fill` accepts `closed_by: Literal["agent_signal", "stop_loss", "take_profit", "trailing_stop", "kill_switch"]` parameter; `inspect_runs.py` aggregates trade_fills by `closed_by` | User Advocate U3: gives Daniele observability over "did the agent close this, or did SL?" — essential to validate the fix |
| **D21** | `signal_to_intent` filters portfolio for `source='agent'` only; Telegram-opened positions are invisible to the translator | User Advocate U7: prevents the agent from closing positions opened by the Telegram tracker (cross-source contamination). Requires `PortfolioContext.open_position_symbols_by_agent` to be populated by `_load_portfolio_context()`. |
| **D22** | `inspect_runs.py` renames section 2 from "Signal distribution" to "Intent distribution"; section 4 shows breakdown by `closed_by` | User Advocate U1, U3: keep the dashboard meaningful after the schema semantic shift |
| **D23** | Double DB read in the close path (executor for idempotency key + `_record_close` for persistence) is **accepted** as trade-off of clarity vs optimisation; ~5ms overhead per close | Arbiter conflict resolution between S1 and G12 |
| **D24** | ORM model `agent_run_models.py` carries an explicit comment explaining the historical mismatch between the column name `signal` and the Intent values it now stores | Arbiter conflict resolution between D11 (rev) and U1: the schema name is historical, the semantic is new, the comment closes the gap for any future reader |

---

## Review summary

| Reviewer | Objections raised | Severity Alta | Status |
|---|---|---|---|
| Skeptic | 8 (S1-S8) | 2 (S1, S2) | All accepted; S3 verified, S5/S6/S7/S8 mitigated, S1/S2/S4 → D13/D15/D4 (rev) |
| Constraint Guardian | 12 (G1-G12) | 1 (G12) | G1, G6, G7, G8, G9, G11 OK; G2 → D17; G3 mitigated; G4 → D18; G5 explicit not new; G10 mitigated; G12 → D19 |
| User Advocate | 8 (U1-U8) | 1 (U7) | All accepted; U2 → eliminated D8; U3 → D20; U7 → D21; U1 → D22; U4 → commit message + KB; U5/U6/U8 in plan |

**Total**: 28 review points, 0 rejected, 0 unresolved.

### Conflict resolution

The Arbiter analysed 5 potential conflicts between accepted mitigations and resolved each:

1. **S2 vs G2** — no conflict; G2 covers atomicity *within* persistence, S2 covers the *pre-persistence* exchange-vs-local divergence
2. **S1 vs G12** — both require DB reads in the close path, but for different decisions (executor for idempotency, runner for persistence); accepted as D23 (double read)
3. **D11 (rev) vs U1** — the schema column name stays "signal", the report renames the dimension to "Intent"; resolved by D24 (explanatory ORM comment)
4. **U7 vs S1** — compatible: U7 filters at translation time, S1 verifies freshness at dispatch time; no overlap
5. **D18 vs G10** — G10 is a sub-vincolo of D18, both accepted

---

## End-to-end walk-through (verification that the bug is resolved)

Scenario: BTC/USDT, agent has previously opened a long position at 90000.

1. Agent cycle, `state.symbol = "BTC/USDT"`
2. `_load_portfolio_context()` loads `open_position_symbols_by_agent = ["BTC/USDT"]` (post-D21, filtered to source='agent')
3. Analyst node calls `_rule_based_signal(...)` → returns `("SELL", 0.6, "death cross detected")`
4. Analyst node calls `signal_to_intent("SELL", "BTC/USDT", portfolio_ctx)` → sees has-long=True for BTC/USDT → returns `Intent.CLOSE_LONG`
5. `state.analysis.intent = Intent.CLOSE_LONG`
6. Risk Gate 4: `intent.is_open = False` → does NOT block → approved
7. Executor: sees `intent == CLOSE_LONG` → queries DB for `position_id = 42` → constructs `idempotency_key = "close:42"` (D19) → calls `gateway.place(direction="SELL", ...)`
8. Gateway: simulator fills the order → `OrderResult(filled, ...)`
9. Runner `_dispatch_fill`: sees `intent == CLOSE_LONG` → calls `_record_close`
10. `_record_close`: re-reads DB live (D13), finds position 42, calls `PortfolioService.record_close_fill(position=42, exit_price=..., fee=..., closed_by="agent_signal")` (D20)
11. `record_close_fill`: in single transaction (D17) → updates `positions.status='closed'` + inserts `account_balance.amount=+pnl, note="agent close..."`
12. Next morning, `inspect_runs` shows: section 4 reports "1 trade closed by agent_signal" (D22)

**The bug is resolved end-to-end. The path is explicit, traceable, testable.**

---

## Extension-friendliness toward Opzione 4 (ExitPolicy)

When the user eventually wants strategies of structurally different families (mean reversion, breakout, momentum) and Opzione 4 becomes necessary, the assets from this refactor that survive:

- **Intent enum**: open vs close is a permanent distinction, independent of any exit policy
- **`signal_to_intent` translator**: can be invoked by `ExitPolicy.classify_exit_event(...)` or similar
- **`_dispatch_fill` switch**: the structure already separates open and close paths
- **`PortfolioService` open/close methods**: clear concepts that ExitPolicy will compose, not replace
- **Backtest engine** (untouched by Opzione 2): can extend its loop to apply SL/TP intra-bar without touching Intent vocabulary

The only thing Opzione 4 adds to today's design is **the logic of "when" to close** (parameters `stop_loss_pct`, `trailing_stop_pct`, `time_stop_bars`, etc.), which today lives in `StopLossMonitor` as global config and would become per-strategy or per-position. That change is **orthogonal** to Intent.

**Conclusion**: nothing built today will be discarded when Opzione 4 arrives.

---

## Test plan

### New tests (~13)

| File | Test | Purpose |
|---|---|---|
| `tests/agents/test_intent.py` | `test_intent_has_5_values` | Enum sanity |
| | `test_is_open_helpers` | Boolean helpers correctness |
| `tests/agents/test_signal_to_intent.py` | `test_buy_no_position_emits_open_long` | Truth table row 1 |
| | `test_buy_long_position_emits_hold_no_pyramiding` | Truth table row 2 |
| | `test_sell_long_position_emits_close_long_THE_FIX` | Truth table row 5 — the core fix |
| | `test_sell_no_position_emits_hold_no_shorting` | Truth table row 4 |
| | `test_hold_emits_hold` | Truth table row 7 |
| | `test_unknown_signal_raises` | Garbage input → ValueError |
| | `test_today_never_emits_short_intents` | **Pins the long-only policy of today** |
| | `test_filters_telegram_positions` | D21 — translator ignores source≠agent |
| `tests/agents/test_runner_dispatch.py` | `test_dispatch_open_long_calls_record_open` | Happy path open |
| | `test_dispatch_close_long_calls_record_close` | Happy path close |
| | `test_dispatch_close_long_aborts_if_position_not_in_live_db` | D13 race with SL |
| | `test_dispatch_short_intents_log_and_skip` | OPEN_SHORT/CLOSE_SHORT no-op |
| `tests/agents/test_risk_gate4.py` | `test_blocks_open_with_existing_agent_position` | Gate 4 OPEN block |
| | `test_allows_close_with_existing_agent_position` | Gate 4 CLOSE pass |
| `tests/agents/test_executor_close_intent.py` | `test_uses_position_id_as_idempotency_key_for_close` | D19 |

### Existing tests to update

Step 0 of the implementation: `grep -rn "\.signal" tests/ src/trdex/` to enumerate the actual call sites. Preliminary estimate: ~30-40 assertions across 5-6 files.

---

## Implementation estimate

| Phase | Time |
|---|---|
| Step 0: grep + enumerate `.signal` call sites | 15 min |
| Implementation: enum + translator + unit tests | 1h |
| Refactor: state.py + analyst.py + risk.py + runner.py + executor.py (with D17, D19, D21) | 2h |
| Refactor: PortfolioService.record_close_fill (D17 + D20) | 30 min |
| Update existing tests that reference `state.analysis.signal` | 1.5h |
| Refactor: inspect_runs.py (D22) | 30 min |
| End-to-end smoke level 4 verification | 30 min |
| Buffer for unforeseen issues | 1h |
| **Total** | **~7h focused work** |

---

## Operational recommendation

**Do not start implementation at the end of a long session.** This refactor requires sustained focus across multiple files and risks leaving the system in an inconsistent state if interrupted. Schedule it for the start of a fresh session.

When the implementation begins, the order matters:

1. Step 0 (grep) FIRST, before any code changes — gives accurate scope
2. Enum + translator + their unit tests (isolated, can be tested in isolation before any system change)
3. Refactor `state.py` (changes the type of `AnalysisResult.intent`) — this triggers the type checker to find all call sites
4. Follow the type checker errors, fixing one file at a time, in this order: analyst → risk → runner → executor → graph
5. PortfolioService.record_close_fill atomicity (D17) and `closed_by` (D20)
6. Update existing tests as the type checker complains
7. inspect_runs.py last (cosmetic, low risk)
8. End-to-end smoke level 4 to confirm the agent can now close positions

---

## Process meta-lesson

This brainstorming had a notable moment of self-correction. After Phase 1, the user asked: "If you didn't have to look at time but only at the real utility of the refactor, would you always choose the shorter path?" The Designer initially answered with "3 values for YAGNI" + "tomorrow it's 1 line to add 2 more". The user spotted the inconsistency: if it's 1 line tomorrow, why is it not worth doing today at zero cost?

The Designer admitted the bias (subconscious cost-cutting on test surface) and corrected to 5 values. This was a process-quality check, not technical indecision. The lesson: when "comfortable coincides with rational", stop and verify. The fact that the user caught it at Phase 0 — before any code was written — saved a real piece of future debt.

The Designer applied the same lens to Q2 and Q3 immediately after, looking for similar bias. Both held up under explicit re-examination, so they were confirmed.

---

## References

- **WIP commit**: `815614d` — `wip(portfolio): fill persistence + inspect_runs (calling logic still TODO)`
- **Bug discovery**: from `inspect_runs.py` first run on the smoke_level4 output, which showed agent_runs filled but account_balance and positions empty — the script that was meant to observe revealed an architectural gap
- **Prior commit** (Phase 1 of the day): `aaae052` — `feat: readiness gate v2, sharpe annualisation fix, scheduler smoke`
- **Earlier brainstorming** (BacktestSMACross design, same day): not committed as a separate report (the design was implemented immediately and lives in `src/trdex/strategy/backtest/sma_cross.py`)
