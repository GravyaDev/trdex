-- Migration 011: relax signal_outcomes for observe-only signal tracking
-- Step 1 of Telegram Signal Integration records signals BEFORE they have
-- an outcome (exit_price/closed_at unknown until TP/SL post-hoc eval).
-- Idempotent: safe to re-run.

ALTER TABLE signal_outcomes
    ALTER COLUMN exit_price DROP NOT NULL;

ALTER TABLE signal_outcomes
    ALTER COLUMN budget SET DEFAULT 0;
