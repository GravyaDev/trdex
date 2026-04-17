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

5. In Coolify → your application (e.g. `trdex`) → **Configuration** → **Source**.
6. Change the source from **Public Repository** to the new **GitHub App** source you just installed. Save.
7. Coolify now creates the webhook on GitHub automatically. No manual webhook creation needed.

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
