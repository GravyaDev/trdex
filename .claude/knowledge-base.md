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
- **Commit Identity**: All commits must use `Co-Authored-By: Kloud <kloud@gravya.it>`. Author is Daniele <daniele@gravya.it>. Never use a generic Claude attribution. [Source: onboarding config 2026-04-04]

## Platform & Tool Rules
- **Coolify non interpola `${VAR}` dentro `command:` né dentro `labels:` del compose — solo dentro `environment:`.** Qualsiasi valore che dipende da env var Coolify DEVE stare nel blocco `environment:`. Nei `labels:` usare valori hardcoded (con single quotes per `$` literal). Nei `command:` spostare la configurazione a env var native se il software le supporta. Violato due volte: (1) basic-auth hash in label `${TRDEX_DASHBOARD_BASICAUTH}` → fix hardcoded; (2) oauth2-proxy `--client-id=${OAUTH2_PROXY_CLIENT_ID}` in command → fix spostato a `OAUTH2_PROXY_CLIENT_ID` in environment. [Source: empirical 2026-04-08 + 2026-04-09]

## Project Patterns
- **RSI deve usare Wilder smoothing** (`com=period-1` in Polars), non EWM standard (`span=period`). Wilder è lo standard di TradingView, Bloomberg e MetaTrader. EWM standard diverge di 2-5 punti RSI in periodi volatili e produce segnali non comparabili con dati esterni. [Source: user override 2026-04-05]
- **Spiegare concetti tecnici a Daniele con esempi numerici concreti**, non con formule o descrizioni algoritmiche. Esempio corretto: "BTC a $90.000, equity $10.000 → compra 0.00222 BTC". Esempio sbagliato: "qty = equity × position_size / price". [Source: user override 2026-04-05]
- **SQLAlchemy `default=` su colonne timestamp: usare funzioni module-level con nome**, non lambda definite dentro classi. SA può iniettare `ctx` come argomento alle lambda con `argcount==1`, causando errori silenziosi. Pattern corretto: `def _utcnow_naive() -> datetime: return datetime.now(tz=timezone.utc).replace(tzinfo=None)` a livello modulo. [Source: empirical 2026-04-05]

## Dynamic Architecture Rules
- **Il balance del portfolio va persistito su ledger DB** (`account_balance` con `balance_after` per ogni evento — deposit, withdrawal, trade_fill). Non tenere il saldo in memoria. Permette di recuperare saldo reale e picco storico dopo qualsiasi riavvio. [Source: empirical 2026-04-05]
- **La skill `persistent-memory-stack` non è applicabile as-is a trdex** — usa pgvector (noi Qdrant) e psycopg3 (noi asyncpg). Solo il Tier 5 (Entity Graph) è applicabile ed è stato estratto e adattato. [Source: agent inference 2026-04-05]

## Known Failure Modes
- **`pip-audit` senza `--python <venv>` scansiona il Python globale, non il venv del progetto.** In un venv uv senza pip installato, `pip-audit` dal PATH usa il global interpreter e riporta vulnerabilità di pacchetti non presenti nel venv (falsi positivi). Usare sempre `uvx --python .venv/Scripts/python.exe pip-audit` per scansionare correttamente il venv di progetto. [Source: empirical 2026-04-18]
- **`uv.lock` si inquina con dep di tool installati via `uv pip` + `uv sync` nella stessa sessione.** Cozempic (o qualsiasi tool) installato durante la sessione può lasciare entry nel lock (anthropic, distro, ecc.) anche dopo la rimozione. Pattern: fare `git diff uv.lock` prima di ogni merge forward; revert se ci sono entry estranee al progetto. [Source: empirical 2026-04-18]

## Merge Forward Rules
- **Task Board.md su feature branch è stato PER-BRANCH — risolvere sempre con `--ours`.** Confermato su 3+ merge forward consecutivi. [Source: empirical 2026-04-10 + 2026-04-11]
- **Strategia B per merge forward con dep conflict (uv.lock/pyproject.toml):** revert locale su pyproject+uv.lock → commit gli altri file → eseguire merge forward → risolvere uv.lock con `--theirs` (upstream è autoritativo per il lock). Evita conflitti manuali su 3000+ righe. [Source: empirical 2026-04-18]