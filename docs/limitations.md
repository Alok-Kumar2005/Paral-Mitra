# Parali Mitra — Known Limitations

> Operational limitations, trade-offs, and their mitigations.

---

## 1. Neon Cold-Start Latency

**What:** Neon scales to zero after ~5 minutes of inactivity. The first Lambda invocation
after an idle period must wake Neon, which adds **~1–2 seconds** of connection latency.

**Impact:** The first message after a long idle period may feel slow to respond.

**Mitigation:**
- `PostgresClient` retries the connection 3 times with 0.5 / 1.0 / 2.0 s backoff.
- If all retries fail, a `ServiceUnavailableError` is raised and the bot sends:
  *"⏳ Service is waking up — please try again in a minute."*
- EventBridge can ping the endpoint on a schedule to keep Neon warm during harvest season.

---

## 2. No PostGIS — Bounding-Box Approximation

**What:** `list_machines_nearby()` uses a flat-earth bounding-box pre-filter in SQL
(111 km per degree latitude, adjusted for cos(lat) for longitude), then computes exact
haversine distance in Python.

**Impact:** At large radii (>150 km), the flat-earth approximation introduces up to
~1% error in the bounding box. No machines are falsely excluded (the box is slightly
larger than needed), but a small number of extra candidates are fetched and then
filtered out by haversine in Python.

**Mitigation:** All farming areas served are within a ~300 km region of Punjab/Haryana.
The approximation error is negligible at this scale. PostGIS would require a VPC-attached
RDS/Aurora instance, which conflicts with the Neon serverless model.

---

## 3. Lambda Single-Connection Model

**What:** `PostgresClient` reuses one module-level `psycopg.Connection` across Lambda
invocations within the same execution environment. This is safe for SQS FIFO queues
with a batch size of 1 (the default), but is **not safe** for concurrent invocations
sharing the same execution environment.

**Impact:** If Lambda scales horizontally (multiple concurrent execution environments),
each environment has its own independent connection — no conflict. However, if two
SQS messages for the same `chat_id` are delivered to the **same** execution environment
concurrently (which Lambda does not do in standard invocation mode), data races could
theoretically occur.

**Mitigation:**
- SQS Standard Queue with `MaxConcurrency=1` per Lambda function alias prevents
  concurrent invocations to the same environment.
- `pg_advisory_xact_lock(hashtext(chat_id))` is used on all `chat_state` and
  `chat_messages` writes to serialize access at the database level.

---

## 4. No Automatic Cross-Backend Fallback

**What:** `get_db_client()` raises `ServiceUnavailableError` if `DB_MODE=postgres`
and the connection fails. There is no silent fallback to `InMemoryDatabase`.

**Rationale:** Silent fallback to in-memory in production would hide farmer data —
the bot would appear to work but lose all session state between invocations. This
is worse than a visible error.

**Impact:** If Neon is unreachable and all retries fail, farmers see:
*"⏳ Service is waking up — please try again in a minute."*

---

## 5. No Real-Time Nearby Search Streaming

**What:** `list_machines_nearby()` fetches all bounding-box candidates and filters
in Python. For very large CHC registries (>10,000 machines), this could be slow.

**Mitigation:** Current dataset is ~12 verified CHCs and ~10 buyers. A GiST index
on `(lat, lon)` with PostGIS `ST_DWithin` would be the upgrade path at scale, but
is not needed today.

---

## 6. `prune_expired()` Is Not Automatic

**What:** Postgres has no native row TTL (unlike DynamoDB). `prune_expired()` must
be called explicitly.

**Mitigation:** The EventBridge-scheduled Lambda calls `db.prune_expired()` on its
regular run (same Lambda that ingests FIRMS fire data). If the scheduler Lambda is
not deployed, expired rows accumulate but do not affect correctness — all reads
filter on `expires_at > now()`.

---

## 7. `chat_id` Type Boundary

**What:** Telegram chat IDs are sent as JSON integers (64-bit). PostgreSQL `bigint`
could store them natively, but we store them as `text` to:
- Avoid JSON serialization/deserialization edge cases.
- Match the webhook payload format exactly.
- Support future use of string identifiers for group chats.

**Impact:** All queries use `chat_id = %s` with `str(chat_id)` from Python.
Python models keep `chat_id: int`; the conversion happens at the DB boundary in
`PostgresClient`.
