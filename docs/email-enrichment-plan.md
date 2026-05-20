# Website Email Enrichment Plan

## Table of Contents

- [1. Problem Statement](#1-problem-statement)
- [2. Goals & Non-Goals](#2-goals-non-goals)
- [3. Proposed Architecture](#3-proposed-architecture)
- [4. Component Breakdown](#4-component-breakdown)
- [5. Data Flow](#5-data-flow)
- [6. Interface Contracts](#6-interface-contracts)
- [7. File Changes](#7-file-changes)
- [8. Implementation Phases](#8-implementation-phases)
- [9. Testing Strategy](#9-testing-strategy)
- [10. Security Implications](#10-security-implications)
- [11. Risks & Tradeoffs](#11-risks-tradeoffs)
- [12. Open Questions](#12-open-questions)

## 1. Problem Statement

Google Places does not return business email addresses. `Lead.email` currently stays empty unless edited manually, which means exported CSVs for AI Agency Pipeline are less useful and may trigger downstream validation/import issues when an email is expected.

Most useful local-business emails are publicly listed on the business website, usually on the homepage, footer, contact page, or about page. The project already checks website availability, so the smallest useful next step is to add a conservative website email enrichment pass that fills `Lead.email` and `Lead.email_source` from public website pages.

## 2. Goals & Non-Goals

Goals:

- Add a CLI command to enrich lead emails from public business websites.
- Only enrich leads with live business websites by default.
- Crawl a tiny, bounded set of pages per website: homepage plus likely contact/about pages.
- Extract emails from `mailto:` links and visible HTML text.
- Avoid storing obvious junk emails or false positives.
- Save one best email to `Lead.email` and a short provenance value to `Lead.email_source`.
- Preserve manually entered emails unless the user explicitly asks to overwrite.
- Keep CSV export unchanged, but make the existing `email` column populated when enrichment finds an email.
- Add tests for extraction, filtering, best-email selection, and database update behavior.

Non-Goals:

- No paid enrichment services yet: Hunter, Apollo, Snov, etc.
- No contact-person discovery or named employee emails.
- No automated outreach.
- No broad crawling or sitemap crawling.
- No JavaScript rendering/browser automation.
- No bypassing bot protection, login walls, CAPTCHAs, or anti-scraping controls.
- No guessing emails from names/domains.

## 3. Proposed Architecture

Add a new enrichment module that is intentionally separate from the existing website status checker:

```text
CLI command
  bf enrich-emails
       |
       v
scanner/enrichment service
  selects eligible Lead rows
       |
       v
email_enrichment module
  fetch homepage/contact/about pages with httpx
  extract + validate candidate emails
  choose best email
       |
       v
Lead.email / Lead.email_source updated
       |
       v
existing CSV export includes email
```

Key design decisions:

- Use `httpx`, already in the project, for network requests.
- Use the Python standard library for simple HTML link extraction; avoid adding BeautifulSoup unless tests show stdlib parsing is insufficient.
- Keep crawling bounded and predictable: max 4 pages per lead by default.
- Use `website_final_url` first when available, then `website_url`.
- Only follow same-domain links discovered from the homepage.
- Fetch likely pages in this order:
  1. Homepage.
  2. Same-site links whose text/path suggests contact or about.
  3. Common fallback paths: `/contact`, `/contact-us`, `/about`, `/about-us`.
- Prefer `mailto:` addresses over regex text matches.
- Prefer contact/about page emails over homepage emails.
- Prefer useful role inboxes (`info@`, `hello@`, `contact@`, `sales@`, `bookings@`, `enquiries@`, `office@`) over noisy addresses.
- Never overwrite existing `Lead.email` unless `--overwrite` is passed.

## 4. Component Breakdown

- `business_finder/email_enrichment.py`
  - Owns URL selection, page fetching, email extraction, candidate filtering, candidate ranking, and per-lead enrichment.
  - Contains pure functions for extraction/ranking so tests do not require network access.

- `business_finder/scanner.py`
  - Adds a service function to enrich a selected set of leads using the new module.
  - Keeps database selection/update behavior close to existing `check_websites_for_scan` patterns.

- `business_finder/cli.py`
  - Adds `bf enrich-emails` command with filters.
  - Prints totals: checked, found, skipped existing, skipped not-live, failed.

- `business_finder/admin.py`
  - Optionally adds `email_source` to list/detail columns if helpful.
  - Existing edit rules already include `email` and `email_source`.

- `tests/test_email_enrichment.py`
  - Unit tests for parsing, filtering, and ranking.

- `tests/test_scanner.py` or `tests/test_email_enrichment_service.py`
  - Tests database update behavior using mocked enrichment results.

- `README.md`
  - Documents how to run enrichment before CSV export.

## 5. Data Flow

1. User runs one of:

   ```bash
   uv run bf enrich-emails --scan 1
   uv run bf enrich-emails --priority high
   uv run bf enrich-emails --scan 1 --priority high
   ```

2. CLI opens a database session.

3. Service selects `Lead` rows matching filters.

4. For each lead:
   - Skip if `lead.email` exists and `--overwrite` is not set.
   - Skip if `lead.website_status != "live"` unless `--include-non-live` is passed.
   - Pick base URL from `lead.website_final_url or lead.website_url`.
   - Fetch homepage.
   - Extract `mailto:` emails and visible-text emails.
   - Discover same-domain contact/about links.
   - Fetch up to `max_pages - 1` additional pages.
   - Filter candidates.
   - Rank candidates.
   - Save best candidate to `lead.email`.
   - Save concise provenance to `lead.email_source`, e.g. `website_contact_mailto`, `website_contact_text`, `website_home_mailto`, `website_home_text`.

5. Commit changes.

6. User exports as normal:

   ```bash
   uv run bf export leads.csv --priority high
   ```

## 6. Interface Contracts

### CLI: enrich-emails

```bash
uv run bf enrich-emails [OPTIONS]
```

Options:

- `--scan INTEGER`: only enrich leads from one scan.
- `--priority TEXT`: only enrich leads with this priority, e.g. `high`.
- `--website-status TEXT`: default `live`; allow explicit filtering.
- `--limit INTEGER`: optional cap for testing/cost control.
- `--overwrite/--no-overwrite`: default `--no-overwrite`; controls whether existing emails are replaced.
- `--include-non-live`: include leads whose `website_status` is not `live`; default false.
- `--max-pages INTEGER`: default `4`, min `1`, max `8`.
- `--concurrency INTEGER`: default `5`, min `1`, max `20`.

Output:

```text
Email enrichment complete.
Checked: 12
Found: 5
Skipped existing email: 2
Skipped no/live website mismatch: 3
Failed: 0
```

### Function: enrich_leads_emails

```python
@dataclass(frozen=True)
class EmailEnrichmentSummary:
    checked: int
    found: int
    skipped_existing: int
    skipped_website_status: int
    failed: int

async def enrich_leads_emails(
    session: Session,
    *,
    scan_id: int | None = None,
    priority: str | None = None,
    website_status: str | None = "live",
    limit: int | None = None,
    overwrite: bool = False,
    include_non_live: bool = False,
    max_pages: int = 4,
    concurrency: int = 5,
) -> EmailEnrichmentSummary:
    """Find public website emails for selected leads and update Lead.email fields."""
```

Error cases:

- Invalid `max_pages` or `concurrency`: raise `ValueError` or Typer validation error.
- Network timeout/errors: count as failed for that lead; continue processing other leads.
- No usable URL: skipped as website mismatch/no URL.
- No email found: checked but not found.

### Function: enrich_lead_email

```python
@dataclass(frozen=True)
class EmailCandidate:
    email: str
    source: str
    page_url: str
    is_mailto: bool

@dataclass(frozen=True)
class EmailEnrichmentResult:
    email: str | None
    email_source: str | None
    candidates: list[EmailCandidate]
    pages_checked: list[str]
    error: str | None = None

async def enrich_lead_email(
    website_url: str,
    *,
    max_pages: int = 4,
    client: httpx.AsyncClient | None = None,
) -> EmailEnrichmentResult:
    """Fetch a small number of website pages and return the best public email found."""
```

### Pure helpers

```python
def extract_emails_from_html(html: str, page_url: str) -> list[EmailCandidate]
def discover_contact_links(html: str, page_url: str) -> list[str]
def is_usable_email(email: str) -> bool
def choose_best_email(candidates: list[EmailCandidate]) -> EmailCandidate | None
```

## 7. File Changes

Create:

- `business_finder/email_enrichment.py` — email crawling, extraction, filtering, ranking.
- `tests/test_email_enrichment.py` — pure parser/filter/ranker tests.
- `tests/test_email_enrichment_service.py` — mocked service/database behavior tests if needed.

Modify:

- `business_finder/scanner.py` — add `enrich_leads_emails` service function and summary dataclass.
- `business_finder/cli.py` — add `enrich-emails` command.
- `business_finder/admin.py` — optionally show `email_source` in lead list/details.
- `README.md` — document enrichment workflow before export.

No migrations are required because `Lead.email` and `Lead.email_source` already exist.

## 8. Implementation Phases

Use one branch: `feature/email-enrichment`.

### Phase 1 — Pure extraction and ranking

Branch: `feature/email-enrichment`

Commits:

- [ ] Add `email_enrichment.py` dataclasses and pure helper functions.
- [ ] Add tests for extracting `mailto:` and visible-text emails.
- [ ] Add tests for filtering junk emails.
- [ ] Add tests for choosing the best candidate.

Done when:

- `uv run pytest tests/test_email_enrichment.py` passes.
- No network/database access is required by these tests.

### Phase 2 — Bounded website crawling

Branch: `feature/email-enrichment`

Commits:

- [ ] Add homepage fetching with timeout and content-type checks.
- [ ] Add same-domain contact/about link discovery.
- [ ] Add common fallback paths.
- [ ] Add max-pages enforcement and graceful HTTP error handling.
- [ ] Add `httpx.MockTransport` tests for crawl behavior.

Done when:

- The crawler checks no more than `max_pages` URLs per website.
- Network failures return an error result instead of crashing the whole run.
- Tests prove contact-page emails are preferred over homepage emails.

### Phase 3 — Database service and CLI command

Branch: `feature/email-enrichment`

Commits:

- [ ] Add `EmailEnrichmentSummary` and `enrich_leads_emails` service in `scanner.py`.
- [ ] Add `bf enrich-emails` CLI command.
- [ ] Add tests for skip/overwrite/filter behavior.

Done when:

- `uv run bf enrich-emails --scan 1 --priority high` runs without changing existing emails unless `--overwrite` is passed.
- CLI prints checked/found/skipped/failed counts.
- Tests cover one row updated and one row skipped.

### Phase 4 — Docs and manual validation

Branch: `feature/email-enrichment`

Commits:

- [ ] Update README workflow: scan → enrich emails → export → upload to AI Agency Pipeline.
- [ ] Add examples for high-priority enrichment.
- [ ] Run full test suite.
- [ ] Manually validate on a small scan with `--limit 5`.

Done when:

- `uv run pytest` passes.
- README includes:

  ```bash
  uv run bf enrich-emails --priority high
  uv run bf export leads.csv --priority high
  ```

- A small real run populates some `Lead.email` values without literal `None` in CSV export.

## 9. Testing Strategy

Unit tests:

- Extract `info@example.com` from `mailto:info@example.com`.
- Extract `hello@example.com` from visible text.
- Decode simple `mailto:` values with query strings, e.g. `mailto:info@example.com?subject=Hi`.
- Ignore invalid regex false positives.
- Ignore junk/no-reply addresses.
- Ignore email-looking strings in image filenames or CSS assets.
- Keep only same-domain contact/about links.
- Rank contact-page `mailto:` above homepage visible text.
- Prefer useful role inboxes over `noreply@` or technical addresses.

Integration-ish tests with `httpx.MockTransport`:

- Homepage contains a contact link; contact page contains email; result returns contact email.
- Homepage has email; contact page 404s; result still returns homepage email.
- Timeout/error on one page does not crash the enrichment.
- `max_pages` is respected.

Database/service tests:

- Existing email is not overwritten by default.
- Existing email is overwritten when `overwrite=True`.
- Non-live lead is skipped by default.
- Selected lead gets `email` and `email_source` updated.
- Summary counts are correct.

Validation commands:

```bash
uv run pytest
uv run bf enrich-emails --priority high --limit 5
uv run bf export ~/Downloads/leads-compatible.csv --priority high
```

## 10. Security Implications

This feature processes public website content and stores email addresses, which are personal/business contact data.

Security/privacy controls:

- Only fetch public pages; do not authenticate, submit forms, bypass CAPTCHAs, or evade blocks.
- Keep request volume low with `max_pages`, `concurrency`, and optional `limit`.
- Do not log full page bodies.
- Do not log secrets or `.env` values.
- Store only one best email per lead, not a large scraped contact dataset.
- Preserve `email_source` so the provenance is visible.
- Treat emails as PII in future exports/integrations.

Input risks:

- `website_url` is externally sourced from Google Places and could be malicious.
- Fetching arbitrary URLs has SSRF-like risk if this app is ever exposed to untrusted users.
- Phase 1 is local/internal, but still mitigate by:
  - allowing only `http` and `https`,
  - not following non-web schemes,
  - using timeouts,
  - limiting redirects via httpx defaults,
  - optionally rejecting localhost/private IPs before any future hosted version.

Injection risks:

- No SQL interpolation; use SQLAlchemy filters.
- No shell commands from URLs or page content.
- CSV export already uses Python `csv.writer`.

## 11. Risks & Tradeoffs

- Risk: false-positive emails from assets or unrelated page text.
  - Mitigation: conservative regex, reject file extensions/domains, prefer `mailto:` links.

- Risk: scraping can annoy sites if too aggressive.
  - Mitigation: low default concurrency, low max pages, `--limit`, no broad crawling.

- Risk: some websites hide emails behind JavaScript or contact forms.
  - Mitigation: accepted for Phase 1; do not add browser automation yet.

- Risk: generic emails may still not be accepted by AI Agency Pipeline if malformed.
  - Mitigation: strict validation and tests; downstream CSV keeps blanks for missing email rather than `None`.

- Risk: website content may include personal emails, not business inboxes.
  - Mitigation: prefer role inboxes; this remains public contact data and must be handled carefully.

- Tradeoff: standard-library HTML parsing is less robust than BeautifulSoup.
  - Mitigation: start stdlib to avoid dependency; add BeautifulSoup only if real sites prove it necessary.

## 12. Open Questions

Resolved/accepted before implementation:

- Should enrichment run automatically after every scan?
  - Decision: no. Add explicit `bf enrich-emails` first so API/network usage is controlled.

- Should existing manually entered emails be overwritten?
  - Decision: no by default. Only overwrite with `--overwrite`.

- Should non-live websites be enriched?
  - Decision: no by default. Allow `--include-non-live` for manual experiments.

- Should we use a paid enrichment provider?
  - Decision: not in this phase. Revisit only after website scraping results are measured.

- Should we store multiple emails?
  - Decision: not in this phase. Store one best email in the existing `Lead.email` field.
