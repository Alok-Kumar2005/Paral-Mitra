# Parali Mitra — Officer Residue Monitoring Dashboard

## 1. Overview
The **Officer Residue Monitoring Dashboard** is a read-only, high-contrast web interface served directly from the serverless AWS stack via API Gateway HTTP API and a lightweight AWS Lambda function (`ApiFunction`).

It empowers agricultural field officers, Custom Hiring Centre (CHC) operators, and district administration across Punjab and Haryana to:
- Monitor active paddy straw fire detections from NASA FIRMS VIIRS (375 m NRT).
- Identify spatial **machinery coverage gaps** (fire clusters with zero registered Crop Residue Management machinery within 15 km).
- Inspect available verified and directory-listed CRM machinery (Super Seeders, Balers, Happy Seeders, Mulchers).
- Track program impact: confirmed/completed bookings and estimated residue tonnage diverted from burning.

---

## 2. Architecture & Routes

```text
[ Browser / Phone / Laptop ]
            │
            ▼
┌───────────────────────────┐
│ API Gateway (HTTP API v2) │
└───────────┬───────────────┘
            │
            ▼
┌───────────────────────────┐
│ Lambda: parali-mitra-api  │  (512 MB, 20s, in-memory 5-min container cache)
└───────────┬───────────────┘
            ├── /dashboard     -> Returns single-page self-contained HTML (MapLibre GL JS)
            ├── /api/summary   -> Regional statistics, 7-day sparkline, top 5 underserved areas
            ├── /api/fires     -> Hotspots aggregated by 0.1-degree spatial grid cells
            ├── /api/gaps      -> Machinery coverage gaps via compute_gap() (15 km threshold)
            └── /api/machines  -> Sanitized public machinery listings (ZERO farmer/owner PII)
```

### Response Caching
- **HTTP Cache Header:** `Cache-Control: public, max-age=300` on all 200 OK responses.
- **Warm Container Cache:** Per-container 5-minute memory cache (`_CACHE`) avoids querying Postgres on repeated requests.

### Privacy & Data Protection (Zero PII)
- **No Farmer Data:** No farmer names, chat IDs, phone numbers, or farm coordinates are ever stored in the dashboard or returned by the API.
- **Machinery Sanitization:** Operator names, phone numbers, telegram chat IDs, and rental rates (`rate_per_acre`, `travel_charge_per_km`) are completely stripped. Only public attributes (`machine_type`, `village`, `district`, coordinates, directory vs. verified status) are exposed.
- **DASHBOARD_TOKEN Authorization:** Optional environment variable. When set, all routes require `?token=<secret>`. Validated via `hmac.compare_digest` to prevent timing attacks.

---

## 3. Data Limitations & Caveats

1. **Satellite Detections vs. Ground Truth:**
   - Thermal detections from NASA FIRMS VIIRS represent *thermal anomalies*, not confirmed ground fires. Industrial heat sources, brick kilns, or solar reflectance can occasionally trigger detections (mitigated by confidence filtering).
2. **Coverage Times & Orbits:**
   - Suomi-NPP and NOAA-20/21 satellites pass over Northwest India approximately twice daily: ~13:30 IST (daytime pass) and ~01:30 IST (nighttime pass). Fires ignited between satellite passes and extinguished quickly may not appear.
3. **Cloud & Smog Obscuration:**
   - Dense cloud cover or thick smog blankets can mask surface thermal radiation and prevent detection.
4. **Machinery Directory Listings:**
   - Machines designated as `Directory Listing` are sourced from public CHC portal registries without verified bot operator logins; machines designated as `Verified` are active marketplace participants.

---

## 4. Local Inspection & Testing

### Running the Snapshot Script
To inspect current API responses from the terminal:
```bash
# Direct local database inspection:
python scripts/dashboard_snapshot.py --days 7

# Inspect against a deployed cloud stack:
python scripts/dashboard_snapshot.py --url https://<api-id>.execute-api.ap-south-1.amazonaws.com --token <secret>
```

### Ingesting Real Active Fires
If the database has 0 recent fire detections, ingest the latest NASA FIRMS satellite data:
```bash
python -m src.connectors.ingest_fires --days 3
```

---

## 5. Deployment Guide

### Files to Package & Deploy
The dashboard is bundled into the single pre-built deployment package:
- `src/dashboard/index.html` (Front end)
- `src/handlers/api.py` (Backend handler)
- `infra/template.yaml` (CloudFormation template with `ApiFunction`, `ApiRole`, routes, and outputs)

### Deployment Steps
1. **Build the arm64 Lambda package:**
   ```bash
   python scripts/build_lambda.py
   ```
2. **Deploy with AWS SAM:**
   ```bash
   sam deploy \
       --template-file infra/template.yaml \
       --stack-name parali-mitra \
       --region ap-south-1 \
       --capabilities CAPABILITY_IAM \
       --parameter-overrides \
           DashboardToken="<optional-secret-token>"
   ```
3. **Retrieve Dashboard URL:**
   The stack output `DashboardUrl` provides the live link:
   ```text
   https://<api-id>.execute-api.ap-south-1.amazonaws.com/dashboard
   ```
