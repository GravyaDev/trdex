-- Perpetual futures positions (shorts and leverage, trdex.risk.leverage).
-- leverage: isolated leverage the position was opened with (1 = spot or
--   unleveraged); budget stays the notional, margin = budget / leverage.
-- funding_paid_until: last funding timestamp (00/08/16 UTC) booked to the
--   ledger for this position in simulation; NULL = none yet (from opened_at).

ALTER TABLE positions ADD COLUMN IF NOT EXISTS leverage DOUBLE PRECISION NOT NULL DEFAULT 1;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS funding_paid_until TIMESTAMP;
