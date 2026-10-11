-- Parali Mitra — Lender (Individual Machine Owner) Feature
-- Migration: 0004_lender.sql
-- Idempotent: safe to re-run via scripts/migrate.py

BEGIN;

-- ── Extend providers.provider_type CHECK to include 'LENDER' ─────────────────
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_class cl ON cl.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = cl.relnamespace
        WHERE cl.relname = 'providers'
          AND n.nspname = current_schema()
          AND c.contype = 'c'
          AND pg_get_constraintdef(c.oid) LIKE '%provider_type%'
    ) LOOP
        EXECUTE 'ALTER TABLE providers DROP CONSTRAINT IF EXISTS ' || quote_ident(r.conname);
    END LOOP;
END;
$$;

ALTER TABLE providers
    ADD CONSTRAINT providers_type_check
    CHECK (provider_type IN ('CHC', 'BUYER', 'LENDER'));

-- ── Add phone_verified column to providers ────────────────────────────────────
ALTER TABLE providers ADD COLUMN IF NOT EXISTS phone_verified bool NOT NULL DEFAULT false;

-- ── Add terms_note column to machines ─────────────────────────────────────────
ALTER TABLE machines ADD COLUMN IF NOT EXISTS terms_note text
    CHECK (terms_note IS NULL OR length(terms_note) <= 160);

-- ── Record Migration ──────────────────────────────────────────────────────────

INSERT INTO schema_migrations (version, applied_at)
VALUES ('0004_lender.sql', now())
ON CONFLICT (version) DO NOTHING;

COMMIT;
