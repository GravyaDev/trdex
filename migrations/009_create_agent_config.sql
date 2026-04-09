-- Migration 009: agent_config (LLM agent configuration)
-- Stores per-agent LLM configuration: model, prompts, sampling parameters.
-- Dashboard reads/writes this table. Agent nodes read at cycle start.
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS agent_config (
    id              BIGSERIAL    PRIMARY KEY,
    agent_name      VARCHAR(40)  NOT NULL UNIQUE,

    -- LLM provider settings
    provider        VARCHAR(20)  NOT NULL DEFAULT 'anthropic',
    model_id        VARCHAR(80)  NOT NULL DEFAULT 'claude-haiku-4-5-20251001',

    -- Sampling parameters (CHECK constraints prevent invalid config via dashboard)
    temperature     REAL         NOT NULL DEFAULT 0.3
        CHECK (temperature >= 0.0 AND temperature <= 2.0),
    max_tokens      INTEGER      NOT NULL DEFAULT 1024
        CHECK (max_tokens >= 64 AND max_tokens <= 8192),
    top_p           REAL         NOT NULL DEFAULT 1.0
        CHECK (top_p >= 0.0 AND top_p <= 1.0),

    -- Prompt configuration (size cap prevents token budget blow-up)
    system_prompt   TEXT         NOT NULL DEFAULT ''
        CHECK (LENGTH(system_prompt) < 16384),

    -- Feature flags
    llm_enabled     BOOLEAN      NOT NULL DEFAULT FALSE,

    -- Metadata
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Seed defaults for each agent
INSERT INTO agent_config (agent_name, provider, model_id, temperature, max_tokens, llm_enabled)
VALUES
    ('scout',    'anthropic', 'claude-haiku-4-5-20251001',   0.2, 512,  FALSE),
    ('analyst',  'anthropic', 'claude-sonnet-4-6-20250514', 0.3, 1024, FALSE),
    ('risk',     'anthropic', 'claude-haiku-4-5-20251001',   0.1, 256,  FALSE),
    ('executor', 'anthropic', 'claude-haiku-4-5-20251001',   0.0, 256,  FALSE)
ON CONFLICT (agent_name) DO NOTHING;
