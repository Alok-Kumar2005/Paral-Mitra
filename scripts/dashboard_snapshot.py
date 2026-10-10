#!/usr/bin/env python3
"""Snapshot inspection tool for the Parali Mitra Officer Dashboard API.

Fetches and formats responses from /api/summary, /api/fires, /api/gaps, and /api/machines.
Can inspect the active database directly (offline or connected to Neon) or query a deployed endpoint.

Usage:
  python scripts/dashboard_snapshot.py
  python scripts/dashboard_snapshot.py --days 7
  python scripts/dashboard_snapshot.py --url https://<api-id>.execute-api.ap-south-1.amazonaws.com --token <secret>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows console unicode compatibility
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add project root to sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from src.common.db import get_db
from src.handlers.api import (
    handle_api_fires,
    handle_api_gaps,
    handle_api_machines,
    handle_api_summary,
)


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Print an ASCII table."""
    col_widths = [len(h) for h in headers]
    for row in rows:
        for idx, val in enumerate(row):
            col_widths[idx] = max(col_widths[idx], len(str(val)))

    sep = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"
    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"

    lines = [sep, header_line, sep]
    for row in rows:
        lines.append("| " + " | ".join(str(val).ljust(col_widths[i]) for i, val in enumerate(row)) + " |")
    lines.append(sep)
    return "\n".join(lines)


def fetch_via_http(base_url: str, token: str, days: int) -> dict[str, dict]:
    import httpx
    client = httpx.Client(timeout=15.0)
    results = {}
    endpoints = ["summary", "fires", "gaps", "machines"]

    for ep in endpoints:
        query_parts = []
        if ep in ("summary", "fires", "gaps"):
            query_parts.append(f"days={days}")
        if token:
            query_parts.append(f"token={token}")
        query_str = f"?{'&'.join(query_parts)}" if query_parts else ""

        url = f"{base_url.rstrip('/')}/api/{ep}{query_str}"
        print(f"GET {url} ...")
        resp = client.get(url)
        if resp.status_code != 200:
            print(f"  [ERROR] {resp.status_code}: {resp.text}", file=sys.stderr)
            results[ep] = {"error": resp.text, "status": resp.status_code}
        else:
            results[ep] = resp.json()
    return results


def fetch_via_handler(days: int) -> dict[str, dict]:
    db = get_db()
    query_event = {"queryStringParameters": {"days": str(days)}}

    summary_res = json.loads(handle_api_summary(query_event, db=db)["body"])
    fires_res = json.loads(handle_api_fires(query_event, db=db)["body"])
    gaps_res = json.loads(handle_api_gaps(query_event, db=db)["body"])
    machines_res = json.loads(handle_api_machines({}, db=db)["body"])

    return {
        "summary": summary_res,
        "fires": fires_res,
        "gaps": gaps_res,
        "machines": machines_res,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Parali Mitra Dashboard Snapshot Tool")
    parser.add_argument("--url", default="", help="Base URL of deployed API Gateway (optional)")
    parser.add_argument("--token", default=os.environ.get("DASHBOARD_TOKEN", ""), help="DASHBOARD_TOKEN for authorization")
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days (default: 7)")
    args = parser.parse_args()

    print("=" * 70)
    print("🌾 Parali Mitra — Officer Dashboard Snapshot")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print(f"Window: {args.days} days")
    print("=" * 70)

    if args.url:
        data = fetch_via_http(args.url, args.token, args.days)
    else:
        print("[i] Reading directly from database backend (DB_MODE=%s)" % os.environ.get("DB_MODE", "local"))
        data = fetch_via_handler(args.days)

    summary = data.get("summary", {})
    fires = data.get("fires", {})
    gaps = data.get("gaps", {})
    machines = data.get("machines", {})

    # 1. Summary Block
    print("\n[1] SUMMARY METRICS")
    print(f"  • Active Hotspots (last {args.days}d):   {summary.get('total_hotspots', 0)}")
    print(f"  • Coverage Gaps (flagged >15km): {summary.get('flagged_cells', 0)}")
    print(f"  • Verified CRM Machines:         {summary.get('verified_machines', 0)}")
    print(f"  • Commercial Off-takers:         {summary.get('verified_buyers', 0)}")
    bookings = summary.get("bookings", {})
    print(f"  • Bookings Confirmed / Done:     {bookings.get('confirmed', 0)} confirmed / {bookings.get('completed', 0)} completed")
    print(f"  • Residue Managed (Estimated):   {summary.get('estimated_residue_tonnes_handled', 0)} tonnes ({summary.get('tonnes_per_acre_rate', 2.8)} t/acre)")

    daily = summary.get("daily_counts", [])
    if daily:
        trend = " -> ".join(f"{d['date'][-5:]}:{d['count']}" for d in daily)
        print(f"  • 7-Day Trend:                   {trend}")

    # 2. Underserved Areas
    top_areas = summary.get("top_underserved_areas", [])
    print(f"\n[2] TOP UNDERSERVED AREAS ({len(top_areas)} clusters)")
    if top_areas:
        rows = []
        for a in top_areas:
            dist = f"{a.get('nearest_machine_distance_km')} km" if a.get("nearest_machine_distance_km") is not None else "None"
            rows.append([
                a.get("grid_cell", ""),
                f"{a.get('lat')}, {a.get('lon')}",
                str(a.get("fire_count", 0)),
                dist,
                a.get("nearest_machine_district") or "N/A",
                "YES" if a.get("is_gap") else "No",
            ])
        print(_format_table(["Grid Cell", "Centroid (Lat,Lon)", "Fires", "Nearest CRM", "District", "Flagged Gap"], rows))
    else:
        print("  (No underserved areas flagged)")

    # 3. Fire Clusters Preview
    fire_cells = fires.get("cells", [])
    print(f"\n[3] RECENT FIRE CLUSTERS ({len(fire_cells)} active 0.1-deg cells)")
    if fire_cells:
        sample = fire_cells[:8]
        rows = [
            [c.get("grid_cell", ""), f"{c.get('lat')}, {c.get('lon')}", str(c.get("fire_count", 0)), f"{c.get('max_frp', 0)} MW", f"{c.get('total_frp', 0)} MW"]
            for c in sample
        ]
        print(_format_table(["Grid Cell", "Centroid", "Detections", "Max FRP", "Total FRP"], rows))
        if len(fire_cells) > 8:
            print(f"  ... and {len(fire_cells) - 8} more cells")
    else:
        print("  ⚠️  0 active fire hotspots found in this window.")
        print("  TIP: If you want to ingest NASA FIRMS data, run:")
        print("       python -m src.connectors.ingest_fires --days 3")

    # 4. Machinery Preview
    mach_list = machines.get("machines", [])
    print(f"\n[4] REGISTERED PUBLIC MACHINERY ({len(mach_list)} available units)")
    if mach_list:
        sample_m = mach_list[:8]
        rows = [
            [m.get("machine_id", ""), m.get("machine_type", ""), m.get("village", ""), m.get("district", ""), "Directory" if m.get("is_directory_listing") else "Verified"]
            for m in sample_m
        ]
        print(_format_table(["Machine ID", "Type", "Village", "District", "Source"], rows))
        if len(mach_list) > 8:
            print(f"  ... and {len(mach_list) - 8} more machines")

    print("\n" + "=" * 70)
    print("Snapshot completed successfully.")
    print("=" * 70)


if __name__ == "__main__":
    main()
