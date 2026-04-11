-- Migration 013: persistent stop-loss event log
-- Before this, StopLossMonitor kept fired events in a Python list
-- that was lost on every restart — so post-mortem / incident review
-- of a kill-switch trigger was impossible once the container cycled.
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS stop_loss_events (
    id            BIGSERIAL PRIMARY KEY,
    reason        VARCHAR(40)    NOT NULL,   -- matches StopReason enum
    symbol        VARCHAR(20),               -- NULL = portfolio-level event
    position_id   BIGINT,                    -- NULL for non-position events
    trigger_price NUMERIC(28, 8),
    entry_price   NUMERIC(28, 8),
    loss_pct      DOUBLE PRECISION,
    message       TEXT           NOT NULL DEFAULT '',
    fired_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_stop_loss_events_fired_at
    ON stop_loss_events (fired_at DESC);

CREATE INDEX IF NOT EXISTS ix_stop_loss_events_reason
    ON stop_loss_events (reason);
