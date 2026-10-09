-- Migration 010: agent_llm_usage (LLM cost tracking)
-- Logs every LLM call with token counts, cost, latency, and fallback status.
-- Used by cost guardrails (daily/monthly budget) and dashboard observability.
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS agent_llm_usage (
    id              BIGSERIAL    PRIMARY KEY,
    run_id          UUID         NOT NULL,
    agent_name      VARCHAR(40)  NOT NULL,
    provider        VARCHAR(20)  NOT NULL,
    model_id        VARCHAR(80)  NOT NULL,
    input_tokens    INTEGER      NOT NULL DEFAULT 0,
    output_tokens   INTEGER      NOT NULL DEFAULT 0,
    cost_usd        NUMERIC(10,6) NOT NULL DEFAULT 0,
    latency_ms      INTEGER      NOT NULL DEFAULT 0,
    fallback_used   BOOLEAN      NOT NULL DEFAULT FALSE,
    error           TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_llm_usage_agent
    ON agent_llm_usage (agent_name);

CREATE INDEX IF NOT EXISTS ix_llm_usage_created
    ON agent_llm_usage (created_at DESC);

CREATE INDEX IF NOT EXISTS ix_llm_usage_run
    ON agent_llm_usage (run_id);
