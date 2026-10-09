-- Migration 011: extend agent_runs for LLM fields
-- Adds columns for LLM-specific data: whether LLM was used,
-- suggested SL/TP from the LLM, and optional risk annotation.
-- Idempotent: safe to re-run (IF NOT EXISTS on ALTER not supported
-- by Postgres, so we use DO blocks with column existence checks).

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'agent_runs' AND column_name = 'llm_used'
    ) THEN
        ALTER TABLE agent_runs ADD COLUMN llm_used BOOLEAN DEFAULT FALSE;
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'agent_runs' AND column_name = 'suggested_sl'
    ) THEN
        ALTER TABLE agent_runs ADD COLUMN suggested_sl NUMERIC(10,6);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'agent_runs' AND column_name = 'suggested_tp'
    ) THEN
        ALTER TABLE agent_runs ADD COLUMN suggested_tp NUMERIC(10,6);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'agent_runs' AND column_name = 'risk_annotation'
    ) THEN
        ALTER TABLE agent_runs ADD COLUMN risk_annotation TEXT;
    END IF;
END $$;
