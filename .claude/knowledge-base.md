# Knowledge Base

System-wide learned rules. Read by ALL agents and sessions at startup.
Written ONLY by the auditor after confirming learnings.
Entries are mandatory constraints, not suggestions.

## Provenance Hierarchy
Every entry MUST cite its source using one of:
- `[Source: user override MMDDYY]` — User explicitly corrected something
- `[Source: empirical MMDDYY]` — Verified through testing or data
- `[Source: agent inference MMDDYY]` — Pattern observed by an agent, confirmed by auditor

## Hard Rules
- **Before coding any API integration from scratch, check https://github.com/public-apis/public-apis first.** 1,426 free public APIs across 51 categories. If a ready-made API exists for the needed data or capability, use it. Only write a custom integration if no suitable option is found in that catalog. [Source: user override 032526]
- **Tutti i commit su gravya-platform devono usare `Co-Authored-By: Kloud <kloud@gravya.it>`.** Mai usare `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>` o qualsiasi altra attribuzione. [Source: user override 032726]
- **/brainstorm-session deve terminare esplicitamente PRIMA di qualsiasi transizione a lavoro pratico.** Quando le idee sono pronte, usare il riepilogo finale della skill e attendere input esplicito dell'utente (nuovo command, approvazione, planning). Non avviare `/plan`, `/team`, o implementation senza una "end session" esplicita. [Source: user override 033026]

## Platform & Tool Rules
- **Windows + pnpm: le env var inline non funzionano.** `VAR=value docker compose up` fallisce su Windows. Usare sempre un file `.env` nella root del progetto. [Source: empirical 032726]
- **Paperclip build script su Windows: usare `shx`.** `mkdir -p` e `cp -R` falliscono su Windows. Aggiungere `shx` come devDependency e sostituire con `shx mkdir -p` / `shx cp -R` in `server/package.json`. [Source: empirical 032726]
- **`HttpError` in Paperclip usa `.status`, non `.statusCode`.** Leggere `errors.ts` prima di usare HttpError in nuove route. [Source: empirical 032726]
- **Paperclip migration runner legge `_journal.json`** e cerca i file come `{tag}.sql`. Le migration raw SQL manuali devono essere aggiunte manualmente al journal — Drizzle non le include. [Source: empirical 032726]

## Project Patterns
- **Tabelle custom su gravya-platform usano prefisso `gravya_`.** Evita conflitti con le 60+ tabelle Paperclip e futuri merge da upstream. [Source: empirical 032726]
- **pgvector richiede immagine dedicata.** Sostituire `postgres:17-alpine` con `pgvector/pgvector:pg17` in docker-compose per abilitare `vector(1024)` e ANN search. [Source: empirical 032726]
- **Drizzle ORM non supporta pgvector natively.** Le colonne `vector(N)`, `tsvector GENERATED`, i self-referencing FK e gli index IVFFlat/GIN vanno in una migration SQL raw separata, aggiunta manualmente al journal. [Source: empirical 032726]
- **Soketi bridge: non usare wildcard EventEmitter.** `live-events.ts` usa `companyId` come chiave evento — non esiste `"*"`. Hookare direttamente `publishLiveEvent()` e `publishGlobalLiveEvent()`, mai subscribere con `"*"`. [Source: empirical 032726]

## Known Failure Modes
- (none yet)
