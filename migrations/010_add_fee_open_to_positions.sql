-- Track the opening fee separately so P&L reflects full round-trip cost.
-- Previously only the close-side fee was subtracted from P&L (record_close_fill),
-- making the P&L inflated by ~0.1% per trade (one Binance taker fee).

ALTER TABLE positions ADD COLUMN IF NOT EXISTS fee_open DOUBLE PRECISION DEFAULT 0;
