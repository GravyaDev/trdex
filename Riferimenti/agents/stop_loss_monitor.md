---
doc_id: kb_stop_loss_monitor
agent: stop_loss_monitor
version: 1.0
last_updated: 2026-04-06
purpose: |
  Knowledge base completa e autosufficiente per lo Stop-Loss Monitor di trdex.
  Lo Stop-Loss Monitor è ESTERNO al ciclo agente AI: è un background daemon
  rule-based che protegge il capitale indipendentemente dalle decisioni dell'LLM.
  Contiene SOLO i blocchi rilevanti per questo componente.
sources:
  - notebook_id: 23eff711-d90f-4575-9a2f-5d1244681d9e
schema:
  HARD: "Regole immutabili"
  PARAM: "Parametri configurabili"
  HEUR: "Euristiche evolvibili"
---

# Stop-Loss Monitor Knowledge Base

> Lo Stop-Loss Monitor è la **safety net hardware** di trdex.
> È un background daemon che gira indipendentemente dal ciclo Scout→Analyst→Risk→Executor.
> Le sue regole sono **rule-based puro**, mai influenzate da LLM o segnali dell'Analyst.
> Quando una condizione di stop scatta, agisce **immediatamente** via gateway diretto.

---

## 1 — IDENTITÀ E FILOSOFIA

### `HARD-MONITOR-MIND-001` — External Safety Net Principle
**Tags**: `mindset, safety_net`

```yaml
principle: |
  Sono ESTERNO all'AI. Sono la rete di sicurezza di ultima istanza.
  Le mie regole sono pure logica matematica.
  Non sono influenzato dal "ragionamento" dell'Analyst.
  Non posso essere disabilitato dall'agente AI.
hard_constraint: |
  Mai chiedere al LLM cosa fare.
  Mai negoziare con i parametri di SL.
  Mai accettare override "intelligenti".
```

### `HARD-MONITOR-MIND-002` — Negative Constraints
**Tags**: `prohibited_actions`

```json
{
  "prohibited_actions": [
    "skip_check_cycle",
    "ignore_stop_threshold",
    "let_position_recover_past_threshold",
    "wait_for_market_to_turn_around",
    "manually_widen_threshold_at_runtime",
    "consult_LLM_for_decisions"
  ]
}
```

---

## 2 — RUOLO OPERATIVO

### `HARD-MONITOR-001` — Scope of Work
**Tags**: `scope, role`

```yaml
component: stop_loss_monitor
type: background_daemon
runs_independently_of: [scout, analyst, risk_manager, executor]

inputs:
  - session_factory: DB session
  - feed_manager: PriceFeedManager (live prices)
  - gateway: DefaultExecutionGateway (per auto-close)
  - kill_switch: KillSwitch instance

check_interval_seconds: 30  # configurable

stop_conditions:
  - position_stop_loss
  - position_take_profit
  - trailing_stop
  - daily_drawdown
  - max_drawdown

allowed_actions:
  - read open positions from DB
  - fetch live prices via feed_manager
  - call gateway.place() to auto-close positions
  - activate kill_switch on portfolio-level breach
  - log events
  - persist event history

forbidden_actions:
  - call LLM
  - read agent_runs (no signal logic)
  - influence Analyst's decisions
```

---

## 3 — STOP CONDITIONS

### `HARD-MONITOR-002` — Position Stop-Loss
**Tags**: `stop_loss, per_position`

```yaml
condition: position_stop_loss
trigger: "pnl_pct <= -position_sl_pct"
default_threshold: 0.05  # -5% per posizione (PARAM-MONITOR-001)

formula:
  buy_position: "pnl_pct = (current_price - entry_price) / entry_price"
  sell_position: "pnl_pct = (entry_price - current_price) / entry_price"

action_sequence:
  1: "fire StopLossEvent (POSITION_STOP_LOSS)"
  2: "log critical message"
  3: "call _auto_close(position, current_price, 'stop_loss')"
```

### `HARD-MONITOR-003` — Position Take-Profit
**Tags**: `take_profit, per_position`

```yaml
condition: position_take_profit
trigger: "pnl_pct >= position_tp_pct"
default_threshold: 0.10  # +10% per posizione (PARAM-MONITOR-001)

action_sequence:
  1: "fire StopLossEvent (POSITION_TAKE_PROFIT)"
  2: "log info message"
  3: "call _auto_close(position, current_price, 'take_profit')"
```

### `HARD-MONITOR-004` — Trailing Stop
**Tags**: `trailing_stop, hwm`

```yaml
condition: trailing_stop
algorithm: high_water_mark_retracement

state_per_position:
  position_id: int
  hwm: float  # high-water mark (BUY) o low-water mark (SELL)

logic:
  buy_position:
    update_hwm: "if current_price > hwm: hwm = current_price"
    trigger: "(hwm - current_price) / hwm >= trailing_pct"
  sell_position:
    update_lwm: "if current_price < lwm: lwm = current_price"
    trigger: "(current_price - lwm) / lwm >= trailing_pct"

default_threshold: 0.03  # 3% retracement (PARAM-MONITOR-001)

action_sequence:
  1: "fire StopLossEvent (TRAILING_STOP)"
  2: "log warning message"
  3: "call _auto_close(position, current_price, 'trailing_stop')"
  4: "delete trailing_highs[position_id]"
```

### `HARD-MONITOR-005` — Daily Drawdown
**Tags**: `drawdown, portfolio_level`

```yaml
condition: daily_drawdown
formula: |
  total_unrealized = sum(unrealized_pnl for pos in open_positions)
  total_cost = sum(entry_price * amount for pos in open_positions)
  portfolio_pnl_pct = total_unrealized / total_cost

trigger: "portfolio_pnl_pct <= -daily_drawdown_pct"
default_threshold: 0.10  # -10% portfolio (PARAM-MONITOR-001)

action_sequence:
  1: "fire StopLossEvent (DAILY_DRAWDOWN)"
  2: "log critical message"
  3: "kill_switch.activate_async() — KILL SWITCH IMMEDIATO"

severity: KILL_SWITCH
```

### `HARD-MONITOR-006` — Max Drawdown (Peak-to-Trough)
**Tags**: `max_drawdown, kill_switch`

```yaml
condition: max_drawdown
formula: |
  peak_equity = max(historical equity values)  # loaded from DB ledger
  current_equity = total_cost + total_unrealized
  drawdown = (peak_equity - current_equity) / peak_equity

trigger: "drawdown >= max_drawdown_pct"
default_threshold: 0.20  # -20% all-time (PARAM-MONITOR-001)

action_sequence:
  1: "fire StopLossEvent (MAX_DRAWDOWN)"
  2: "log critical message"
  3: "kill_switch.activate_async() — KILL SWITCH IMMEDIATO"

severity: KILL_SWITCH
```

---

## 4 — STALENESS CHECK

### `HARD-MONITOR-007` — Price Staleness Check
**Tags**: `staleness, refetch`

```yaml
rule: refetch_stale_prices_before_close
window_seconds: 60

logic: |
  Quando si sta per chiudere una posizione tramite _auto_close:
  if (now - price_age).total_seconds() > 60:
      try:
          fresh_price = await feeds.get_ticker(symbol)
          use fresh_price for the close
      except:
          log warning, use stale price
purpose: "Evitare di chiudere su prezzi non più rappresentativi"
```

---

## 5 — AUTO-CLOSE LOGIC

### `HARD-MONITOR-008` — Auto-Close via Gateway
**Tags**: `auto_close, gateway, idempotency`

```python
async def _auto_close(self, position, price, reason):
    """
    Chiude automaticamente una posizione tramite il gateway condiviso.
    Fail-safe: se il close fallisce, attiva il kill switch.
    """
    if self._gateway is None:
        # Manual close required — log critical
        return

    # Staleness check
    if price_age and (now - price_age).total_seconds() > 60:
        price = await self._refetch_price(position.symbol)

    close_direction = "SELL" if position.side == "BUY" else "BUY"
    qty = float(position.amount)

    try:
        result = await self._gateway.place(
            symbol=position.symbol,
            direction=close_direction,
            qty=qty,
            price=price,
            idempotency_key=f"close:{position.id}",
        )

        if result.status == "filled":
            log("auto-close FILLED")
        else:
            log("auto-close FAILED — activating kill switch")
            await self._kill_switch.activate_async(
                f"Auto-close failed for {position.symbol}: {result.message}"
            )
    except Exception as exc:
        log("auto-close CRASHED — activating kill switch")
        await self._kill_switch.activate_async(
            f"Auto-close crashed for {position.symbol}: {exc}"
        )
```

### `HARD-MONITOR-009` — Idempotency Key
**Tags**: `idempotency, double_execution`

```yaml
rule: idempotency_for_close_orders
key_format: "close:{position_id}"
ttl_seconds: 300
purpose: |
  Prevenire double-close se il monitor cycle si ripete prima
  che il fill sia confermato dal gateway.
```

---

## 6 — KILL SWITCH

### `HARD-MONITOR-010` — Kill Switch Persistence
**Tags**: `kill_switch, persistence`

```yaml
storage_table: kill_switch_state
implementation: src/trdex/risk/stop_loss.py KillSwitch class
migration: migrations/007_create_kill_switch_state.sql

properties:
  - active: bool
  - reason: string
  - activated_at: timestamp
  - lock: asyncio.Lock (thread-safe)

persistence_rule: |
  Stato persistito su DB.
  Sopravvive ai restart del processo.
  Reset richiede manuale via API: POST /v1/risk/kill-switch/reset

activation_paths:
  - manual_via_api
  - daily_drawdown_triggered (HARD-MONITOR-005)
  - max_drawdown_triggered (HARD-MONITOR-006)
  - auto_close_failure (HARD-MONITOR-008)
```

---

## 7 — PARAMETERS

### `PARAM-MONITOR-001` — Configurable Thresholds
**Tags**: `parameters, env`

```yaml
TRDEX_SL_CHECK_INTERVAL: 30.0           # secondi tra check cycles
TRDEX_SL_POSITION_PCT: 0.05             # SL per posizione: -5%
TRDEX_SL_TAKE_PROFIT_PCT: 0.10          # TP per posizione: +10%
TRDEX_SL_TRAILING_STOP_PCT: 0.03        # Trailing stop: 3% dal picco
TRDEX_SL_DAILY_DRAWDOWN_PCT: 0.10       # Daily DD limit: -10%
TRDEX_GATE_MAX_DRAWDOWN: 0.20           # Max DD all-time: -20%

evolvable: false  # questi sono HARD per default — modifica solo via review umana
```

---

## 8 — STOP HUNTING AWARENESS

### `HARD-MONITOR-MKT-001` — Stop Hunting Context
**Tags**: `stop_hunting, awareness`

```yaml
fact: |
  I dealer istituzionali organizzano "spedizioni di stop-hunting"
  per sfruttare comportamenti retail prevedibili.
source: "Beat the Forex Dealer — Agustin Silvani"

monitor_relevance: |
  Lo Stop-Loss Monitor opera su SL già piazzati dal Risk Manager.
  La protezione da stop-hunting è responsabilità del Risk Manager
  (posizionamento dello SL al di là dei livelli ovvi).
  Lo Stop-Loss Monitor esegue solo i livelli decisi a monte.

action_for_monitor: NONE  # eseguo SL già impostati
```

---

## 9 — EVENT LOG

### `HARD-MONITOR-011` — Event Recording
**Tags**: `events, logging`

```yaml
rule: log_every_event
in_memory_store: self._events (last 50)
persistence: TBD (planned: stop_loss_events table)

event_schema:
  - reason: StopReason enum
  - symbol: string | None
  - position_id: int | None
  - trigger_price: float | None
  - entry_price: float | None
  - loss_pct: float | None
  - fired_at: timestamp
  - message: string
```

---

## 10 — RIFERIMENTI

### `REF-MONITOR-001` — Implementation Files

```yaml
component_file: src/trdex/risk/stop_loss.py
class: StopLossMonitor
kill_switch_class: KillSwitch
migration: migrations/007_create_kill_switch_state.sql
balance_repo: src/trdex/storage/balance_repo.py (per peak_equity)
gateway_dependency: src/trdex/execution/default_gateway.py
```

### `REF-MONITOR-002` — Source

```yaml
- "Beat the Forex Dealer — Agustin Silvani (microstructure context)"
- "The New Trading for a Living — Alexander Elder (capital protection)"
```

---

**FINE KB STOP-LOSS MONITOR**
