# Parali Mitra — Data Model

> Tables, indexes, and the queries each index serves.

---

## Schema Overview

All tables live in the `public` schema (or an isolated test schema per pytest run).
All timestamps are `timestamptz` (UTC). Monetary and area values are `numeric`.
`farmers.chat_id` is stored as `text`; Python always works with `int` (cast at DB boundary).

---

## Tables

### `farmers`

Persistent farmer profile. One row per Telegram user.

| Column | Type | Notes |
|---|---|---|
| `chat_id` | `text PK` | Telegram chat ID (64-bit int stored as text) |
| `language` | `text` | `hi` / `pa` / `en` (default `hi`) |
| `lat`, `lon` | `numeric(9,6)` | Farm GPS coordinates |
| `village_text` | `text` | Free-text village + district |
| `district`, `state` | `text` | Normalised location fields |
| `acres` | `numeric(8,2)` | Farm area |
| `crop` | `text` | Current crop type |
| `sowing_deadline` | `date` | Target wheat sowing date |
| `consent_given_at` | `timestamptz` | GDPR consent timestamp |
| `created_at` | `timestamptz` | Profile creation |
| `last_seen_at` | `timestamptz` | Touched on every `get_session()` call |

**Queries served:** `get_session(chat_id)`, `put_session(session)`, `forget_farmer(chat_id)`

---

### `chat_state`

One row per farmer. Holds the rolling LLM summary and optimistic concurrency version.

| Column | Type | Notes |
|---|---|---|
| `chat_id` | `text PK FK → farmers` | Cascades on DELETE |
| `summary` | `text` | LLM-generated rolling summary text |
| `summarized_upto` | `bigint` | `id` of last `chat_messages` row included in summary |
| `version` | `int` | Incremented on every UPDATE (optimistic concurrency) |
| `updated_at` | `timestamptz` | |

**Queries served:** `get_chat_state(chat_id)`, `put_chat_state(state)`
**Lock:** `pg_advisory_xact_lock(hashtext(chat_id))` on every write.

---

### `chat_messages`

Individual conversation turns. Rows expire after a retention window and are pruned by `prune_expired()`.

| Column | Type | Notes |
|---|---|---|
| `id` | `bigserial PK` | Auto-incrementing message ID |
| `chat_id` | `text FK → farmers` | Cascades on DELETE |
| `role` | `text CHECK` | `user` or `assistant` |
| `text` | `text` | Message content |
| `created_at` | `timestamptz` | |
| `expires_at` | `timestamptz` | Prune target; replaces DynamoDB TTL epoch |

**Indexes:**
- `(chat_id, id DESC)` — `load_chat_messages()`: paginated history load, newest-first inner sort
- `(expires_at)` — `prune_expired()`: batch delete of expired rows

---

### `providers`

Registered CHC operators and commercial buyers. Status lifecycle: `PENDING → VERIFIED → SUSPENDED / REJECTED`.

| Column | Type | Notes |
|---|---|---|
| `provider_id` | `text PK` | |
| `provider_type` | `text` | `CHC` or `BUYER` |
| `name`, `contact_phone` | `text` | |
| `telegram_chat_id` | `text UNIQUE NULL` | Set once the operator links their Telegram account |
| `district`, `state` | `text` | |
| `lat`, `lon` | `numeric(9,6)` | |
| `status` | `text CHECK` | `PENDING / VERIFIED / REJECTED / SUSPENDED` |
| `verified_by` | `text` | Admin `chat_id` or `system` |
| `verified_at` | `timestamptz` | |
| `is_directory_listing` | `bool` | `true` for phone-collected directory data |
| `created_at` | `timestamptz` | |

**Queries served:** `get_provider()`, `put_provider()`, `update_provider_status()`

---

### `machines`

Agricultural equipment offered by CHC providers.

| Column | Type | Notes |
|---|---|---|
| `machine_id` | `text PK` | |
| `provider_id` | `text FK → providers NULL` | `SET NULL` on provider delete |
| `machine_type` | `text` | `SUPER_SEEDER`, `HAPPY_SEEDER`, etc. |
| `village`, `district` | `text` | Base location |
| `lat`, `lon` | `numeric(9,6)` | |
| `rate_per_acre` | `numeric(10,2)` | INR |
| `travel_charge_per_km` | `numeric(8,2)` | INR |
| `service_radius_km` | `numeric(6,2)` | |
| `available_from` | `date` | |
| `blocked_dates` | `date[]` | |
| `status` | `text CHECK` | `ACTIVE / INACTIVE` |
| `rating_avg` | `numeric(3,2)` | |
| `rating_count` | `int` | |
| `source` | `text` | `CHC_PORTAL / DIRECT / SEED` |
| `is_synthetic` | `bool` | |

**Indexes:**
- `(district, machine_type)` — `list_machines(district=...)`: district-scoped type filtering
- `(lat, lon)` — `list_machines_nearby()`: bounding-box pre-filter before haversine
- `(provider_id)` — provider admin queries

**Nearby search algorithm** (no PostGIS):
1. SQL: bounding-box filter `lat BETWEEN lat_min AND lat_max AND lon BETWEEN lon_min AND lon_max`, join `providers WHERE status='VERIFIED'` and `machines WHERE status='ACTIVE'`
2. Python: exact haversine distance filter on candidates

---

### `buyers`

Commercial biomass buyers (CBG plants, biomass power, pellet mills).

| Column | Type | Notes |
|---|---|---|
| `buyer_id` | `text PK` | |
| `provider_id` | `text FK → providers NULL` | |
| `name`, `buyer_type` | `text` | |
| `district` | `text` | |
| `lat`, `lon` | `numeric(9,6)` | |
| `price_per_tonne` | `numeric(10,2)` | INR |
| `min_quantity_tonnes` | `numeric(8,2)` | |
| `transport_terms` | `text` | `EX_FARM / DELIVERED / NEGOTIABLE` |
| `phone` | `text` | |
| `source`, `is_synthetic` | | |

---

### `bookings`

Farmer booking requests for machines and buyer dispatches.

| Column | Type | Notes |
|---|---|---|
| `booking_id` | `text PK` | |
| `farmer_chat_id` | `text FK → farmers` | |
| `provider_id` | `text FK → providers NULL` | |
| `option_type` | `text CHECK` | `IN_SITU / EX_SITU` |
| `target_id` | `text` | `machine_id` or `buyer_id` |
| `acres` | `numeric(8,2)` | |
| `requested_date` | `date` | |
| `status` | `text CHECK` | `PENDING / PENDING_MANUAL / CONFIRMED / REJECTED / EXPIRED / COMPLETED` |
| `rating` | `smallint NULL` | 1–5 |
| `created_at`, `updated_at` | `timestamptz` | |
| `completed_at` | `timestamptz NULL` | Set when status = COMPLETED |

**Indexes:**
- `(farmer_chat_id, created_at DESC)` — `list_bookings_by_farmer()`: farmer booking history
- `(provider_id, created_at DESC)` — provider job queue

---

### `hotspots`

NASA FIRMS VIIRS active fire detections. Deduped on `(grid_cell, acq_date)`.

| Column | Type | Notes |
|---|---|---|
| `grid_cell` | `text PK(1)` | Spatial grid identifier |
| `acq_date` | `date PK(2)` | Acquisition date |
| `acq_time` | `text` | HHMM UTC |
| `lat`, `lon` | `numeric(9,6)` | |
| `frp` | `numeric(8,2)` | Fire Radiative Power (MW) |
| `confidence` | `text` | `low / nominal / high` |
| `expires_at` | `timestamptz` | Prune target (replaces DynamoDB TTL epoch) |

**Upsert:** `ON CONFLICT (grid_cell, acq_date) DO UPDATE` — re-ingested FIRMS data silently refreshes `frp`, `confidence`, `expires_at`.

**Indexes:**
- `(grid_cell, acq_date)` — primary key doubles as dedup index
- `(expires_at)` — `prune_expired()`

---

### `processed_updates`

Idempotency guard. Prevents double-processing of the same Telegram `update_id`.

| Column | Type | Notes |
|---|---|---|
| `update_id` | `bigint PK` | Telegram update ID |
| `expires_at` | `timestamptz` | Default 24-hour TTL |

**Index:** `(expires_at)` — `prune_expired()`

---

### `geocode_cache`

Nominatim reverse-geocoding cache. Avoids re-querying for the same village text.

| Column | Type | Notes |
|---|---|---|
| `query_key` | `text PK` | Normalised query string |
| `lat`, `lon` | `numeric(9,6)` | |
| `payload` | `jsonb` | Full Nominatim response |
| `expires_at` | `timestamptz` | Default 7-day TTL |

**Index:** `(expires_at)` — `prune_expired()`

---

### `schema_migrations`

Migration tracking. Managed by `scripts/migrate.py`.

| Column | Type | Notes |
|---|---|---|
| `version` | `text PK` | Migration filename stem (e.g. `0001_init`) |
| `applied_at` | `timestamptz` | |

---

## `prune_expired()` Function

SQL function called from the EventBridge-scheduled Lambda (scheduler handler).
Postgres has no native row TTL; this replaces DynamoDB's automatic TTL deletion.

```sql
DELETE FROM chat_messages     WHERE expires_at < now();
DELETE FROM hotspots          WHERE expires_at < now();
DELETE FROM processed_updates WHERE expires_at < now();
DELETE FROM geocode_cache     WHERE expires_at < now();
```

Called via `PostgresClient.prune_expired()` → `SELECT prune_expired()`.
