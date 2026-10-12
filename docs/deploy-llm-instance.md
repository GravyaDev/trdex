# Deploy trdex-llm — Parallel Instance on Coolify

## Overview

Run `llm-agents` branch as a SEPARATE Coolify Application alongside the
existing `main` branch (rule-engine). Both run in simulation mode on the
same VPS, independent databases, same market data.

## Prerequisites

- DNS: `trdex-llm.gravya.it` → `187.124.166.189` (A + AAAA) — **DONE**
- Anthropic API key for LLM calls

## Step 1: Create new Application on Coolify

1. Coolify dashboard → New Application → Docker Compose
2. **Repository**: `GravyaDev/trdex` (same repo)
3. **Branch**: `llm-agents`
4. **Name**: `trdex-llm`

## Step 2: Environment Variables

Copy all env vars from the existing `trdex` app, then change:

```bash
# === MUST CHANGE (different from main) ===

# Different database name (CRITICAL — prevents cross-contamination)
POSTGRES_PASSWORD=<generate new: openssl rand -hex 24>
DATABASE_URL=postgresql+asyncpg://trdex:${POSTGRES_PASSWORD}@db:5432/trdex_llm

# Different app port (avoid conflict with main instance's 8500)
TRDEX_APP_HOST_PORT=8600

# Different API key (separate auth)
TRDEX_API_KEY=<generate new: openssl rand -hex 32>

# === NEW (LLM-specific) ===

TRDEX_ANTHROPIC_API_KEY=sk-ant-api03-...
TRDEX_OPENAI_API_KEY=              # empty = disabled
TRDEX_GOOGLE_API_KEY=              # empty = disabled
TRDEX_LLM_DAILY_BUDGET=20.0
TRDEX_LLM_MONTHLY_BUDGET=500.0
TRDEX_LLM_MAX_PROMPT_TOKENS=4096

# === KEEP SAME (or similar) ===

TRDEX_MODE=simulation
TRDEX_AGENT_SCHEDULER_ENABLED=true
TRDEX_AGENT_SCHEDULER_INTERVAL=300
TRDEX_AGENT_SCHEDULER_SYMBOLS=BTC/USDT,ETH/USDT,SOL/USDT,XRP/USDT,BNB/USDT
# (start with 5 symbols instead of 9 to control LLM costs)
```

## Step 3: Fix domain in Traefik labels

The `docker-compose.yaml` has `trdex.gravya.it` hardcoded in Traefik labels
(Coolify doesn't interpolate env vars in labels). Before deploying, change
these in the Coolify compose editor (or create a branch-specific override):

**In the `oauth2-proxy` service:**
```yaml
# Change these 3 lines:
OAUTH2_PROXY_COOKIE_DOMAIN: 'trdex-llm.gravya.it'           # was trdex.gravya.it
OAUTH2_PROXY_REDIRECT_URL: 'https://trdex-llm.gravya.it/oauth2/callback'

# Labels:
- "traefik.http.routers.trdex-llm-dashboard.rule=Host(`trdex-llm.gravya.it`) && (PathPrefix(`/dashboard`) || PathPrefix(`/oauth2`))"
- "traefik.http.routers.trdex-llm-dashboard.entrypoints=https"
- "traefik.http.routers.trdex-llm-dashboard.tls=true"
- "traefik.http.routers.trdex-llm-dashboard.tls.certresolver=letsencrypt"
- "traefik.http.routers.trdex-llm-dashboard.service=trdex-llm-oauth2-svc"
- "traefik.http.services.trdex-llm-oauth2-svc.loadbalancer.server.port=4180"
```

**In the `app` service (if Coolify auto-generates a router):**
Ensure Coolify points the domain `trdex-llm.gravya.it` → app:8000.

**IMPORTANT**: Router names must be unique across all Coolify apps on the
same Traefik instance. Use `trdex-llm-*` prefix (not `trdex-*`) to avoid
colliding with the existing main app's routers.

## Step 4: GitHub OAuth App

Option A: Reuse the same GitHub OAuth App — add `https://trdex-llm.gravya.it/oauth2/callback` as an additional Authorized redirect URI.

Option B: Create a separate GitHub OAuth App for the LLM instance.

Option A is simpler. Same `OAUTH2_PROXY_CLIENT_ID` / `CLIENT_SECRET`.

## Step 5: Deploy

1. Click Deploy on Coolify
2. Wait for build + healthcheck
3. Verify: `curl https://trdex-llm.gravya.it/v1/health`
4. Verify dashboard: `https://trdex-llm.gravya.it/dashboard/`
5. Enable LLM: dashboard → LLM Agent Configuration → Analyst → toggle ON

## Step 6: Monitor

- Dashboard cost widget shows spend
- `/v1/agent/llm-usage?period=today` for API-level stats
- Compare signals with `trdex.gravya.it` (rule engine) after 24-48h

## Cost Estimate

5 symbols × 168 ticks/day × Sonnet ≈ $11/day ($340/month) at full rate.
With conditional calling (unchanged data skip): ~$6/day ($180/month).
Budget cap: $20/day hard limit.

## Rollback

If LLM costs too much or produces bad signals:
- Toggle `llm_enabled=false` from dashboard → instant fallback to rule engine
- Or: stop the Coolify app entirely (main keeps running)
