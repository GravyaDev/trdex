-- Migration 001: Create OHLCV hypertable
-- Run once after TimescaleDB extension is enabled.
-- Idempotent: safe to re-run.

CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

CREATE TABLE IF NOT EXISTS ohlcv (
    id          BIGSERIAL,
    symbol      VARCHAR(20)  NOT NULL,
    timeframe   VARCHAR(10)  NOT NULL,
    timestamp   TIMESTAMPTZ  NOT NULL,
    open        DOUBLE PRECISION NOT NULL,
    high        DOUBLE PRECISION NOT NULL,
    low         DOUBLE PRECISION NOT NULL,
    close       DOUBLE PRECISION NOT NULL,
    volume      DOUBLE PRECISION NOT NULL,
    source      VARCHAR(30)  NOT NULL DEFAULT 'binance',
    PRIMARY KEY (id, timestamp)
);

-- TimescaleDB hypertable on timestamp
SELECT create_hypertable(
    'ohlcv', 'timestamp',
    if_not_exists => TRUE,
    migrate_data  => TRUE
);

-- Unique constraint to support upsert idempotency
ALTER TABLE ohlcv
    DROP CONSTRAINT IF EXISTS uq_ohlcv_symbol_tf_ts;

ALTER TABLE ohlcv
    ADD CONSTRAINT uq_ohlcv_symbol_tf_ts
    UNIQUE (symbol, timeframe, timestamp);

-- Covering index for common queries
CREATE INDEX IF NOT EXISTS ix_ohlcv_symbol_tf_ts
    ON ohlcv (symbol, timeframe, timestamp ASC);

-- Compression policy: compress chunks older than 7 days
SELECT add_compression_policy('ohlcv', INTERVAL '7 days', if_not_exists => TRUE);
