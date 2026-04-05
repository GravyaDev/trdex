-- Migration 003: agent run history
-- Stores every Scout→Analyst→Risk→Executor cycle result

CREATE TABLE IF NOT EXISTS agent_runs (
    id          BIGSERIAL PRIMARY KEY,
    run_id      UUID        NOT NULL UNIQUE,
    symbol      TEXT        NOT NULL,
    ran_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Analyst output
    signal      TEXT        NOT NULL DEFAULT 'HOLD',  -- BUY | SELL | HOLD
    confidence  NUMERIC(5,4) NOT NULL DEFAULT 0,
    reasoning   TEXT        NOT NULL DEFAULT '',
    indicators  JSONB       NOT NULL DEFAULT '{}',

    -- Risk output
    risk_approved    BOOLEAN NOT NULL DEFAULT FALSE,
    risk_reason      TEXT    NOT NULL DEFAULT '',
    position_size    NUMERIC(10,6) NOT NULL DEFAULT 0,
    stop_loss_pct    NUMERIC(10,6) NOT NULL DEFAULT 0,
    take_profit_pct  NUMERIC(10,6) NOT NULL DEFAULT 0,

    -- Order output
    order_status     TEXT    NOT NULL DEFAULT 'skipped',  -- filled | rejected | skipped
    filled_price     NUMERIC(28,8),
    filled_qty       NUMERIC(28,8),
    order_message    TEXT    NOT NULL DEFAULT '',

    error            TEXT
);

CREATE INDEX IF NOT EXISTS ix_agent_runs_symbol ON agent_runs (symbol);
CREATE INDEX IF NOT EXISTS ix_agent_runs_ran_at ON agent_runs (ran_at DESC);
