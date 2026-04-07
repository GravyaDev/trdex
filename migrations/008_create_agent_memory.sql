-- Migration 008: trdex_agent_memory (Tier 2 — Persistent Memory Stack)
-- Operational structured memory per agent.
-- Each row is a typed observation/state that persists across agent runs.
--
-- Examples:
--   ('analyst', 'indicator_observation', 'BTC/USDT:rsi_pattern', {"pattern": "double_bottom", "ts": "..."})
--   ('risk',    'rejection_stat',         'gate_drawdown:7d',      {"count": 12, "rate": 0.08})
--   ('executor','slippage_sample',        'BTC/USDT:1h',           {"avg_bps": 4.2, "n": 30})
--
-- Upsert by (agent, kind, key). expires_at is optional TTL for short-lived memories.
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS trdex_agent_memory (
    id           BIGSERIAL    PRIMARY KEY,
    agent        VARCHAR(40)  NOT NULL,
    -- analyst | risk | executor | scout | stop_loss_monitor | system
    kind         VARCHAR(60)  NOT NULL,
    -- free-form category, e.g. indicator_observation, rejection_stat, slippage_sample
    key          VARCHAR(160) NOT NULL,
    -- composite identifier within the kind, e.g. "BTC/USDT:rsi"
    value        JSONB        NOT NULL DEFAULT '{}'::jsonb,
    confidence   REAL         NOT NULL DEFAULT 1.0,
    source       VARCHAR(40)  NOT NULL DEFAULT 'agent',
    -- agent | system | manual
    note         TEXT         NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    expires_at   TIMESTAMPTZ                            -- NULL = never expires
);

-- One active row per (agent, kind, key); upsert target.
CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_memory_triple
    ON trdex_agent_memory (agent, kind, key);

CREATE INDEX IF NOT EXISTS ix_agent_memory_agent_kind
    ON trdex_agent_memory (agent, kind);

CREATE INDEX IF NOT EXISTS ix_agent_memory_updated_at
    ON trdex_agent_memory (updated_at DESC);

-- Partial index for permanent rows (faster active lookups in the common case).
-- NOTE: we cannot include ``OR expires_at > NOW()`` in the predicate because
-- Postgres requires index predicate functions to be IMMUTABLE, and NOW() is
-- only STABLE. Most memories are permanent (no TTL), so this index still
-- covers the hot path. Expired-row filtering is done at query time.
CREATE INDEX IF NOT EXISTS ix_agent_memory_active
    ON trdex_agent_memory (agent, kind)
    WHERE expires_at IS NULL;
