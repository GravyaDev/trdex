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
- **Per ogni API o tool con connessioni di terze parti, accedere SEMPRE alla documentazione ufficiale online prima di scrivere codice.** Verificare versione corrente dell'API, endpoint aggiornati, parametri e deprecazioni. Se la documentazione non è accessibile, chiedere all'utente di fornirla prima di procedere. Non assumere mai versioni o comportamenti da training data — le API evolvono. [Source: user override 040226]
- **Quando si implementa un client verso un'API di terze parti, leggere SEMPRE la sezione rate limiting della documentazione ufficiale prima di scrivere il codice.** Implementare il rate limiter basandosi sui segnali reali dell'API (header di risposta, error code specifici) — non su stime locali (token bucket, contatori propri). Gestire sia il throttle a livello applicativo che quello globale/BUC se previsto dall'API. [Source: user override 040226]
- **Implementare SEMPRE un throttle proporzionale basato sull'utilizzo corrente riportato dall'API.** Se la documentazione indica soglie esplicite, usarle. Se non le indica, applicare limiti ampiamente conservativi (es. iniziare a rallentare al 60%, quasi fermarsi all'85%, fermarsi completamente al 95%). Un account bannato per rate-limit abuse è irrecuperabile su molte piattaforme (Meta in primis). Meglio rallentare pesantemente che superare il limite. La curva di delay deve essere convessa, non lineare: il rischio di ban cresce esponenzialmente avvicinandosi al 100%. [Source: user override 040226]
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

## Dynamic Architecture Rules
- **Supervisor validation must be deterministic (config-based), not LLM-based.** Executor declares `completeness_status: "complete" | "partial" | "error"`; pipeline config provides `is_critical: bool` and `partial_strategy`. The admin decides the acceptance threshold, not the LLM at runtime. [Source: agent inference 040226]
- **LangGraph `CompiledGraph` is not serializable.** Must be built at runtime from DB config and cached in-memory per supervisor with a per-supervisor `asyncio.Lock` (double-check locking). Cache invalidation via `schema_version` field bumped by a PostgreSQL trigger on `gravya_supervisor_pipeline`. [Source: agent inference 040226]

## Known Failure Modes
- (none yet)
