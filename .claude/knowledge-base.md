# Knowledge Base

System-wide learned rules. Read by ALL agents and sessions at startup.
Written ONLY by the auditor after confirming learnings.
Entries are mandatory constraints, not suggestions.

## Provenance Hierarchy
Every entry MUST cite its source using one of:
- `[Source: user override YYYY-MM-DD]` — User explicitly corrected something
- `[Source: empirical YYYY-MM-DD]` — Verified through testing or data
- `[Source: agent inference YYYY-MM-DD]` — Pattern observed by an agent, confirmed by auditor

## Hard Rules
- **For every third-party API or tool, ALWAYS access the official documentation online before writing code.** Verify current API version, updated endpoints, parameters, and deprecations. If documentation is not accessible, ask the user to provide it before proceeding. Never assume versions or behavior from training data — APIs evolve. [Source: user override 2026-04-02]
- **When implementing a client for a third-party API, ALWAYS read the rate limiting section of the official docs before writing code.** Implement the rate limiter based on real API signals (response headers, specific error codes) — not on local estimates (token bucket, own counters). Handle both application-level and global/BUC throttle if provided by the API. [Source: user override 2026-04-02]
- **ALWAYS implement proportional throttle based on current utilization reported by the API.** If the documentation specifies explicit thresholds, use them. If not, apply broadly conservative limits (e.g. start slowing at 60%, near-stop at 85%, full stop at 95%). An account banned for rate-limit abuse is unrecoverable on many platforms (Meta especially). Better to slow down heavily than exceed the limit. The delay curve must be convex, not linear: ban risk grows exponentially approaching 100%. [Source: user override 2026-04-02]
- **Before coding any API integration from scratch, check https://github.com/public-apis/public-apis first.** 1,426 free public APIs across 51 categories. If a ready-made API exists for the needed data or capability, use it. Only write a custom integration if no suitable option is found in that catalog. [Source: user override 2026-03-25]
- **Commit Identity**: All commits must use `Co-Authored-By: Kloud <kloud@gravya.it>`. Author is Daniele <daniele@gravya.it>. Never use a generic Claude attribution. [Source: onboarding config 2026-04-04]
- **/brainstorm-session must end explicitly BEFORE any transition to practical work.** When ideas are ready, use the skill's final summary and wait for explicit user input (new command, approval, planning). Do not start `/plan`, `/team`, or implementation without an explicit "end session". [Source: user override 2026-03-30]

## Platform & Tool Rules
- **Windows + pnpm: inline env vars don't work.** `VAR=value docker compose up` fails on Windows. Always use a `.env` file in the project root. [Source: empirical 2026-03-27]
- **Coolify non interpola `${VAR}` dentro `command:` né dentro `labels:` del compose — solo dentro `environment:`.** Qualsiasi valore che dipende da env var Coolify DEVE stare nel blocco `environment:`. Nei `labels:` usare valori hardcoded (con single quotes per `$` literal). Nei `command:` spostare la configurazione a env var native se il software le supporta. Violato due volte: (1) basic-auth hash in label `${TRDEX_DASHBOARD_BASICAUTH}` → fix hardcoded; (2) oauth2-proxy `--client-id=${OAUTH2_PROXY_CLIENT_ID}` in command → fix spostato a `OAUTH2_PROXY_CLIENT_ID` in environment. [Source: empirical 2026-04-08 + 2026-04-09]

## Project Patterns
- **RSI deve usare Wilder smoothing** (`com=period-1` in Polars), non EWM standard (`span=period`). Wilder è lo standard di TradingView, Bloomberg e MetaTrader. EWM standard diverge di 2-5 punti RSI in periodi volatili e produce segnali non comparabili con dati esterni. [Source: user override 2026-04-05]
- **Spiegare concetti tecnici a Daniele con esempi numerici concreti**, non con formule o descrizioni algoritmiche. Esempio corretto: "BTC a $90.000, equity $10.000 → compra 0.00222 BTC". Esempio sbagliato: "qty = equity × position_size / price". [Source: user override 2026-04-05]
- **SQLAlchemy `default=` su colonne timestamp: usare funzioni module-level con nome**, non lambda definite dentro classi. SA può iniettare `ctx` come argomento alle lambda con `argcount==1`, causando errori silenziosi. Pattern corretto: `def _utcnow_naive() -> datetime: return datetime.now(tz=timezone.utc).replace(tzinfo=None)` a livello modulo. [Source: empirical 2026-04-05]

## Dynamic Architecture Rules
- **Il balance del portfolio va persistito su ledger DB** (`account_balance` con `balance_after` per ogni evento — deposit, withdrawal, trade_fill). Non tenere il saldo in memoria. Permette di recuperare saldo reale e picco storico dopo qualsiasi riavvio. [Source: empirical 2026-04-05]
- **La skill `persistent-memory-stack` non è applicabile as-is a trdex** — usa pgvector (noi Qdrant) e psycopg3 (noi asyncpg). Solo il Tier 5 (Entity Graph) è applicabile ed è stato estratto e adattato. [Source: agent inference 2026-04-05]

## Known Failure Modes
- (none yet)