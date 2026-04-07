-- Migration 006: trdex Entity Graph (Tier 5 — Persistent Memory Stack)
-- Stores structured subject-predicate-object facts with temporal auditability.
-- valid_until = NULL means the fact is currently active.
-- Upsert pattern: invalidate old row (set valid_until), insert new row.
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS trdex_entity_graph (
    id           BIGSERIAL    PRIMARY KEY,
    subject_type VARCHAR(30)  NOT NULL,
    -- symbol | channel | strategy | portfolio
    subject_id   VARCHAR(100) NOT NULL,
    predicate    VARCHAR(60)  NOT NULL,
    -- volatility_regime | win_rate | correlates_with | last_signal | drawdown_pct | ...
    object_value JSONB,
    -- {"value": 0.62} or {"value": "high"} or arbitrary structured data
    object_id    VARCHAR(100),
    -- if fact is a relation to another entity (e.g. correlates_with ETH/USDT)
    confidence   REAL         NOT NULL DEFAULT 1.0,
    -- 1.0 = observed, <1.0 = inferred
    source       VARCHAR(30)  NOT NULL DEFAULT 'agent',
    -- agent | system | manual
    note         TEXT         NOT NULL DEFAULT '',
    valid_from   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    valid_until  TIMESTAMPTZ                           -- NULL = currently active
);

CREATE INDEX IF NOT EXISTS ix_entity_graph_subject
    ON trdex_entity_graph (subject_type, subject_id);

CREATE INDEX IF NOT EXISTS ix_entity_graph_predicate
    ON trdex_entity_graph (predicate);

CREATE INDEX IF NOT EXISTS ix_entity_graph_active
    ON trdex_entity_graph (subject_id, valid_until)
    WHERE valid_until IS NULL;
