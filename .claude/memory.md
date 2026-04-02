# Memory

## Now
- **W14 + W17 completati** — 18/18 test pass; fix infrastruttura test (conftest, 4 import errati `from ...config.settings`)
- **Meta Ads tools** implementati: `_client.py` (throttle proporzionale), `get_insights.py`, `get_campaigns.py`, `get_ad_sets.py`, `__init__.py`
- **Migration 0056** — `gravya_credentials` (pgcrypto), `credentials_loader.py`, `settings.py` + `docker-compose.yml` aggiornati
- **Prossimo**: test suite P1 (W18 auth, W15 supervisor_registry, W21 memory_writer) + UI credentials + write tools Meta Ads

## Open Threads
- **Test suite W15, W18, W21** — P1, prossime da implementare
- **UI credentials** — `AgencyIntegrations.tsx` + `ClientCredentialsTab.tsx` + API routes (Node.js)
- **Meta Ads write tools** — `create_campaign.py`, `create_ad_set.py`, `update_budget.py`, `pause_campaign.py` (HITL)
- **Meta Ads review** — user in attesa di rivedere `_client.py`, `get_insights.py`, `get_campaigns.py`, `get_ad_sets.py`
- **Test E2E Meta Ads** — dopo review + write tools; read-only pipeline reale
- **ARCHITETTURA: Supervisore di Cliente** — design after Meta Ads validation
- Frontend dashboard Layer 5 Meta Ads (metriche campagne, Soketi realtime)
- Upstream Paperclip: 123+ commits behind — valutare merge dopo Meta Ads test infra

## Recent Decisions
- **Piano architettura dinamica** approvato → supervisori/esecutori dinamici da DB (migration 0052)
- **Kloud ha una "scheda" in DB** come i supervisor: model, fallback, threshold, system_prompt base — `kloud_config.py` con TTL 60s
- **supervisor_registry filtra agent_type='supervisor'** — Kloud non viene mai caricato come grafo supervisor
- **DDL-only pattern** per future migration: seed data in `app/scripts/seed-gravya-dev.sql` e `seed-gravya-prod.sql`
- **HITL levels (ordine corretto)**: full_manual → low_risk → escalation → full_auto (crescente automazione)
- **IVFFlat → HNSW** (migration 0054): HNSW m=16 ef=64, nessun probes tuning, ~99% recall
- **Tutti i commit**: Co-Authored-By: Kloud <kloud@gravya.it>
- **Unico repo**: `gravya-platform/app/` — origin: GravyaDev/gravya-platform, upstream: paperclipai/paperclip (branch: master)

## Daily Rituals
- **Paperclip upstream check**: ogni sessione, `git -C app fetch upstream && git -C app log upstream/master..HEAD --oneline`

## Blockers
- (none)
