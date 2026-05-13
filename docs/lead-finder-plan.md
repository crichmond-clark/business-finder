# Business Lead Finder — Plan

## Table of Contents

- [1. Problem Statement](#1-problem-statement)
- [2. Goals &amp; Non-Goals](#2-goals-non-goals)
- [3. Proposed Architecture](#3-proposed-architecture)
- [4. Component Breakdown](#4-component-breakdown)
- [5. Data Flow](#5-data-flow)
- [6. Interface Contracts](#6-interface-contracts)
- [7. File Changes](#7-file-changes)
- [8. Implementation Phases](#8-implementation-phases)
- [9. Testing Strategy](#9-testing-strategy)
- [10. Security &amp; Compliance Implications](#10-security-compliance-implications)
- [11. Risks &amp; Tradeoffs](#11-risks-tradeoffs)
- [12. Planning Decisions](#12-planning-decisions)

## 1. Problem Statement

I build websites for small businesses. Finding businesses that need a website is currently manual: search Google Maps, click each listing, check whether they have a website, verify whether that website works, then decide if they are worth contacting.

This tool automates the first pass: search businesses by category and location, classify their web presence, score the quality of each lead, and present a browsable list I can work through.

Phase 1 is an internal lead-generation tool. A SaaS for other freelancers/agencies is explicitly out of scope until the workflow proves it can win clients.

## 2. Goals &amp; Non-Goals

**Goals:**

- Search for businesses by query/category + location using the official Google Places API.
- Classify businesses as `no_site`, `social_only`, `third_party_platform`, `broken`, `live`, or `unknown`.
- Score leads by practical signals: no/weak website, review count, rating, phone availability, operational status, and profile completeness.
- Provide a browsable, searchable dashboard through SQLAdmin — no custom frontend for Phase 1.
- Provide a CLI command to run scans, e.g. `python -m business_finder scan "plumbers" --city "Plymouth"`.
- Store scan history, lead notes, outreach status, and prospect email addresses locally.
- Keep API usage explicit and visible so costs do not creep up silently.

**Non-Goals for Phase 1:**

- Custom React/Next.js frontend.
- Multi-user SaaS features.
- Email automation.
- Auto-generated landing pages.
- Google Maps scraping.
- Bulk nationwide scraping.
- Automated cold outreach.

## 3. Proposed Architecture

```
┌──────────────┐     ┌─────────────────────┐     ┌────────────────────┐
│ CLI (Typer)  │────▶│ Scanner Service     │────▶│ Google Places API  │
│ scan command │     │ Text Search default │     │ searchText         │
└──────────────┘     └──────────┬──────────┘     └────────────────────┘
                                │
                      ┌─────────▼─────────┐
                      │ Website Checker   │
                      │ httpx + redirects │
                      └─────────┬─────────┘
                                │
                      ┌─────────▼─────────┐
                      │ Lead Scorer       │
                      │ weak-site signals │
                      └─────────┬─────────┘
                                │
                      ┌─────────▼─────────┐
                      │ Turso/libSQL +    │
                      │ SQLAlchemy        │
                      └─────────┬─────────┘
                                │
                      ┌─────────▼─────────┐
                      │ SQLAdmin          │
                      │ /admin dashboard  │
                      └───────────────────┘
```

**Key decisions:**

- **FastAPI + SQLAdmin** for a lightweight backend and admin dashboard.
- **No separate frontend for Phase 1.** SQLAdmin is enough for listing, filtering, sorting, editing notes, and exporting leads.
- **Google Places Text Search (New) as the default scanner**, not Nearby Search. Text Search supports natural queries like `"plumbers in Plymouth"` and returns up to 60 results across pages. Nearby Search (New) only returns up to 20 results and has no pagination, so it should be reserved for later grid-based scanning.
- **Turso/libSQL first.** Use Turso for Phase 1 instead of plain SQLite, while keeping the schema SQLite-compatible and lightweight.
- **Local-first setup.** The app should be easy to run locally with `uv`, Python 3.12, and simple Turso environment variables.
- **Alembic migrations.** Even with a lightweight database, schema changes will happen quickly; migrations are worth adding from day one.
- **Explicit field masks.** Google Places billing depends on requested fields. We request only fields we actually use.

## 4. Component Breakdown

### 4.1 Scanner (`business_finder/scanner.py`)

Responsibilities:

- Build a Places Text Search query from `category + city`, e.g. `"plumbers in Plymouth"`.
- Optionally apply `includedType` when a valid Google place type is known.
- Optionally include pure service-area businesses for trades like plumbers, electricians, roofers, etc.
- Paginate Text Search results up to the API maximum, defaulting to a conservative `--max-pages 1` for cost control.
- Deduplicate by Google `place_id`.
- Persist a `Scan` row and related `Lead` rows.

Important notes:

- Google Places category filters require official place types. User-friendly terms like `"plumbers"` need mapping to valid API types or should be handled as text queries.
- Google Places does **not** provide business email addresses. `Lead.email` should be left empty from Places results and filled manually or by a later website/contact-page enrichment step.

### 4.2 Website Checker (`business_finder/checker.py`)

Responsibilities:

- If Google returns no `websiteUri`, classify as `no_site`.
- If `websiteUri` exists, make an HTTP request with redirects enabled.
- Classify final URL:
  - `social_only`: Facebook, Instagram, TikTok, Linktree, etc.
  - `third_party_platform`: Yelp, Tripadvisor, Fresha, Treatwell, Checkatrade, etc.
  - `broken`: timeout, DNS failure, SSL failure, 4xx/5xx, too many redirects.
  - `live`: reachable normal website.
  - `unknown`: checker could not decide safely.
- Store HTTP status, final URL, redirect chain, and last checked time.

### 4.3 Lead Scorer (`business_finder/scorer.py`)

Phase 1 scoring should avoid expensive review-detail fields. Use cheap/practical signals:

- Website status:
  - `no_site`: highest opportunity
  - `social_only` / `third_party_platform`: strong opportunity
  - `broken`: strong opportunity
  - `live`: low opportunity unless later audit flags are added
- Business status:
  - closed permanently: exclude or very low score
  - operational: eligible
- Rating and user rating count:
  - active businesses with review volume are better prospects
- Phone present:
  - useful for outreach
- Address/profile completeness:
  - useful confidence signal

Review recency is **not** Phase 1 because requesting full `reviews` moves the call into a more expensive Places SKU. It can be added later as an optional enrichment mode.

### 4.4 Models (`business_finder/models.py`)

```python
class Scan:
    id: int
    query: str                 # "plumbers in Plymouth"
    category: str | None       # "plumbers"
    included_type: str | None  # Google place type if mapped
    city: str
    country_code: str | None
    max_pages: int
    results_count: int
    high_priority_count: int
    created_at: datetime

class Lead:
    id: int
    scan_id: FK[Scan]
    place_id: str
    name: str
    address: str | None
    phone: str | None
    email: str | None             # manual/enriched; not returned by Google Places
    email_source: str | None      # manual|website|contact_page|unknown
    google_maps_uri: str | None
    website_url: str | None
    website_final_url: str | None
    website_status: str        # no_site|social_only|third_party_platform|broken|live|unknown
    http_status_code: int | None
    rating: float | None
    review_count: int | None
    business_status: str | None
    primary_type: str | None
    types: list[str]
    score: int                 # 0–100
    priority: str              # high|medium|low|skip
    outreach_status: str       # not_contacted|contacted|replied|not_interested|converted
    notes: str | None
    raw_data: JSON             # useful during prototype; review before production/SaaS
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime
```

Recommended constraints:

- Unique index on `(scan_id, place_id)`.
- Optional later unique index on `place_id` if we decide one lead should be canonical across scans.

### 4.5 SQLAdmin Dashboard (`business_finder/admin.py`)

`LeadAdmin` should provide:

- Columns: name, city, website_status, priority, score, rating, review_count, phone, email, outreach_status.
- Filters: website_status, priority, outreach_status, business_status, scan.
- Search: name, address, phone, email.
- Default sort: priority/score descending.
- Editable fields: email, email_source, notes, outreach_status.
- Export: CSV if SQLAdmin export is available; otherwise implement a simple `/exports/leads.csv` endpoint.

`ScanAdmin` should provide:

- List scan history.
- Show query, city, result counts, created time.
- Detail view with related leads.

### 4.6 CLI (`business_finder/cli.py`)

Use Typer:

```bash
python -m business_finder scan "plumbers" --city "Plymouth" --country gb
python -m business_finder scan "beauty salons" --city "Plymouth" --max-pages 2
python -m business_finder check-websites --scan-id 1
```

CLI should print:

- Query being run.
- Estimated/actual API calls.
- Number of results found.
- Counts by website status and priority.
- Link to dashboard.

## 5. Data Flow

```
1. User runs:
   python -m business_finder scan "plumbers" --city "Plymouth" --country gb

2. Scanner builds text query:
   "plumbers in Plymouth"

3. Places Text Search request runs with an explicit field mask:
   places.id,
   places.displayName,
   places.formattedAddress,
   places.googleMapsUri,
   places.websiteUri,
   places.nationalPhoneNumber,
   places.rating,
   places.userRatingCount,
   places.businessStatus,
   places.primaryType,
   places.types,
   nextPageToken

4. Results are persisted as Lead rows.

5. Website checker runs concurrently for leads with website URLs.

6. Lead scorer calculates score + priority.

7. Scan summary is updated.

8. User opens:
   http://127.0.0.1:8000/admin
```

## 6. Interface Contracts

### 6.1 CLI: Scan

```bash
python -m business_finder scan CATEGORY --city CITY [--country COUNTRY] [--max-pages N] [--included-type TYPE]
```

Initial target defaults:

- Area: Plymouth, UK.
- Categories: trades and local service businesses first — plumbers, electricians, roofers, landscapers/gardeners, cleaners, builders/handymen, barbers, beauty salons, cafes, and independent restaurants.

Inputs:

- `CATEGORY`: free-text business type, e.g. `plumbers`, `electricians`, `roofers`, `cleaners`, `cafes`, `hair salons`.
- `--city`: city/town/area.
- `--country`: optional country/region hint, e.g. `gb`.
- `--max-pages`: default `1`, max `3` for Text Search.
- `--included-type`: optional official Google place type.

Output:

- Creates one `Scan` row.
- Creates/updates many `Lead` rows.
- Prints summary.

### 6.2 Scanner Service

```python
async def scan_businesses(
    category: str,
    city: str,
    country_code: str | None = None,
    included_type: str | None = None,
    max_pages: int = 1,
) -> ScanSummary:
    """Run a Places Text Search scan and persist results."""
```

### 6.3 Website Checker

```python
async def check_website(url: str) -> WebsiteCheckResult:
    """Return website status, final URL, HTTP status, and redirect chain."""
```

### 6.4 Lead Scorer

```python
def score_lead(lead_data: LeadInput) -> LeadScore:
    """Return score 0–100 and priority bucket."""
```

### 6.5 FastAPI Routes

Phase 1 only needs health/export helpers:

```http
GET /health
GET /exports/leads.csv?scan_id=1&priority=high
```

SQLAdmin handles CRUD at `/admin`.

## 7. File Changes

All files are new:

```text
business_finder/
├── __init__.py
├── __main__.py
├── admin.py
├── app.py
├── checker.py
├── cli.py
├── config.py
├── database.py
├── exports.py
├── models.py
├── scanner.py
├── scorer.py
└── services/
    └── places.py
alembic/
├── env.py
└── versions/
.env.example
.gitignore
pyproject.toml
README.md
docs/lead-finder-plan.md
```

## 8. Implementation Phases

Use one branch: `feature/lead-finder`.

These phases are intentionally implementation-oriented because the next reader may be an AI coding agent. Each phase should leave the project runnable and should avoid building later-phase behaviour early.

### Phase 1 — Project scaffold, models, migrations, admin

Goal: create a runnable FastAPI + SQLAdmin app with database models before touching external APIs.

Implementation steps:

1. Create the Python project scaffold:
   - `pyproject.toml` with Python `>=3.12`.
   - Dependencies: `fastapi`, `uvicorn`, `sqlalchemy`, `alembic`, `sqladmin`, `typer`, `pydantic-settings`, `python-dotenv`, `httpx`, `aiosqlite` or the chosen libSQL/Turso driver, `pytest`, `pytest-asyncio`.
   - Package directory: `business_finder/` with `__init__.py` and `__main__.py`.
2. Add configuration in `business_finder/config.py`:
   - Load `DATABASE_URL`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `GOOGLE_MAPS_API_KEY`.
   - Default local database URL should work without secrets, e.g. SQLite/libSQL local file.
   - Do not require a Google key until the scan command runs.
3. Add database setup in `business_finder/database.py`:
   - SQLAlchemy engine/session factory.
   - Declarative base.
   - Helper dependency for FastAPI routes/admin.
4. Add models in `business_finder/models.py`:
   - `Scan` and `Lead` matching section 4.4.
   - Use enums or constrained string constants for `website_status`, `priority`, and `outreach_status`.
   - Store `types`, `raw_data`, and redirect-chain style fields as JSON-compatible columns.
   - Add unique constraint on `(scan_id, place_id)`.
5. Add Alembic:
   - `alembic/env.py` wired to model metadata.
   - Initial migration creating `scans` and `leads`.
   - Document the migration command in README later; for now ensure it runs.
6. Add FastAPI app in `business_finder/app.py`:
   - Create `app = FastAPI(...)`.
   - Add `GET /health` returning `{"status": "ok"}`.
   - Mount SQLAdmin at `/admin`.
7. Add SQLAdmin views in `business_finder/admin.py`:
   - `ScanAdmin` list/detail fields.
   - `LeadAdmin` columns, search, filters, editable fields, default sorting.

Suggested commits:

- [ ] Add FastAPI project scaffold and settings.
- [ ] Add SQLAlchemy models and Alembic migrations.
- [ ] Add SQLAdmin dashboard for Scan and Lead.

Validation commands:

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn business_finder.app:app --reload
```

Done when:

- `/health` returns `{"status": "ok"}`.
- `/admin` loads.
- Scan and Lead CRUD work locally.
- A new developer/agent can create the database from migrations only.

### Phase 2 — Places Text Search integration

Goal: run a real Google Places Text Search and persist raw lead rows without website checking or scoring complexity.

Implementation steps:

1. Add `business_finder/services/places.py`:
   - Define a `PlacesClient` using `httpx.AsyncClient`.
   - Use the Text Search (New) endpoint.
   - Send the API key via the required Google header.
   - Send the explicit field mask from section 5.
   - Support `pageToken` pagination up to `max_pages`.
   - Return typed/plain dict result objects; do not persist from the client directly.
2. Add category/type mapping support in `business_finder/scanner.py`:
   - Build query as `"{category} in {city}"`.
   - Accept `included_type` only when supplied or mapped confidently.
   - Keep free-text category as the default path.
3. Add scan orchestration in `business_finder/scanner.py`:
   - Create a `Scan` row at the start.
   - Call `PlacesClient.search_text(...)` for each page.
   - Upsert or insert `Lead` rows for each returned place.
   - Map Google fields to model fields exactly:
     - `id` -> `place_id`
     - `displayName.text` -> `name`
     - `formattedAddress` -> `address`
     - `nationalPhoneNumber` -> `phone`
     - `googleMapsUri` -> `google_maps_uri`
     - `websiteUri` -> `website_url`
     - `userRatingCount` -> `review_count`
   - Leave `email` empty.
   - Set initial `website_status="unknown"`, `score=0`, `priority="low"` until Phase 3.
   - Store original place payload in `raw_data`.
   - Update `Scan.results_count`.
4. Add CLI in `business_finder/cli.py` and `business_finder/__main__.py`:
   - Typer command: `scan CATEGORY --city CITY --country gb --max-pages 1 --included-type optional`.
   - Validate `max_pages` between `1` and `3`.
   - Print query, max pages, actual API calls/pages, results stored, dashboard URL.
5. Handle failures clearly:
   - Missing Google key should produce a friendly CLI error.
   - API errors should include status code and response message, but never print the API key.

Suggested commits:

- [ ] Add Google Places client with explicit field masks.
- [ ] Add scan CLI command.
- [ ] Persist scan results.

Validation commands:

```bash
uv run python -m business_finder scan "plumbers" --city "Plymouth" --country gb --max-pages 1
uv run uvicorn business_finder.app:app --reload
```

Done when:

- The scan command stores real leads from Google Places.
- CLI prints API call/page count and result count.
- SQLAdmin shows the imported leads with raw website URLs and Google Maps links.
- No website-checking or scoring side effects are required yet.

### Phase 3 — Website classification and scoring

Goal: turn raw Places leads into prioritised leads that can be filtered in SQLAdmin.

Implementation steps:

1. Add `business_finder/checker.py`:
   - Define `WebsiteCheckResult` with `status`, `final_url`, `http_status_code`, `redirect_chain`, `checked_at`, and optional `error`.
   - If URL is empty, return `no_site` without making a network request.
   - Use `httpx.AsyncClient(follow_redirects=True)` with short timeouts.
   - Limit concurrency in batch operations with an async semaphore.
2. Add classification rules:
   - Social domains -> `social_only`.
   - Marketplace/booking/review domains -> `third_party_platform`.
   - Timeout, DNS, SSL, too many redirects, 4xx/5xx -> `broken`.
   - Successful normal response -> `live`.
   - Anything ambiguous -> `unknown`.
3. Add `business_finder/scorer.py`:
   - Define a pure function `score_lead(input) -> LeadScore`.
   - Use only fields already stored on `Lead`.
   - Keep scoring deterministic and easy to test.
   - Suggested priority buckets:
     - `high`: score `70+`
     - `medium`: score `40-69`
     - `low`: score `1-39`
     - `skip`: permanently closed or invalid lead
4. Integrate checker/scorer with scans:
   - After storing Places results, check websites for leads in the scan.
   - Update `website_status`, `website_final_url`, `http_status_code`, `last_checked_at`, `score`, and `priority`.
   - Update `Scan.high_priority_count`.
5. Add CLI command:
   - `python -m business_finder check-websites --scan-id 1`
   - Useful for rerunning checks without another paid Places search.
6. Add tests before tuning weights:
   - Unit tests for social/third-party/broken/live/no-site classification.
   - Unit tests for score and priority boundaries.
   - Mock network calls; tests must not hit real websites.

Suggested commits:

- [ ] Add async website checker.
- [ ] Add website classification rules.
- [ ] Add lead scoring and priority buckets.
- [ ] Add checker/scorer tests.

Validation commands:

```bash
uv run pytest
uv run python -m business_finder check-websites --scan-id 1
```

Done when:

- Leads in SQLAdmin show website status, score, and priority.
- High-priority leads can be filtered in the dashboard.
- Rerunning website checks does not create duplicate leads or scans.
- Tests cover the main classification and scoring paths.

### Phase 4 — Export, polish, docs

Goal: make the prototype usable end-to-end for reviewing and exporting prospects.

Implementation steps:

1. Check SQLAdmin export support first:
   - If built-in CSV export is enough, enable/configure it.
   - If not, add `business_finder/exports.py` with `GET /exports/leads.csv`.
2. CSV export endpoint requirements:
   - Optional filters: `scan_id`, `priority`, `website_status`, `outreach_status`.
   - Include practical outreach columns: name, address, phone, email, website status, website URL/final URL, rating, review count, score, priority, notes, Google Maps URL.
   - Return `text/csv` with a sensible filename.
3. Add README:
   - Prerequisites: Python 3.12, `uv`, Google Cloud project with Places API enabled, Turso/libSQL setup if needed.
   - Setup commands.
   - Environment variables.
   - Migration commands.
   - Run server command.
   - Scan command examples.
   - Testing command.
   - Cost warning about Places field masks and `--max-pages`.
4. Add `.env.example`:
   - Include variable names only, never real secrets.
5. Add `.gitignore`:
   - Ignore `.env`, local DB files, caches, virtualenvs, coverage output.
6. Final manual smoke test:
   - Run migrations from scratch.
   - Start the app.
   - Run one `--max-pages 1` scan.
   - Open `/admin` and filter high-priority leads.
   - Export CSV.

Suggested commits:

- [ ] Add CSV export endpoint if SQLAdmin export is insufficient.
- [ ] Add README setup instructions and environment example.
- [ ] Add final smoke-test notes.

Validation commands:

```bash
uv run pytest
uv run alembic upgrade head
uv run python -m business_finder scan "plumbers" --city "Plymouth" --country gb --max-pages 1
curl "http://127.0.0.1:8000/exports/leads.csv?priority=high"
```

Done when:

- A full scan can be run from CLI.
- Results can be reviewed in `/admin`.
- High-priority leads can be exported to CSV.
- README contains enough setup detail for another agent/developer to start from a clean checkout.

## 9. Testing Strategy

- Unit tests:
  - website classification rules
  - scoring rules
  - category/type mapping
- Integration tests:
  - mocked Places API responses
  - database persistence
  - CSV export
- Manual validation:
  - one real scan with `--max-pages 1`
  - inspect 10–20 leads manually in Google Maps
- Edge cases:
  - no website field
  - no email field from Places
  - manually entered email addresses
  - social-only URLs
  - third-party platform URLs
  - timeout/DNS/SSL failure
  - permanently closed businesses
  - duplicate place IDs across scans
  - non-ASCII business names

## 10. Security &amp; Compliance Implications

- Store `GOOGLE_MAPS_API_KEY`, `TURSO_DATABASE_URL`, and `TURSO_AUTH_TOKEN` in `.env`; never commit them.
- Bind local dev server to `127.0.0.1` by default.
- If this is deployed anywhere, add SQLAdmin authentication before exposure.
- Google Places data has platform terms around storage/display/caching. For Phase 1, keep this an internal prototype and avoid over-collecting. Before any SaaS/productisation, review Google Maps Platform terms and adjust storage/display rules.
- Business phone numbers, email addresses, and addresses are contact data. If doing outreach, comply with UK GDPR/PECR/CAP Code: legitimate interest assessment, relevance, no misleading claims, clear opt-out, and avoid mass spam.
- User inputs are used as API parameters only; still validate max pages and allowed included types.

## 11. Risks &amp; Tradeoffs

- **Risk:** Nearby Search was initially attractive but only returns up to 20 results and has no pagination.

  **Mitigation:** Use Text Search first; add grid-based Nearby scanning later if needed.
- **Risk:** Places fields needed for this product (`websiteUri`, phone, rating, review count) trigger higher billing tiers.

  **Mitigation:** Use explicit field masks, default to one page, print API call counts, and avoid full reviews in Phase 1.
- **Risk:** Google API results are capped at ~60 for Text Search.

  **Mitigation:** This is enough for first outreach campaigns. Later add multi-query scans or geographic grid scanning.
- **Risk:** Website checks can be slow.

  **Mitigation:** Use async concurrency with sensible timeouts and limits.
- **Risk:** SQLAdmin may not provide every CRM feature.

  **Mitigation:** Keep Phase 1 simple; add a custom FastAPI route or Next.js frontend only once the workflow proves valuable.
- **Risk:** Turso/libSQL support with SQLAlchemy/Alembic may need validation early.

  **Mitigation:** Confirm the Python driver and migration workflow during Phase 1 scaffold before building scanner logic on top.

## 12. Planning Decisions

Resolved decisions:

1. First target area: Plymouth, UK.
2. First categories: trades and local service businesses — plumbers, electricians, roofers, landscapers/gardeners, cleaners, builders/handymen, barbers, beauty salons, cafes, and independent restaurants.
3. Package manager: `uv`.
4. Python target: 3.12.
5. Database: Turso/libSQL for Phase 1.
6. Google Cloud project: not created yet; user can create one and enable Places API.
7. Product scope: local/internal tool first, not SaaS, but setup must be easy to run locally.

