-- Migration 005: Telegram signal outcomes
-- Persists closed signal results for per-source reliability tracking.
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS signal_outcomes (
    id          BIGSERIAL PRIMARY KEY,
    source      VARCHAR(100)   NOT NULL,
    symbol      VARCHAR(20)    NOT NULL,
    direction   VARCHAR(5)     NOT NULL,   -- BUY | SELL
    entry_price NUMERIC(28, 8) NOT NULL,
    exit_price  NUMERIC(28, 8) NOT NULL,
    budget      NUMERIC(28, 8) NOT NULL,
    executed_at TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    closed_at   TIMESTAMPTZ,
    note        TEXT           NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_signal_outcomes_source
    ON signal_outcomes (source);

CREATE INDEX IF NOT EXISTS ix_signal_outcomes_executed_at
    ON signal_outcomes (executed_at DESC);
