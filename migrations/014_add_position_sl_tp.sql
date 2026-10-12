-- Add per-position stop-loss and take-profit percentages.
-- Set by the Risk gate at open time (from LLM suggestion or defaults).
-- Read by StopLossMonitor to enforce per-position thresholds.
-- Nullable: existing positions use the global/symbol fallback.

ALTER TABLE positions ADD COLUMN IF NOT EXISTS stop_loss_pct DOUBLE PRECISION;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS take_profit_pct DOUBLE PRECISION;
