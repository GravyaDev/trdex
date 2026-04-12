# Telegram Signal & News Pipeline — Alignment Document for LLM Agents

**Date**: 2026-04-12
**Audience**: the `llm-agents` branch (Scout/Analyst/Risk/Executor agents)
**Purpose**: describes the data flowing into trdex from Telegram so LLM
agents can consume it effectively when the branch merges `main`.

---

## What exists now on `main`

### Two data streams from 30+ Telegram channels

**Stream 1 — Trading Signals** (18 channels)
Real-time structured signals from forex, gold, crypto, and index channels.
Each signal contains: symbol, direction (BUY/SELL), entry price, TP targets,
stop-loss. Stored in `signal_outcomes` table with `exit_price=NULL` until
the post-hoc evaluator resolves them.

**Stream 2 — Market News** (12 channels)
Breaking news, commentary, macro analysis from CoinCodeCap, Cointelegraph,
CoinDesk, CoinMarketCap, Watcher Guru, and others. Stored in Qdrant as
context documents (`source=telegram_news:<chat_id>`).

### Data flow

```
Telegram channels (30+)
    │
    ▼
TelegramMonitor.stream_raw()   ←── all text messages, real-time
    │
    ├── parse_signal() succeeds ──► signal_outcomes table (observe-only)
    │                                  + Qdrant (source=telegram_signal)
    │
    └── parse_signal() fails ──────► Qdrant (source=telegram_news:<chat_id>)
                                       if text > 20 chars
```

### Signal format (what the parser extracts)

```python
@dataclass
class TelegramSignal:
    source: str           # chat_id of the channel
    symbol: str           # normalized: "XAU/USD", "BTC/USDT", "NAS100/USD"
    direction: "BUY"|"SELL"
    entry: float | None   # entry price (None = at market)
    targets: list[float]  # TP1, TP2, TP3 levels
    stop_loss: float | None
    raw_text: str         # original message for context
    parsed_at: datetime   # when parsed (= when received for real-time)
```

### What the parser handles

| Feature | Status |
|---|---|
| Standard forex pairs (EURUSD, GBP/JPY) | ✅ |
| Crypto pairs (BTC/USDT, ETH/BTC) | ✅ |
| Commodity aliases (GOLD→XAU/USD, USOIL→WTI/USD) | ✅ |
| Index symbols (NAS100, US30, GER40) | ✅ |
| Multiple TP levels (TP1, TP2, TP3) | ✅ |
| Label variants (Entry Level, Goal, Stoploss, Safe Stop Loss) | ✅ |
| BUY LIMIT / SELL LIMIT / BUY STOP | ✅ |
| Italian keywords (Compra, Vendi) | ✅ |
| Report/update filter (closed, TP hit, breakeven, +N pips) | ✅ |
| Signal dedup (60s window, same source+symbol+direction) | ✅ |

### What the parser does NOT handle (opportunities for LLM)

1. **Prose-embedded signals** — "EURUSD will go down to **0.919** from **0.924**" (SignalProvider format). The regex parser cannot extract prices from bold markdown in prose. An LLM agent reading the raw text could.

2. **Implicit direction** — "considering a short position on TRUMP" without an explicit BUY/SELL keyword. LLM can infer.

3. **Confidence/conviction scoring** — a signal that says "HIGH CONFIDENCE" vs "risky setup, small position only" has no representation in the current dataclass. An LLM agent could assign a conviction score (0.0-1.0) from the raw text.

4. **Multi-signal messages** — some channels post "BUY EURUSD + SELL GBPJPY" in a single message. The parser returns the first match only. An LLM could extract all.

5. **Context correlation** — a news message saying "NFP disappoints, USD weakness expected" followed 30 seconds later by a "SELL EURUSD" signal. The current system records them independently. An LLM Analyst agent could correlate the news with the signal and increase conviction.

---

## How LLM agents should consume this data

### Scout Agent

**Input**: Qdrant context store (queried by symbol or topic)
- `source=telegram_signal` documents: recent signals with entry/TP/SL metadata
- `source=telegram_news:<chat_id>` documents: market commentary, breaking news
- CryptoCompare + StockData news (existing sources, already in Qdrant)

**Expected behavior**: when scanning for trading opportunities, the Scout
should query Qdrant for recent context on the symbol(s) under analysis.
Telegram news provides faster signal than API-aggregated news (Telegram
messages arrive in seconds, API news sources have 5-30 minute lag).

### Analyst Agent

**Input**: Scout's market snapshot + Qdrant context
**Opportunity**: the Analyst can read the `raw_text` of recent `signal_outcomes`
records (via the `/v1/signals` API `recent` field) and:

1. **Validate signals against context** — does the news support the signal
   direction? Conflicting signals (one channel says BUY, another says SELL
   on the same symbol) should lower conviction.

2. **Score signal source reliability** — `/v1/signals` `report` field includes
   per-source `win_rate` and `roi_pct` after the 7-day observation period.
   Weight recent signals from high-reliability sources more heavily.

3. **Extract nuance the parser misses** — read the raw message text for
   mentions of "risky", "high confidence", "scalp only", "swing", time
   frame references ("4H chart", "daily close"). These inform position
   sizing and holding period.

### Risk Agent

**Input**: open positions + signal metadata
**Opportunity**: when evaluating a proposed trade that originated from a
Telegram signal, the Risk Agent can:

1. **Check signal quality** — does the signal have all of entry + TP + SL?
   Missing SL should trigger a penalty or rejection.

2. **Cross-reference with evaluator stats** — if the source channel has
   `win_rate < 0.5` on resolved signals, the Risk Agent should apply
   a larger safety margin or reject entirely.

3. **Multi-source confirmation** — if 3+ channels signal the same direction
   on the same symbol within a 5-minute window, conviction goes up.

### Executor Agent

**Input**: approved trade from Risk + signal metadata
**Current behavior** (main branch, rule-engine): observe-only, no execution.
**Future behavior** (llm-agents, Step 2): the Executor reads the signal's
TP/SL from the `note` JSON field and configures the StopLossMonitor to
use those targets instead of the default adaptive formula.

---

## DB schema relevant to signals

### `signal_outcomes` table

```sql
CREATE TABLE signal_outcomes (
    id            BIGSERIAL PRIMARY KEY,
    source        VARCHAR(100),     -- chat_id of the channel
    symbol        VARCHAR(20),
    direction     VARCHAR(5),       -- BUY | SELL
    entry_price   NUMERIC(28,8),
    exit_price    NUMERIC(28,8),    -- NULL until resolved by evaluator
    budget        NUMERIC(28,8),    -- 0 in observe-only mode
    executed_at   TIMESTAMPTZ,
    closed_at     TIMESTAMPTZ,      -- NULL until resolved
    note          TEXT              -- JSON: {targets, stop_loss, resolution}
);
```

The `note` field is JSON that evolves through the signal lifecycle:
1. **On record**: `{"targets": [2370, 2380], "stop_loss": 2340}`
2. **After evaluation**: `{"targets": [...], "stop_loss": ..., "resolution": "tp", "touched_target": 1}`

### Qdrant `trdex_context` collection

Documents with fields:
- `text`: signal or news content
- `source`: `"telegram_signal"` or `"telegram_news:<chat_id>"`
- `symbol`: for signals, empty string for news
- `sentiment`: 0.6 for BUY signals, -0.6 for SELL, 0.0 for news
- `published_at`: message timestamp

---

## API endpoints for signal data

| Endpoint | What it returns |
|---|---|
| `GET /v1/signals` | `{report: [{source, win_rate, roi_pct, ...}], recent: [last 50 outcomes]}` |
| `GET /v1/status` | `{telegram: {streaming, channels, signals_tracked, evaluator_running}}` |
| `GET /v1/settings/telegram` | `{values: {telegram_channels: "CSV of chat_ids"}}` |
| `PUT /v1/settings/telegram` | Update channel list at runtime (hot-reload, no restart) |

---

## Observation gate (before LLM auto-execute)

The current system is in **observe-only mode**: signals are recorded but
never executed. The gate criteria for moving to Step 2 (auto-execute):

- `win_rate >= 0.6` on resolved signals
- `roi_pct >= 5%` on at least 20 resolved signals
- 7 days of continuous observation

After the gate passes, the `llm-agents` branch should implement
`TelegramSignalExecutor` that:
1. Reads the signal from the background task
2. Routes to the correct feed/gateway (Binance for crypto, OANDA for forex)
3. Applies LLM Risk Agent approval instead of rule-based risk gates
4. Configures SL/TP from the signal's targets
5. Records execution in `signal_outcomes` with non-zero `budget`

---

## Channel inventory (as of 2026-04-12)

### Signal channels (18)

| chat_id | Name | Parser status |
|---|---|---|
| -1001830493898 | Wolf FX Signals (VIP) | FULL MATCH |
| -1001821216397 | PipXpert - Forex Signals | FULL MATCH |
| -1001758700941 | Forexero - Forex Signals | FULL MATCH |
| -1001954127662 | Sureshot FX Vip | FULL MATCH |
| -1001827807666 | Forex RR Vip | FULL MATCH |
| -1001584939836 | GOLD Snipers | PARTIAL (extended) |
| -1001485264313 | USOIL & Gold Signals | PARTIAL (extended) |
| -1001805057023 | NAS100 - US30 Snipers | PARTIAL (extended) |
| -1001810943222 | USOIL - Brent Signals | PARTIAL (extended) |
| -1001662267019 | EliteTradingSignals | PARTIAL (extended) |
| -1001485077759 | ProSignalsFx | PARTIAL (extended) |
| -1001196272579 | TopTradingSignals | PARTIAL (extended) |
| -1001785197109 | AnabelSignals | PARTIAL (extended) |
| -1001469931329 | SignalProvider | PARTIAL (prose) |
| -1002176304936 | MATTEO ZANNI | PARTIAL (Italian) |
| -1002100291186 | Gold Signals (VIP) | PARTIAL (extended) |
| -1001830925100 | Jacob Crypto Bury | PARTIAL (extended) |
| -1001774567944 | Trader signals EN | PARTIAL (prose) |

### News channels (12)

| chat_id | Name | Content |
|---|---|---|
| -1001213141511 | CoinCodeCap Classic | Crypto analysis + commentary |
| -1001263225860 | Learn 2 Trade | Market briefs + forex news |
| -1001347620559 | Wells Crypto | Breaking crypto news |
| -1002086010937 | Crypto Wolf | Crypto news |
| -1002296311807 | Kara Trading | Macro analysis (inflation, rates, NFP) |
| -1001765226347 | Ben, Gold Trader | Gold market updates |
| -1002217602117 | Kharitonov FX Trading | FX market analysis |
| -1001556054753 | Watcher Guru | Breaking crypto + finance |
| -1001072723547 | Cointelegraph | Crypto + Web3 media |
| -1001358788312 | unfolded | Institutional/macro crypto |
| -1001381405351 | CoinMarketCap English | Industry news + listings |
| -1001509831470 | CoinDesk | Crypto news + analysis |

### Pending discovery (~58 channels)

A lookup file exists at `channels_failed_lookup.md` with 58 channel
names where only the admin handle was available (not the channel link).
The user is searching for the correct channel links. These will be
added via the dashboard as they are found.

---

## Merge notes for `llm-agents`

1. **`api/app.py`** heavily modified — `_telegram_background()` now uses
   `stream_raw()` with dual-path (signal vs news). The lifespan creates
   the `_telegram_eval_task` and registers a `_on_telegram_change`
   hot-reload listener. **Merge conflict expected** — preserve both the
   new Telegram wiring and the LLM agent wiring.

2. **`telegram/parser.py`** completely rewritten with commodity aliases,
   extended labels, and report filter. If the LLM branch has not
   touched this file, no conflict.

3. **`telegram/monitor.py`** has `stream_raw()`, `update_channels()`,
   and `TelegramMessage` dataclass. These are additive — the original
   `stream()` method is preserved for backward compat.

4. **`services/credentials_crypto.py`** now raises on wrong key (was
   silent). If the LLM branch reads credentials via RuntimeConfigService,
   it must handle `DecryptionError` in its startup path.

5. **New evaluator module** `telegram/evaluator.py` — entirely new file,
   no conflict possible unless the LLM branch also created one.

---

**End of document.**
