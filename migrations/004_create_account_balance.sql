-- Migration 004: Account balance ledger
-- Tracks every cash movement (deposits, withdrawals, trade fills).
-- Current balance = latest balance_after. Peak equity = MAX(balance_after).
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS account_balance (
    id           BIGSERIAL PRIMARY KEY,
    event_type   VARCHAR(30)    NOT NULL,
    -- deposit | withdrawal | trade_fill | fee | manual_adjustment
    amount       NUMERIC(28, 8) NOT NULL,   -- positive = credit, negative = debit
    balance_after NUMERIC(28, 8) NOT NULL,
    note         TEXT           NOT NULL DEFAULT '',
    recorded_at  TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_account_balance_recorded_at
    ON account_balance (recorded_at DESC);

CREATE INDEX IF NOT EXISTS ix_account_balance_event_type
    ON account_balance (event_type);

-- Seed the initial balance if table is empty (10,000 USDT default)
INSERT INTO account_balance (event_type, amount, balance_after, note)
SELECT 'deposit', 10000, 10000, 'Initial balance — set TRDEX_INITIAL_BALANCE to override'
WHERE NOT EXISTS (SELECT 1 FROM account_balance);
