-- Kill switch persistent state.
-- Survives process restarts: if the kill switch was active when
-- the process died, it stays active on reboot.

CREATE TABLE IF NOT EXISTS kill_switch_state (
    id          INTEGER PRIMARY KEY DEFAULT 1,   -- singleton row
    active      BOOLEAN NOT NULL DEFAULT FALSE,
    reason      TEXT NOT NULL DEFAULT '',
    activated_at TIMESTAMPTZ,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Ensure only one row ever exists
    CONSTRAINT kill_switch_singleton CHECK (id = 1)
);

-- Seed with inactive state
INSERT INTO kill_switch_state (id, active, reason)
VALUES (1, FALSE, '')
ON CONFLICT (id) DO NOTHING;
