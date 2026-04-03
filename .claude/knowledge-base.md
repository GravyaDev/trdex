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
- **For every third-party API or tool, ALWAYS access the official documentation online before writing code.** Verify current API version, updated endpoints, parameters, and deprecations. If documentation is not accessible, ask the user to provide it before proceeding. Never assume versions or behavior from training data — APIs evolve. [Source: user override 2026-04-02]
- **When implementing a client for a third-party API, ALWAYS read the rate limiting section of the official docs before writing code.** Implement the rate limiter based on real API signals (response headers, specific error codes) — not on local estimates (token bucket, own counters). Handle both application-level and global/BUC throttle if provided by the API. [Source: user override 2026-04-02]
- **ALWAYS implement proportional throttle based on current utilization reported by the API.** If the documentation specifies explicit thresholds, use them. If not, apply broadly conservative limits (e.g. start slowing at 60%, near-stop at 85%, full stop at 95%). An account banned for rate-limit abuse is unrecoverable on many platforms (Meta especially). Better to slow down heavily than exceed the limit. The delay curve must be convex, not linear: ban risk grows exponentially approaching 100%. [Source: user override 2026-04-02]
- **Before coding any API integration from scratch, check https://github.com/public-apis/public-apis first.** 1,426 free public APIs across 51 categories. If a ready-made API exists for the needed data or capability, use it. Only write a custom integration if no suitable option is found in that catalog. [Source: user override 2026-03-25]
- **All commits must use the Co-Authored-By identity configured during onboarding.** Check the "Commit Identity" entry in this file for the exact name and email. Never use a generic Claude attribution. [Source: system rule]
- **/brainstorm-session must end explicitly BEFORE any transition to practical work.** When ideas are ready, use the skill's final summary and wait for explicit user input (new command, approval, planning). Do not start `/plan`, `/team`, or implementation without an explicit "end session". [Source: user override 2026-03-30]

## Platform & Tool Rules
- **Windows + pnpm: inline env vars don't work.** `VAR=value docker compose up` fails on Windows. Always use a `.env` file in the project root. [Source: empirical 2026-03-27]

## Project Patterns
- (none yet)

## Dynamic Architecture Rules
- (none yet)

## Known Failure Modes
- (none yet)