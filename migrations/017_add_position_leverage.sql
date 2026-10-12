-- Perpetual futures positions (shorts and leverage, trdex.risk.leverage).
-- venue: market the position lives on, 'spot' or 'usdm' (Binance USDⓈ-M
--   perpetuals). Closes are routed by it, so switching
--   thresholds.execution_venue never sends a close to the wrong market.
--   Rows that predate this migration were spot longs.
-- leverage: isolated leverage the position was opened with (1 on spot);
--   budget stays the notional, margin = budget / leverage.
-- funding_paid_until: last funding timestamp (00/08/16 UTC) booked to the
--   ledger for this position in simulation; NULL = none yet (from opened_at).

ALTER TABLE positions ADD COLUMN IF NOT EXISTS venue VARCHAR(8) NOT NULL DEFAULT 'spot';
ALTER TABLE positions ADD COLUMN IF NOT EXISTS leverage DOUBLE PRECISION NOT NULL DEFAULT 1;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS funding_paid_until TIMESTAMP;
