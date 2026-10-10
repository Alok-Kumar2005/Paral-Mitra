-- Parali Mitra — Provider Marketplace & Booking Enhancements
-- Migration: 0002_marketplace.sql
-- Idempotent: safe to re-run via scripts/migrate.py

BEGIN;

-- ── Interactive Chat Flow State ──────────────────────────────────────────────
-- chat_flow: holds state machine for multi-step interactive flows (e.g. /owner registration).

CREATE TABLE IF NOT EXISTS chat_flow (
    chat_id      text        PRIMARY KEY,
    flow         text        NOT NULL,
    step         text        NOT NULL,
    data         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    attempts     int         NOT NULL DEFAULT 0,
    locked_until timestamptz,
    updated_at   timestamptz NOT NULL DEFAULT now()
);

-- ── Booking Table Enhancements ────────────────────────────────────────────────
-- Add auto-expiry and audit columns for booking decisions.

ALTER TABLE bookings ADD COLUMN IF NOT EXISTS expires_at timestamptz;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS decided_at timestamptz;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS decided_by text;

-- ── Performance & Sweeper Indexes ─────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_bookings_status_expires
    ON bookings (status, expires_at);

CREATE INDEX IF NOT EXISTS idx_providers_status
    ON providers (status);

-- ── Record Migration ──────────────────────────────────────────────────────────

INSERT INTO schema_migrations (version, applied_at)
VALUES ('0002_marketplace.sql', now())
ON CONFLICT (version) DO NOTHING;

COMMIT;
