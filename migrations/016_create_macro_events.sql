-- Migration 016: economic calendar events for the macro entry gate
-- (trdex.market.macro_calendar). Each refresh replaces the fetched week
-- for its source; past weeks stay, so the table accumulates a history
-- that a future backtest can replay. Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS macro_events (
    id          BIGSERIAL PRIMARY KEY,
    source      VARCHAR(40)  NOT NULL,   -- e.g. forexfactory
    currency    VARCHAR(10)  NOT NULL,   -- USD, EUR, ... (Forex Factory "country")
    title       TEXT         NOT NULL,
    event_time  TIMESTAMPTZ  NOT NULL,
    impact      VARCHAR(16)  NOT NULL,   -- High | Medium | Low | Holiday
    forecast    TEXT,
    previous    TEXT,
    fetched_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_macro_events UNIQUE (source, currency, title, event_time)
);

CREATE INDEX IF NOT EXISTS ix_macro_events_time ON macro_events (event_time);
