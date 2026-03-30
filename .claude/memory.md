# Memory

## Now
- `.claude/teams/dev-team/` module completato (7 agenti specializzati + PROJECT_CONTEXT.md + /team command)
- Task Board riordinata: RAG refactoring parcheggiato, Google Ads/Email Marketing soft-blocked fino a Meta Ads validation
- Prossimo: Upstream Paperclip check + RAG architettura refactoring + memory hierarchy fixes

## Open Threads
- Upstream Paperclip check: fetch + log rilevamento commit (daily ritual)
- RAG architettura refactoring: config/, data/, pipelines/, tests/, notebooks/, Makefile (6-8 ore, post Meta Ads)
- Memory hierarchy conflict resolution: memory_writer.py (T5 vs T3 check) + router.py (tiebreaking prompt) + retrieval.py (confidence filter)
- Meta Ads test infrastruttura: tools/meta/ads_tool.py + executors/insights_fetcher.py + end-to-end test (BLOCCO)
- Google Ads, Email Marketing, Reporting/Quality: soft-blocked fino a Meta Ads test infra + frontend validation
- Frontend dashboard Layer 5 Meta Ads (CRM views, metriche, Soketi realtime)
- Streaming SSE per Ask Gravya (TTFT improvement, backlog)
- Production hardening: RLS, TTL cleanup su langgraph_checkpoints, cursor pagination CRM

## Recent Decisions
- **Unico repo di progetto: `gravya-platform/app/`** — origin: GravyaDev/gravya-platform, upstream: paperclipai/paperclip. Nessun altro repo.
- DB porta 5432 (standard PostgreSQL)
- Tabelle Gravya con prefisso `gravya_` per evitare conflitti con schema Paperclip
- Windows: build script usa `shx` al posto di `mkdir -p` / `cp -R`
- Piano completo: `.claude/plans/compiled-munching-octopus.md`
- Tutti i commit devono avere `Co-Authored-By: Kloud <kloud@gravya.it>`
- Multi-provider LLM: LiteLLM come libreria (non proxy). Model routing: default statico per agente + modalità "auto" dove Kloud ragiona e sceglie.
- Cost tracking: Kloud calcola cost_cents via litellm.completion_cost() → POST /cost-events.
- Kloud registrato come agente Paperclip: adapter_type=http, endpoint /kloud/invoke (migration 0050).
- Velocity reale ~10x stima iniziale → timeline compressa a 4-6 settimane totali.

## Daily Rituals
- **Paperclip upstream check**: ogni sessione, `git -C app fetch upstream && git -C app log upstream/main..HEAD --oneline` per rilevare commit upstream da valutare.

## Blockers
- (none)
