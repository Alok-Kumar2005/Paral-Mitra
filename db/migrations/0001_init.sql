-- Parali Mitra — Initial Schema
-- Migration: 0001_init.sql
-- Idempotent: safe to re-run via scripts/migrate.py
-- All monetary/area values: numeric. All timestamps: timestamptz.

BEGIN;

-- ── Migration tracking ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    text        PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

-- ── Farmer profiles ───────────────────────────────────────────────────────────
-- chat_id stored as text: Telegram IDs are 64-bit ints that can exceed
-- JSON safe-integer range; text is safe and consistent with webhook payloads.

CREATE TABLE IF NOT EXISTS farmers (
    chat_id          text        PRIMARY KEY,
    language         text        NOT NULL DEFAULT 'hi',
    lat              numeric(9,6),
    lon              numeric(9,6),
    village_text     text,
    district         text,
    state            text,
    acres            numeric(8,2),
    crop             text,
    sowing_deadline  date,
    consent_given_at timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    last_seen_at     timestamptz NOT NULL DEFAULT now()
);

-- ── Conversation memory ───────────────────────────────────────────────────────
-- chat_state: one row per farmer, holds rolling summary + version for
-- optimistic concurrency control (pg_advisory_xact_lock in PostgresClient).

CREATE TABLE IF NOT EXISTS chat_state (
    chat_id         text        PRIMARY KEY
                    REFERENCES farmers(chat_id) ON DELETE CASCADE,
    summary         text,
    summarized_upto bigint,     -- bigserial id of last message included in summary
    version         int         NOT NULL DEFAULT 0,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- chat_messages: individual turns, expire after retention window.
-- Index (chat_id, id DESC) serves paginated history loads.
-- Index (expires_at) serves prune_expired().

CREATE TABLE IF NOT EXISTS chat_messages (
    id         bigserial   PRIMARY KEY,
    chat_id    text        NOT NULL REFERENCES farmers(chat_id) ON DELETE CASCADE,
    role       text        NOT NULL CHECK (role IN ('user', 'assistant')),
    text       text        NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_id
    ON chat_messages (chat_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_chat_messages_expires_at
    ON chat_messages (expires_at);

-- ── Provider marketplace ──────────────────────────────────────────────────────
-- providers: CHCs and commercial buyers registered by operators.
-- Status lifecycle: PENDING -> VERIFIED (by admin) -> SUSPENDED / REJECTED.
-- telegram_chat_id UNIQUE NULL: set once the operator links their account.

CREATE TABLE IF NOT EXISTS providers (
    provider_id          text        PRIMARY KEY,
    provider_type        text        NOT NULL,       -- 'CHC' | 'BUYER'
    name                 text        NOT NULL,
    contact_phone        text        NOT NULL,
    telegram_chat_id     text        UNIQUE,         -- NULL until linked
    district             text        NOT NULL,
    state                text        NOT NULL,
    lat                  numeric(9,6) NOT NULL,
    lon                  numeric(9,6) NOT NULL,
    status               text        NOT NULL DEFAULT 'PENDING'
                         CHECK (status IN ('PENDING', 'VERIFIED', 'REJECTED', 'SUSPENDED')),
    verified_by          text,                       -- admin chat_id or 'system'
    verified_at          timestamptz,
    is_directory_listing bool        NOT NULL DEFAULT false,
    created_at           timestamptz NOT NULL DEFAULT now()
);

-- machines: agricultural equipment offered by CHC providers.
-- Index (district, machine_type): district-scoped listing by type.
-- Index (lat, lon): bounding-box pre-filter for nearby search.
-- Index (provider_id): admin/provider queries.

CREATE TABLE IF NOT EXISTS machines (
    machine_id           text         PRIMARY KEY,
    provider_id          text         REFERENCES providers(provider_id) ON DELETE SET NULL,
    machine_type         text         NOT NULL,
    village              text         NOT NULL,
    district             text         NOT NULL,
    lat                  numeric(9,6) NOT NULL,
    lon                  numeric(9,6) NOT NULL,
    rate_per_acre        numeric(10,2) NOT NULL,
    travel_charge_per_km numeric(8,2)  NOT NULL,
    service_radius_km    numeric(6,2)  NOT NULL,
    available_from       date          NOT NULL,
    blocked_dates        date[]        NOT NULL DEFAULT '{}',
    status               text          NOT NULL DEFAULT 'ACTIVE'
                         CHECK (status IN ('ACTIVE', 'INACTIVE')),
    rating_avg           numeric(3,2),
    rating_count         int           NOT NULL DEFAULT 0,
    source               text          NOT NULL DEFAULT 'MANUAL',
    is_synthetic         bool          NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_machines_district_type
    ON machines (district, machine_type);

CREATE INDEX IF NOT EXISTS idx_machines_lat_lon
    ON machines (lat, lon);

CREATE INDEX IF NOT EXISTS idx_machines_provider_id
    ON machines (provider_id);

-- buyers: commercial biomass buyers (CBG, biomass power, pellet mills).

CREATE TABLE IF NOT EXISTS buyers (
    buyer_id            text         PRIMARY KEY,
    provider_id         text         REFERENCES providers(provider_id) ON DELETE SET NULL,
    name                text         NOT NULL,
    buyer_type          text         NOT NULL,
    district            text         NOT NULL,
    lat                 numeric(9,6) NOT NULL,
    lon                 numeric(9,6) NOT NULL,
    price_per_tonne     numeric(10,2) NOT NULL,
    min_quantity_tonnes numeric(8,2)  NOT NULL,
    transport_terms     text          NOT NULL,
    phone               text          NOT NULL,
    source              text          NOT NULL DEFAULT 'MANUAL',
    is_synthetic        bool          NOT NULL DEFAULT false
);

-- bookings: farmer booking requests for machines and buyer dispatches.
-- Index (farmer_chat_id, created_at DESC): farmer booking history.
-- Index (provider_id, created_at DESC): provider job queue.

CREATE TABLE IF NOT EXISTS bookings (
    booking_id     text        PRIMARY KEY,
    farmer_chat_id text        NOT NULL REFERENCES farmers(chat_id),
    provider_id    text        REFERENCES providers(provider_id),
    option_type    text        NOT NULL CHECK (option_type IN ('IN_SITU', 'EX_SITU')),
    target_id      text        NOT NULL,
    acres          numeric(8,2) NOT NULL,
    requested_date date        NOT NULL,
    status         text        NOT NULL DEFAULT 'PENDING'
                   CHECK (status IN (
                       'PENDING', 'PENDING_MANUAL', 'CONFIRMED',
                       'REJECTED', 'EXPIRED', 'COMPLETED'
                   )),
    rating         smallint    CHECK (rating BETWEEN 1 AND 5),
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    completed_at   timestamptz
);

CREATE INDEX IF NOT EXISTS idx_bookings_farmer
    ON bookings (farmer_chat_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_bookings_provider
    ON bookings (provider_id, created_at DESC);

-- ── Environmental / operational tables ────────────────────────────────────────
-- hotspots: NASA FIRMS VIIRS active fire detections.
-- PRIMARY KEY (grid_cell, acq_date) also serves as the dedup constraint:
-- ON CONFLICT DO UPDATE on re-ingestion silently updates frp/confidence.
-- expires_at index serves prune_expired().

CREATE TABLE IF NOT EXISTS hotspots (
    grid_cell  text         NOT NULL,
    acq_date   date         NOT NULL,
    acq_time   text,
    lat        numeric(9,6) NOT NULL,
    lon        numeric(9,6) NOT NULL,
    frp        numeric(8,2) NOT NULL,
    confidence text         NOT NULL,
    expires_at timestamptz  NOT NULL,
    PRIMARY KEY (grid_cell, acq_date)
);

CREATE INDEX IF NOT EXISTS idx_hotspots_grid_date
    ON hotspots (grid_cell, acq_date);

CREATE INDEX IF NOT EXISTS idx_hotspots_expires_at
    ON hotspots (expires_at);

-- processed_updates: idempotency guard for Telegram update_ids.
-- Replaces DynamoDB TTL; rows pruned by prune_expired().

CREATE TABLE IF NOT EXISTS processed_updates (
    update_id  bigint      PRIMARY KEY,
    expires_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_processed_updates_expires
    ON processed_updates (expires_at);

-- geocode_cache: Nominatim reverse-geocoding cache.
-- payload jsonb stores the full Nominatim response for debugging.

CREATE TABLE IF NOT EXISTS geocode_cache (
    query_key  text         PRIMARY KEY,
    lat        numeric(9,6) NOT NULL,
    lon        numeric(9,6) NOT NULL,
    payload    jsonb        NOT NULL DEFAULT '{}',
    expires_at timestamptz  NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_geocode_cache_expires
    ON geocode_cache (expires_at);

-- ── Maintenance function ──────────────────────────────────────────────────────
-- Called from the EventBridge-scheduled Lambda (scheduler handler).
-- Postgres has no native TTL; this replaces DynamoDB's automatic TTL deletion.

CREATE OR REPLACE FUNCTION prune_expired() RETURNS void
LANGUAGE sql AS $$
    DELETE FROM chat_messages     WHERE expires_at < now();
    DELETE FROM hotspots          WHERE expires_at < now();
    DELETE FROM processed_updates WHERE expires_at < now();
    DELETE FROM geocode_cache     WHERE expires_at < now();
$$;

COMMIT;
