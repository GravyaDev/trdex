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

-- Unique constraint to support upsert idempotency.
-- Wrapped in a DO block so the migration stays idempotent: once compression
-- is enabled below, ALTER TABLE ADD CONSTRAINT is rejected by TimescaleDB,
-- so we only attempt it if the constraint isn't already there.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_ohlcv_symbol_tf_ts'
          AND conrelid = 'ohlcv'::regclass
    ) THEN
        ALTER TABLE ohlcv
            ADD CONSTRAINT uq_ohlcv_symbol_tf_ts
            UNIQUE (symbol, timeframe, timestamp);
    END IF;
END$$;

-- Covering index for common queries
CREATE INDEX IF NOT EXISTS ix_ohlcv_symbol_tf_ts
    ON ohlcv (symbol, timeframe, timestamp ASC);

-- Enable compression on the hypertable (required before add_compression_policy
-- on TimescaleDB >= 2.11). segmentby groups rows that compress and decompress
-- together: every query on this table filters by symbol+timeframe, so this is
-- the natural grouping.
ALTER TABLE ohlcv
    SET (
        timescaledb.compress,
        timescaledb.compress_segmentby = 'symbol,timeframe'
    );

-- Compression policy: compress chunks older than 7 days
SELECT add_compression_policy('ohlcv', INTERVAL '7 days', if_not_exists => TRUE);
