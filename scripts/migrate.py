"""Apply pending SQL migrations to the Parali Mitra PostgreSQL database.

Usage:
    python scripts/migrate.py

Reads DATABASE_URL_DIRECT from .env (non-pooled Neon URL).
Safe to re-run: already-applied migrations are skipped.
Each migration runs in a single transaction; if it fails, the transaction
is rolled back and the script exits non-zero.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from any working directory
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os
from dotenv import load_dotenv

load_dotenv()


MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "db" / "migrations"


def _get_direct_dsn() -> str:
    dsn = os.getenv("DATABASE_URL_DIRECT", "").strip()
    if not dsn:
        print(
            "\n❌  DATABASE_URL_DIRECT is not set.\n"
            "    This must be the non-pooled Neon connection string (for DDL).\n"
            "    Set it in your .env file.\n"
        )
        sys.exit(1)
    return dsn


def run_migrations() -> None:
    try:
        import psycopg
    except ImportError:
        print("❌  psycopg[binary] is not installed. Run: pip install psycopg[binary]")
        sys.exit(1)

    dsn = _get_direct_dsn()

    print("=== Parali Mitra — Database Migrations ===")
    print(f"Migrations directory: {MIGRATIONS_DIR}\n")

    # Never print the DSN
    with psycopg.connect(dsn, sslmode="require", connect_timeout=15, autocommit=True) as conn:
        # Ensure tracking table exists
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    text        PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )

        applied: set[str] = {
            row[0]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }

        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        if not migration_files:
            print("No migration files found in", MIGRATIONS_DIR)
            return

        pending = [f for f in migration_files if f.stem not in applied]

        if not pending:
            print("✅  All migrations already applied. Nothing to do.")
            return

        for mf in pending:
            print(f"  Applying {mf.name} ...", end=" ", flush=True)
            sql = mf.read_text(encoding="utf-8")
            try:
                # Run each file in its own explicit transaction (file already has BEGIN/COMMIT)
                conn.execute(sql)
                conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)", (mf.stem,)
                )
                print("✅")
            except Exception as exc:
                print(f"\n❌  Failed: {exc}")
                sys.exit(1)

    print("\n✅  All migrations applied successfully.")


if __name__ == "__main__":
    run_migrations()
