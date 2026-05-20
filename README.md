# AI Business Finder

Internal lead-generation tool for finding small businesses with missing, broken, or weak websites.

## Prerequisites

- Python 3.12+
- `uv`
- Google Cloud project with Places API enabled
- Google Maps API key with Places API access

## Setup

```bash
uv sync
cp .env.example .env
```

Edit `.env` and set:

```env
GOOGLE_MAPS_API_KEY=your-google-places-key
```

By default the app uses local SQLite at `./business_finder.db`.

To use Turso from the start instead, create/get your Turso database credentials:

```bash
turso db create ai-business-finder
turso db show --url ai-business-finder
turso db tokens create ai-business-finder
```

Then set these in `.env`:

```env
TURSO_DATABASE_URL=libsql://your-database.turso.io
TURSO_AUTH_TOKEN=your-turso-token
```

Finally create/update the tables:

```bash
uv run bf init
```

## Run the dashboard

```bash
uv run bf serve
```

Open:

- Health check: <http://127.0.0.1:8000/health>
- Admin dashboard: <http://127.0.0.1:8000/admin>

## Run a scan

```bash
uv run bf scan plumbers Plymouth
```

More examples:

```bash
uv run bf scan "beauty salons" Plymouth --pages 2
uv run bf scan roofers Exeter --country gb --pages 1
```

The scan command prints the query, API page count, stored result count, high-priority count, and dashboard URL.

## Recheck websites

Recheck websites for an existing scan without making another Google Places API call:

```bash
uv run bf check 1
```

## Enrich emails from websites

Google Places does not return business email addresses. After scanning, run:

```bash
#Find emails on live websites for high-priority leads
uv run bf enrich-emails --priority high

# Limit to 5 leads for testing
uv run bf enrich-emails --priority high --limit 5

# Overwrite existing emails (default: skip)
uv run bf enrich-emails --priority high --overwrite

# Include non-live websites
uv run bf enrich-emails --scan 1 --include-non-live
```

The enrichment crawls up to 4 pages per website (homepage + contact/about pages) and
saves the best business email found with a provenance label (`email_source`).

## Export leads

Export directly from the CLI in AI Agency Pipeline-compatible format:

```bash
uv run bf export leads.csv --priority high
```

Then upload `leads.csv` in AI Agency Pipeline at:

<http://localhost:3000/dashboard/leads>

You can also export a single scan:

```bash
uv run bf export leads-scan-1.csv --scan 1
```

Or export from the running web server:

```bash
curl "http://127.0.0.1:8000/exports/leads.csv?priority=high" -o leads.csv
curl "http://127.0.0.1:8000/exports/leads.csv?scan_id=1" -o leads-scan-1.csv
```

## Old verbose commands still work

```bash
uv run business-finder scan "plumbers" "Plymouth" --country gb --max-pages 1
uv run python -m business_finder check-websites --scan-id 1
uv run uvicorn business_finder.app:app --reload
uv run alembic upgrade head
```

## Testing

```bash
uv run pytest
```

## Cost warning

Google Places billing depends on requested fields and number of calls. This project uses an explicit field mask and defaults scans to `--pages 1`. Keep `--pages` low until you are happy with the workflow.

## Security notes

- Never commit `.env` or API keys.
- Run locally on `127.0.0.1` for Phase 1.
- Add SQLAdmin authentication before exposing the app on any network.
- Google Places does not return email addresses; fill them manually or with a later enrichment step.
