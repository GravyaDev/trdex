-- Per-symbol risk threshold overrides.
--
-- When a row exists for a symbol, StopLossMonitor uses the values
-- here instead of the adaptive CV-based defaults. Any column left
-- NULL falls back to the adaptive calculation (max(base, mult×CV)).
--
-- If no row exists for a symbol, the monitor uses the adaptive
-- formula with the global base thresholds from env vars.

CREATE TABLE IF NOT EXISTS symbol_config (
    symbol              TEXT PRIMARY KEY,
    sl_pct              DOUBLE PRECISION,       -- override stop-loss %  (NULL = adaptive)
    tp_pct              DOUBLE PRECISION,       -- override take-profit % (NULL = adaptive)
    trailing_pct        DOUBLE PRECISION,       -- override trailing stop % (NULL = adaptive)
    notes               TEXT DEFAULT '',
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Index not needed: primary key on symbol is already an index, and
-- the table will have at most a few dozen rows (one per traded pair).
