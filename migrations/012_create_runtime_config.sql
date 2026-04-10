-- Persistent runtime configuration.
--
-- Replaces volatile in-memory overrides (globals, instance attrs) with
-- DB-backed config. Env vars seed this table on first boot only; after
-- that the DB is the source of truth and changes via the dashboard or
-- API take effect immediately and survive restarts.

CREATE TABLE IF NOT EXISTS runtime_config (
    category    TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL DEFAULT '',
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (category, key)
);

CREATE INDEX IF NOT EXISTS idx_runtime_config_category
    ON runtime_config (category);
