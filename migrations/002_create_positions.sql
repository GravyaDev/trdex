-- Migration 002: Create positions table for portfolio tracking
-- Run after 001_create_ohlcv.sql.
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS positions (
    id          BIGSERIAL PRIMARY KEY,
    symbol      VARCHAR(20)      NOT NULL,
    side        VARCHAR(5)       NOT NULL,   -- 'BUY' or 'SELL'
    entry_price NUMERIC(28, 8)   NOT NULL,
    amount      NUMERIC(28, 8)   NOT NULL,
    budget      NUMERIC(28, 8)   NOT NULL,   -- capital allocated (quote currency)
    source      VARCHAR(100)     NOT NULL DEFAULT 'manual',
    signal_id   VARCHAR(100),               -- traceability string, no FK
    status      VARCHAR(10)      NOT NULL DEFAULT 'open',  -- 'open' | 'closed'
    opened_at   TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    closed_at   TIMESTAMPTZ,
    exit_price  NUMERIC(28, 8)
);

CREATE INDEX IF NOT EXISTS ix_positions_symbol_status
    ON positions (symbol, status);

CREATE INDEX IF NOT EXISTS ix_positions_source_status
    ON positions (source, status);
