"""reset_dev.py — Drop and recreate the entire schema for development.

SAFETY GUARD: Refuses to run unless DB_ENV=dev is explicitly set.
This prevents accidental data wipe in staging or production.

Usage:
    DB_ENV=dev python scripts/reset_dev.py

What it does:
  1. Drops all Parali Mitra tables (CASCADE)
  2. Re-applies all migrations via scripts/migrate.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os
from dotenv import load_dotenv

load_dotenv()

# ── Safety guard ──────────────────────────────────────────────────────────────
DB_ENV = os.getenv("DB_ENV", "prod").strip().lower()
if DB_ENV not in ("dev", "test"):
    print(
        "\n🚫  reset_dev.py REFUSED to run.\n"
        "    DB_ENV must be 'dev' or 'test' to allow a schema reset.\n"
        "    Current DB_ENV =", repr(DB_ENV),
        "\n\n    Set DB_ENV=dev in your .env if this is intentional.\n"
    )
    sys.exit(1)

TABLES = [
    "bookings",
    "chat_messages",
    "chat_state",
    "hotspots",
    "processed_updates",
    "geocode_cache",
    "machines",
    "buyers",
    "providers",
    "farmers",
    "schema_migrations",
]


def main() -> None:
    try:
        import psycopg
    except ImportError:
        print("❌  psycopg[binary] is not installed. Run: pip install psycopg[binary]")
        sys.exit(1)

    dsn = os.getenv("DATABASE_URL_DIRECT", "").strip()
    if not dsn:
        print("❌  DATABASE_URL_DIRECT is not set.")
        sys.exit(1)

    print("=== Parali Mitra — Dev Schema Reset ===")
    print(f"DB_ENV={DB_ENV!r}  →  Proceeding.\n")

    with psycopg.connect(dsn, sslmode="require", connect_timeout=15, autocommit=True) as conn:
        print("Dropping all tables...")
        for table in TABLES:
            try:
                conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")  # noqa: S608
                print(f"  ✅  Dropped {table}")
            except Exception as exc:
                print(f"  ⚠️   Could not drop {table}: {exc}")

        # Also drop the prune_expired function
        conn.execute("DROP FUNCTION IF EXISTS prune_expired() CASCADE")
        print("  ✅  Dropped prune_expired() function")

    print("\nRe-applying migrations...\n")

    # Delegate to migrate.py
    import importlib.util
    migrate_path = Path(__file__).resolve().parent / "migrate.py"
    spec = importlib.util.spec_from_file_location("migrate", migrate_path)
    migrate_mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(migrate_mod)  # type: ignore[union-attr]
    migrate_mod.run_migrations()

    print("\n✅  Dev schema reset complete.")


if __name__ == "__main__":
    main()
