# Universal Rules

Cross-project rules that apply to **every** Kloudify deployment. Shipped with
the Kloudify base repo, versioned in git. Read by ALL agents and sessions at
startup, before any project-specific knowledge.

These rules are NOT project-specific. They encode platform truths, API
integration discipline, and Kloudify's own behavioral contracts. If you need
to add a rule that only applies to one project, put it in
`.claude/knowledge-base.md` instead.

**Authoring policy**: edited only in the Kloudify base repo (via PR). Do NOT
edit this file in a deployment — your changes will be overwritten on the next
Kloudify update, and you are changing a rule for every other project too.

## Provenance Hierarchy
Every entry MUST cite its source using one of:
- `[Source: user override YYYY-MM-DD]` — User explicitly corrected something
- `[Source: empirical YYYY-MM-DD]` — Verified through testing or data
- `[Source: agent inference YYYY-MM-DD]` — Pattern observed by an agent, confirmed by auditor

## API & Integration Rules
- **For every third-party API or tool, ALWAYS access the official documentation online before writing code.** Verify current API version, updated endpoints, parameters, and deprecations. If documentation is not accessible, ask the user to provide it before proceeding. Never assume versions or behavior from training data — APIs evolve. [Source: user override 2026-04-02]
- **When implementing a client for a third-party API, ALWAYS read the rate limiting section of the official docs before writing code.** Implement the rate limiter based on real API signals (response headers, specific error codes) — not on local estimates (token bucket, own counters). Handle both application-level and global/BUC throttle if provided by the API. [Source: user override 2026-04-02]
- **ALWAYS implement proportional throttle based on current utilization reported by the API.** If the documentation specifies explicit thresholds, use them. If not, apply broadly conservative limits (e.g. start slowing at 60%, near-stop at 85%, full stop at 95%). An account banned for rate-limit abuse is unrecoverable on many platforms (Meta especially). Better to slow down heavily than exceed the limit. The delay curve must be convex, not linear: ban risk grows exponentially approaching 100%. [Source: user override 2026-04-02]
- **Before coding any API integration from scratch, check https://github.com/public-apis/public-apis first.** 1,426 free public APIs across 51 categories. If a ready-made API exists for the needed data or capability, use it. Only write a custom integration if no suitable option is found in that catalog. [Source: user override 2026-03-25]

## Kloudify Behavioral Rules
- **/brainstorm-session must end explicitly BEFORE any transition to practical work.** When ideas are ready, use the skill's final summary and wait for explicit user input (new command, approval, planning). Do not start `/plan`, `/team`, or implementation without an explicit "end session". [Source: user override 2026-03-30]
- **WebFetch must always go through Jina Reader** (`https://r.jina.ai/<URL>`). Direct WebFetch calls bypass markdown conversion, ad stripping, and significant token savings. The only automatic exceptions are loopback addresses (Jina is a public proxy and cannot reach private networks). For pages Jina genuinely cannot serve (login-required, binary downloads, private services), STOP and ask the user for explicit per-URL authorization — do not retry raw WebFetch on your own initiative. Enforced mechanically by `.claude/hooks/guard-webfetch-jina.sh` (HARD BLOCK). [Source: user override 2026-04-08]

## Platform & Tool Rules
- **Windows + pnpm: inline env vars don't work.** `VAR=value docker compose up` fails on Windows. Always use a `.env` file in the project root. [Source: empirical 2026-03-27]
- **Bash aggregation: prefer single-pass awk over nested while/read loops.** When aggregating data from log files or pipe-separated text in bash hooks, use one awk expression that builds the result in a single pass instead of nesting `while read` + inner `awk` + variable accumulation. Nested aggregation in bash is fragile to whitespace, CRLF, empty fields, and IFS edge cases — a single awk script with an associative array (`counts[$3]++`) is more robust, more readable, and easier to debug. Apply this whenever a hook needs to count occurrences, find a max/top-N, or group by a column. [Source: empirical 2026-04-07]
