# Runbook: Deploy trdex-llm on Coolify

**Date**: 2026-04-18
**Target domain**: `https://trdex-llm.gravya.it`
**Target branch**: `llm-agents`
**Approach**: GitHub App auto-deploy (per `docs/playbook-coolify-autodeploy.md`)

This runbook replaces the manual steps in `docs/deploy-llm-instance.md` Section 3+4
(Traefik labels, OAuth reuse) — the compose is already configured for trdex-llm
(commits `11b7ef9` port 8502, `f341516` volume isolation, `29408e0` compose isolation)
and the GitHub App source is already installed org-wide (2026-04-17).

---

## Pre-flight — already verified

- DNS `trdex-llm.gravya.it` → `187.124.166.189` ✓ (same VPS as trdex, Traefik routes by Host)
- Branch `llm-agents` pushed, latest `7850117` (merge forward #7 + security patches) ✓
- `docker-compose.yaml` on `llm-agents` has trdex-llm-specific Traefik router names
  (`trdex-llm-dashboard`, `trdex-llm-oauth2-svc`) and hardcoded domain
  `trdex-llm.gravya.it` in oauth2-proxy labels (Coolify cannot interpolate env
  vars in labels — see `.claude/knowledge-base.md`) ✓
- Port `8502:8000` hardcoded in compose (avoids collision with trdex `8500:8000`) ✓
- Volume names `pgdata / redis / qdrant` isolated per-app (Coolify prefixes with
  its application UUID automatically — no cross-contamination with trdex prod) ✓
- GitHub App `Coolify` installed on `GravyaDev` org with "All repositories"
  access (done 2026-04-17 for trdex prod) ✓
- GitHub OAuth App for `trdex-llm` already created with callback URL
  `https://trdex-llm.gravya.it/oauth2/callback` ✓
- All 3 LLM provider API keys available (Anthropic, OpenAI, Google) ✓

**Section 1.5 of the playbook does NOT apply** — we are creating a new Coolify
application from scratch using the GitHub App source, not converting an existing
"Public Repository" app. Zero data wipe risk (no data exists yet).

---

## Step 1 — Create the Coolify application (human, UI)

In Coolify UI at `https://coolify.gravya.it`:

1. **New Resource** → **Application** → **Public Repository (slash)** — no, **wait**, pick **Private Repository (with GitHub App)** and select the `Coolify` GitHub App source installed on `GravyaDev`.
2. **Repository**: `GravyaDev/trdex`
3. **Branch**: `llm-agents` *(CRITICAL — not `main`. Main is trdex prod.)*
4. **Build pack**: **Docker Compose**
5. **Name**: `trdex-llm`
6. **Domain**: `https://trdex-llm.gravya.it` (Coolify reads this and generates the default app router; the oauth2-proxy/dashboard router is defined by labels in the compose file itself)
7. **Auto Deploy**: ✓ ON
8. **Save**. Do NOT deploy yet — env vars first.

After save, Coolify will create a new application with a new UUID. This app has
its own `<uuid>_pgdata`, `<uuid>_redis`, `<uuid>_qdrant` volumes, isolated from
trdex prod. Good.

---

## Step 2 — Configure environment variables (human, UI)

In Coolify → application `trdex-llm` → **Environment Variables** tab.

### 2a. Secrets (generate fresh — DO NOT reuse from trdex prod)

```bash
# Generate these locally once, then paste into Coolify:
openssl rand -hex 24    # POSTGRES_PASSWORD
openssl rand -hex 32    # TRDEX_API_KEY
openssl rand -hex 16    # OAUTH2_PROXY_COOKIE_SECRET
```

| Variable | Value | Notes |
|---|---|---|
| `POSTGRES_PASSWORD` | `<hex-24>` | Fresh — isolated DB from trdex prod |
| `TRDEX_API_KEY` | `<hex-32>` | Separate from trdex prod |
| `OAUTH2_PROXY_COOKIE_SECRET` | `<hex-16>` | 32-char, cookie signing |
| `TRDEX_CONFIG_ENCRYPTION_KEY` | `python -m trdex.services.credentials_crypto` | Fernet key for runtime_config.credentials encryption at rest |

### 2b. OAuth2-proxy (GitHub SSO)

From the `trdex-llm` GitHub OAuth App you already created:

| Variable | Value |
|---|---|
| `OAUTH2_PROXY_CLIENT_ID` | `<from GitHub OAuth App settings>` |
| `OAUTH2_PROXY_CLIENT_SECRET` | `<from GitHub OAuth App settings>` |
| `OAUTH2_PROXY_GITHUB_USER` | `GravyaDev` (restrict to your user only) |
| `OAUTH2_PROXY_EMAIL_DOMAIN` | `*` (optional — `gravya.it` to restrict) |
| `TRDEX_DOMAIN` | `trdex-llm.gravya.it` |

### 2c. LLM providers (all three active)

| Variable | Value |
|---|---|
| `TRDEX_ANTHROPIC_API_KEY` | `sk-ant-api03-…` |
| `TRDEX_OPENAI_API_KEY` | `sk-…` |
| `TRDEX_GOOGLE_API_KEY` | `AIza…` |
| `TRDEX_LLM_DAILY_BUDGET` | `20.0` |
| `TRDEX_LLM_MONTHLY_BUDGET` | `500.0` |
| `TRDEX_LLM_MAX_PROMPT_TOKENS` | `4096` |

### 2d. Operational defaults

| Variable | Value | Why |
|---|---|---|
| `TRDEX_MODE` | `simulation` | Never live on llm-agents branch until gate passes |
| `TRDEX_AGENT_SCHEDULER_ENABLED` | `false` | Start off — enable via dashboard after smoke test |
| `TRDEX_AGENT_SCHEDULER_SYMBOLS` | (leave default — 10 symbols) | Or start narrower (5) to cap LLM spend, tune later via Runtime Config |
| `TRDEX_JINA_API_KEY` | `<if available>` or empty | Empty tolerated — disables Qdrant embeddings |
| `TRDEX_TELEGRAM_API_ID` | `0` | Keep disabled for LLM-agent observation phase |

### 2e. Everything else

Leave defaults from compose (`:-` fallbacks). Feed API keys optional (empty ⇒
feed skipped at runtime). Scheduler/SL/gate params have sensible defaults
already in the compose file.

---

## Step 3 — Persistent bind mount for Telethon session (human, VPS)

Even with Telegram disabled (`TRDEX_API_ID=0`), the compose declares a bind
mount `/opt/trdex-llm/session:/app/session`. Create the directory on the VPS
before first deploy so the mount does not fail:

```bash
# ssh user@187.124.166.189
sudo mkdir -p /opt/trdex-llm/session
sudo chown -R 1000:1000 /opt/trdex-llm/session
```

(If you later enable Telegram, drop the `.session` file into that directory.
Bind mount survives container rebuilds and Coolify redeploys.)

---

## Step 4 — Deploy and smoke-verify

### 4a. Trigger first deploy

In Coolify UI → application `trdex-llm` → **Deploy** button. First build is
~2–3 min (1.3 GB image). Watch the Deployments log for:
- `apply_migrations` runs cleanly on startup (DB empty + migrations create schema)
- `app` container healthcheck turns healthy (`curl /v1/health`)
- `dashboard` container healthcheck turns healthy
- `oauth2-proxy` starts (no fatal errors about missing env)

### 4b. Verify webhook created by GitHub App

Locally, from agent:

```bash
gh api repos/GravyaDev/trdex/hooks --jq '.[].config.url'
```

Expected: at least one `https://coolify.gravya.it/webhooks/...` entry. The App
may register at org-level or per-install — either counts as verified.

### 4c. Health checks (external)

```bash
curl -sf https://trdex-llm.gravya.it/v1/health
# Expected: {"status":"ok",...} with 200

curl -sf -o /dev/null -w "%{http_code}\n" https://trdex-llm.gravya.it/dashboard/
# Expected: 302 (oauth2-proxy redirect to GitHub login)
```

### 4d. Auto-deploy smoke test

Once healthy, push an empty commit from your local `llm-agents` branch:

```bash
cd "c:/Users/Daniele/Antigravity/trdex-llm"
git commit --allow-empty -m "chore: smoke test trdex-llm auto-deploy"
git push origin llm-agents
```

Within ~5 seconds, Coolify should start a new deployment. Watch
**Deployments** tab in Coolify UI. If nothing happens in 30 seconds → see
Playbook Section 6 (Diagnostics).

---

## Step 5 — Enable LLM agents (post-deploy, dashboard UI)

1. Browse to `https://trdex-llm.gravya.it/dashboard/` → log in via GitHub OAuth.
2. Runtime Config → **LLM Agent Configuration** → set desired provider per agent
   (Analyst / Scout). Toggle `llm_enabled: true` for each.
3. Verify `/v1/agent/llm-usage?period=today` returns zero-cost baseline.
4. Enable scheduler: Runtime Config → set `TRDEX_AGENT_SCHEDULER_ENABLED=true`
   via env (requires container restart — Coolify → Redeploy), OR leave the
   env at `false` and flip a per-integration toggle if the new per-component
   toggles work (from main merge commit `cf24a2e`).

### RAG Tier 4b activation (optional, after scheduler is running)

Once scheduler is running and producing signals, populate Qdrant episodes:

```bash
# ssh into the Coolify VPS, exec into the app container:
ssh user@187.124.166.189
docker exec -it <trdex-llm-app-container> bash
# Inside container:
python -m trdex.scripts.backfill_ohlcv BTC/USDT --days 365
python -m trdex.scripts.backfill_ohlcv ETH/USDT --days 365
# ... for each scheduler symbol
python -m trdex.scripts.generate_episodes --all
```

This is deferrable — not required for first smoke-test.

---

## Step 6 — Cost watch (first 48h)

Dashboard widget "LLM costs" shows daily/monthly spend. Compare against:
- Estimate at full rate: 10 symbols × 288 ticks/day × 3 providers = ~$X/day
  (precise figure depends on which provider is active per agent)
- Budget hard cap at `$20/day` — agents auto-disable if exceeded (see
  `services/llm_budget.py`)

---

## Troubleshooting

- **"container healthy but 502 from Traefik"** → Coolify domain setting likely
  points to wrong internal port. In Coolify → application → Configuration,
  verify domain `trdex-llm.gravya.it` is set; Traefik labels in compose handle
  the oauth2-proxy → dashboard chain themselves.
- **"OAuth redirect loop"** → `OAUTH2_PROXY_REDIRECT_URL` in compose is
  `https://${TRDEX_DOMAIN:-trdex-llm.gravya.it}/oauth2/callback`. If `TRDEX_DOMAIN`
  is set to something else in env vars, the callback URL must match the
  GitHub OAuth App's "Authorization callback URL" exactly.
- **"POSTGRES_PASSWORD is required"** at startup → compose uses `:?` enforcement
  for this var. Missing = fail-fast. Add it in Coolify env vars.
- **"TRDEX_API_KEY must be defined"** at startup → same pattern. Even empty
  string works (dev mode disables auth) but the var must be defined.
- **Deploy doesn't start on push** → see `docs/playbook-coolify-autodeploy.md`
  Section 6.

---

## Rollback

If LLM agents misbehave or costs spike:

1. **Instant**: Runtime Config → toggle `llm_enabled=false` per agent in dashboard.
   Falls back to rule engine, no redeploy needed.
2. **Harder**: Coolify → application → Stop. trdex prod (separate app) unaffected.
3. **Full teardown**: Coolify → application → Delete. Volumes orphan on VPS
   until `docker volume prune`.
