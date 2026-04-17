# Playbook: Coolify Auto-Deploy + Granular Actions

**Audience**: LLM agents (Claude, etc.) opening a session on a new Gravya project that needs automatic redeploy on `git push`.

**Problem this solves**: Coolify's "Auto Deploy" checkbox is ticked but pushing to `main` does nothing — every deploy still requires a manual click in the Coolify UI. Cause: no webhook is registered on GitHub, so Coolify never receives `push` events.

**Design principle**: separation of responsibilities.
- **Coolify GitHub App** — universal, handles **only** the redeploy (rebuild image + restart containers). Installed once on the GitHub org, covers all current and future Gravya repos.
- **GitHub Actions workflow** (optional, per-project) — handles **only** project-specific granular actions that Coolify doesn't do (sync folders on VPS, notify Slack/Telegram, run lint/test, apply custom migrations, post-deploy smoke checks).

If you find existing workflows that `curl -X POST <coolify-webhook>/deploy`, **remove that step** after installing the App — it becomes redundant and can race.

---

## Section 1 — When to use this playbook

**Signal**: you are in a Gravya repo, the Coolify app's "Auto Deploy" toggle is ✓, but pushes to `main` don't trigger deploys.

**Quick diagnostic** (run first, before any change):

```bash
gh api repos/GravyaDev/<REPO>/hooks
```

- Returns `[]` → no webhook registered → **this playbook applies**.
- Returns a webhook pointing to `coolify.gravya.it` → already set up, you're done (check it's pointing to the right Coolify app and that "Recent Deliveries" are 200s).
- Returns a webhook pointing somewhere else → investigate before overwriting.

---

## Section 1.5 — ⚠️ CRITICAL: Source type change recreates the app

**Read this before touching any existing Coolify application.**

In Coolify 4.0-beta, **changing an application's Source type** (e.g., from "Public Repository" to "GitHub App") is **NOT an in-place operation**. What actually happens:

- Coolify **creates a new application** with a new UUID (e.g. `e5tqc26v...`)
- The new application gets **new volumes** — `<new-uuid>_pgdata`, `<new-uuid>_redis`, `<new-uuid>_qdrant`, etc.
- The old application's volumes (`<old-uuid>_pgdata`, ...) become **orphan** — they still exist on disk but no container mounts them
- The new app starts with an **empty database, empty Redis, empty Qdrant collections** — zero data

This wipes all application state that lived in volumes: trading positions, balance ledger, signal outcomes, persistent stop-loss events, vector embeddings, Telethon session files, etc. Environment variables are **not** automatically copied either — you have to re-enter them in the new app's UI.

**Before changing Source type, decide one of**:

1. **Accept the data wipe** — only valid if the persistent state is truly disposable (dev environment, freshly reset DB, staging app with no production data).
2. **Plan the migration upfront**:
   - Dump each volume's data: `pg_dump` for Postgres, `redis-cli --rdb` for Redis, Qdrant snapshot API for vector DB, rsync for file volumes.
   - Switch Source → wait for new app to deploy → restore into the new volumes.
   - Alternatively: stop new containers → `docker run --rm -v <old_vol>:/src -v <new_vol>:/dst alpine cp -av /src/. /dst/` for each volume → restart.
3. **Skip the Source switch entirely** and register the webhook manually on the existing app — GitHub repo → Settings → Webhooks → add webhook pointing to Coolify's deploy URL for that app. Preserves volumes, avoids the whole problem. Trade-off: one manual step per repo, not universal.

**When this matters most**: production apps with live data. The wipe is usually silent — the new app comes up healthy, but every dashboard metric is 0. Users discover it only when they look.

**History**: on 2026-04-17 this happened on trdex production. The GitHub App was installed correctly, but clicking "switch source to GitHub App" on the existing `w35035...` trdex app silently created a new `e5tqc26v...` app and left the old pgdata/redis/qdrant volumes orphaned. 24h of trading data were disposable so the wipe was accepted, but had the same been done on the gravya-platform production DB the loss would have been unrecoverable.

---

## Section 2 — Install Coolify GitHub App (one-time, org-wide)

This is the **universal** step. Do it once per GitHub org (`GravyaDev`), not per repo. It requires UI access to Coolify and GitHub — an LLM agent cannot do it alone, brief the human operator to do it.

**Steps (human operator, via Coolify UI at `https://coolify.gravya.it`)**:

1. Go to **Sources** (left sidebar) → **GitHub** → **+ New** → **GitHub App** (not "Public Repository" or "Deploy Key").
2. Follow the authorization flow. GitHub will ask which account/org to install on. Select **GravyaDev** (the org, not a personal account).
3. On the GitHub app install screen, select **which repos** the App can see:
   - Minimum: the repo you're setting up right now.
   - Recommended: **All repositories**. One install covers every current and future Gravya repo (gravya-platform, trdex, trdex-llm, gravya-ops). If you later restrict, do it from GitHub → Settings → Applications → Coolify → Configure.
4. Finish the flow. Coolify registers the App under **Sources → GitHub** and the App is now linked.

**Reconnect existing app to the new Source** (only if the app was previously on "Public Repository"):

> ⚠️ **STOP**: before proceeding, re-read **Section 1.5**. Changing an existing app's Source type in Coolify 4.0-beta **creates a new application with empty volumes** (DB wipe). If the app has any data you cannot afford to lose, plan the migration first — or skip to the manual webhook registration in Section 4 instead.

5. In Coolify → your application (e.g. `trdex`) → **Configuration** → **Source**.
6. Change the source from **Public Repository** to the new **GitHub App** source you just installed. Save.
7. Coolify will now spin up a new application with a new UUID. The webhook is created on GitHub automatically, but all volumes are fresh. Re-enter env vars, then migrate data (or accept the wipe) per Section 1.5.

---

## Section 3 — Verification

After the human completes Section 2, verify from the LLM agent side (read-only):

```bash
# 1) Webhook should now exist on GitHub
gh api repos/GravyaDev/<REPO>/hooks --jq '.[].config.url'
# Expected output: https://coolify.gravya.it/webhooks/source/github/events/...

# 2) End-to-end smoke test: push a no-op commit
git commit --allow-empty -m "chore: smoke test auto-deploy"
git push origin main

# 3) Watch Coolify UI → application → Deployments. A new deployment should
#    start within ~5 seconds of the push.

# 4) GitHub side: Settings → Webhooks → Recent Deliveries.
#    The push event should show a 200 OK response.
```

If the deployment doesn't start, see **Section 6 — Diagnostics**.

---

## Section 4 — Pattern: App vs Actions

Once the GitHub App is installed, you have two channels to act on `push: main`:

| Channel | Fires on | Use for | Latency |
|---|---|---|---|
| Coolify GitHub App | every push (automatic via webhook) | **only** image build + container restart | ~5s trigger, then build time |
| `.github/workflows/*.yml` | push events matching the workflow `on:` filter | **only** project-specific non-deploy actions | parallel to the App, not sequential |

**Critical rule**: Actions and the App run **in parallel** on the same `push`, not in sequence. If an Action depends on the new deployment being live (e.g., a smoke test hitting `/v1/health`), it MUST poll — it cannot assume deployment is ready when the workflow starts.

**Example Action template** (only if you actually need granular actions — omit the whole workflow if the project has nothing beyond deploy):

```yaml
# .github/workflows/post-deploy.yml
name: post-deploy
on:
  push:
    branches: [main]
jobs:
  post-deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Wait for deploy to be live
        run: |
          for i in $(seq 1 30); do
            if curl -sf https://<APP_URL>/v1/health > /dev/null; then
              echo "healthy after $i attempts"
              exit 0
            fi
            sleep 2
          done
          echo "health check never succeeded"
          exit 1
      - name: Sync specific VPS folder (example — only if needed)
        env:
          SSH_KEY: ${{ secrets.DEPLOY_SSH_KEY }}
        run: |
          # rsync, scp, or similar. Project-specific.
          echo "no-op — add real step here"
      - name: Notify Telegram (example — only if needed)
        env:
          BOT_TOKEN: ${{ secrets.TELEGRAM_NOTIFY_TOKEN }}
          CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: |
          curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
            -d "chat_id=${CHAT_ID}" \
            -d "text=deploy ok on ${GITHUB_REPOSITORY}@${GITHUB_SHA:0:7}"
```

**Invariant**: this workflow must **never** contain `curl -X POST .../coolify/.../deploy`. The GitHub App handles that. Duplicating the trigger from a workflow causes double-deploys and can race.

---

## Section 5 — Race condition handling

App and Actions start at roughly the same moment. For any Action that needs to check the deployed state (health check, smoke test, "tag as live"), use this polling pattern instead of `sleep`:

```bash
# Retry for ~60s, 2s between attempts
for i in $(seq 1 30); do
  if curl -sf "https://<URL>/<HEALTH_ENDPOINT>" > /dev/null; then
    echo "ready"; exit 0
  fi
  sleep 2
done
echo "never became healthy"; exit 1
```

Adjust the retry count based on typical build time. trdex's image is ~1.3 GB and rebuilds take 2–3 minutes on the VPS; retry budget should be 120+ seconds if Action needs post-deploy state.

---

## Section 6 — Diagnostics

**Symptom**: Push happens but no deployment starts.

1. **Check webhook exists**: `gh api repos/GravyaDev/<REPO>/hooks`. If empty, Section 2 didn't complete — redo.
2. **Check webhook deliveries**: GitHub → repo → Settings → Webhooks → click the Coolify webhook → "Recent Deliveries". Look for recent `push` events. If 404/500, Coolify isn't processing them — check Coolify app logs.
3. **Check Coolify app logs**: `ssh <VPS>` → `docker logs coolify --tail 100 | grep -i webhook`. Look for "received webhook from github" lines.
4. **Check branch filter**: in Coolify → app → Configuration, the branch MUST be `main` (or whatever you're pushing). A mismatch = silent no-op.
5. **Check path filter**: if "Watch Paths" is set in Coolify, pushes that don't touch those paths won't deploy. For general-purpose auto-deploy, leave it empty.
6. **Check `.github/workflows/*.yml` isn't double-triggering deploy**: `grep -r "coolify" .github/`. If a workflow calls the Coolify webhook directly, remove that step (redundant + race-prone).

**Symptom**: Deployment starts but image isn't updated (same SHA as before).

- Coolify "Redeploy" without "Force Rebuild" sometimes reuses a cached image. If you see the container still on the old commit, force a no-cache rebuild from Coolify UI. Not an App vs Actions problem.

---

## Section 7 — Multi-repo rollout

After this works on the first repo, replicate for the rest of Gravya:

1. The GitHub App is already installed at the org level — no re-install needed.
2. For each new repo, in Coolify → app → Source → switch to the **GitHub App** source (Section 2 step 5-7).
3. Verify with `gh api repos/GravyaDev/<REPO>/hooks` (Section 3).

Repos to cover: `trdex`, `gravya-platform`, `trdex-llm`, `gravya-ops`. One-minute ops per repo.

---

## Section 8 — Invariants / what NOT to do

- Never write credentials (tokens, SSH keys, webhook secrets) into the playbook or into committed workflow files. Use GitHub Secrets and Coolify env vars.
- Never call the Coolify deploy webhook from a workflow after the GitHub App is installed — duplicated trigger, race condition.
- Never skip the branch filter in Coolify — pushes to feature branches would deploy production otherwise.
- Never set `"Watch Paths"` to `.github/**` or `docs/**` only unless you **specifically** want docs/CI-only pushes to redeploy.
