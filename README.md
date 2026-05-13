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
uv run alembic upgrade head
```

Edit `.env` and set:

```env
GOOGLE_MAPS_API_KEY=your-key-here
```

The default database is local SQLite at `./business_finder.db`. Turso/libSQL variables are present for later deployment, but local development works without them.

## Run the dashboard

```bash
uv run uvicorn business_finder.app:app --reload
```

Open:

- Health check: <http://127.0.0.1:8000/health>
- Admin dashboard: <http://127.0.0.1:8000/admin>

## Run a scan

```bash
uv run python -m business_finder scan "plumbers" --city "Plymouth" --country gb --max-pages 1
```

Other examples:

```bash
uv run python -m business_finder scan "beauty salons" --city "Plymouth" --max-pages 2
uv run python -m business_finder check-websites --scan-id 1
```

The scan command prints the query, API page count, stored result count, high-priority count, and dashboard URL.

## Export leads

```bash
curl "http://127.0.0.1:8000/exports/leads.csv?priority=high" -o leads.csv
curl "http://127.0.0.1:8000/exports/leads.csv?scan_id=1" -o leads-scan-1.csv
```

## Testing

```bash
uv run pytest
```

## Cost warning

Google Places billing depends on requested fields and number of calls. This project uses an explicit field mask and defaults scans to `--max-pages 1`. Keep `--max-pages` low until you are happy with the workflow.

## Security notes

- Never commit `.env` or API keys.
- Run locally on `127.0.0.1` for Phase 1.
- Add SQLAdmin authentication before exposing the app on any network.
- Google Places does not return email addresses; fill them manually or with a later enrichment step.
