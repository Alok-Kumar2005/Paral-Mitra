"""db_check.py — Connectivity and health check for the Parali Mitra Neon database.

Prints:
  - Server version
  - All tables with row counts
  - Round-trip latency of a trivial query (useful for cold vs warm Neon comparison)

Usage:
    python scripts/db_check.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os
from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    try:
        import psycopg
    except ImportError:
        print("❌  psycopg[binary] is not installed. Run: pip install psycopg[binary]")
        sys.exit(1)

    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        print("❌  DATABASE_URL is not set.")
        sys.exit(1)

    print("=== Parali Mitra — Database Health Check ===\n")

    t0 = time.perf_counter()
    try:
        conn = psycopg.connect(dsn, sslmode="require", connect_timeout=15)
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"❌  Connection failed after {elapsed:.0f} ms: {exc}")
        sys.exit(1)

    connect_ms = (time.perf_counter() - t0) * 1000
    print(f"✅  Connected in {connect_ms:.0f} ms\n")

    # Server version
    ver = conn.execute("SELECT version()").fetchone()[0]
    print(f"Server version:\n  {ver}\n")

    # Round-trip latency
    t1 = time.perf_counter()
    conn.execute("SELECT 1")
    rtt_ms = (time.perf_counter() - t1) * 1000
    print(f"Round-trip latency (SELECT 1):  {rtt_ms:.1f} ms")
    if connect_ms > 1500:
        print("  ℹ️  High connect time suggests Neon was scale-to-zero (cold start).")
    print()

    # Tables and row counts
    tables = conn.execute(
        """
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
        ORDER BY tablename
        """
    ).fetchall()

    if not tables:
        print("⚠️   No tables found in public schema. Run scripts/migrate.py first.")
        conn.close()
        return

    print(f"{'Table':<30} {'Rows':>8}")
    print("-" * 40)
    for (tbl,) in tables:
        try:
            count = conn.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]  # noqa: S608
        except Exception:
            count = "ERROR"
        print(f"  {tbl:<28} {count:>8}")

    conn.close()
    print("\n✅  Health check complete.")


if __name__ == "__main__":
    main()
