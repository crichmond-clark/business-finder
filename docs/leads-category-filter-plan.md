# Leads Category & Filtering — Plan

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
- [10. Security Implications](#10-security-implications)
- [11. Risks &amp; Tradeoffs](#11-risks-tradeoffs)
- [12. Open Questions](#12-open-questions)

## 1. Problem Statement

Leads from different scan categories (plumbers, electricians, roofers, etc.) all live in a single flat list in the admin dashboard. There is no way to:

- Filter the admin view by category (e.g., "show me only plumbers")
- Filter CSV exports by category
- See the category label on leads without cross-referencing the scan

The `Scan` model already stores `category` (the user's search term like `"plumbers"`), but `Lead` does not carry it. The admin and export endpoints also lack a category filter.

## 2. Goals &amp; Non-Goals

**Goals:**

- Add category filtering to the Lead admin list (so leads can be browsed by business type)
- Add category filtering to the CLI `export` command
- Add category filtering to the web `GET /exports/leads.csv` endpoint
- Include `category` as a column in CSV exports so downstream tools can group by it
- Add `primary_type` (Google's place classification) as an admin filter and CSV column
- Backfill existing leads with their scan's category

**Non-Goals:**

- Hierarchical or multi-level category system
- Category management CRUD (categories come from scan, not a separate taxonomy)
- Custom frontend — SQLAdmin filters and CSV exports are enough
- Changing how scans work or how categories are assigned

## 3. Proposed Architecture

Denormalize `category` onto the `Lead` table. This is the simplest path and matches the project's existing pragmatism:

- Add `Lead.category: Mapped[str | None]` column
- Populate it from `Scan.category` at scan time (in `place_to_lead`)
- Run a one-off data migration to backfill existing leads
- Add `AllUniqueStringValuesFilter` on `Lead.category` and `Lead.primary_type` in the admin
- Add `category` and `primary_type` query params to both export paths
- Add `category` and `primary_type` columns to the CSV output

**Why denormalize instead of joining to Scan on every query:**

- Filtering by a related table's column requires either a custom filter class in SQLAdmin or always joining. Denormalizing keeps it simple.
- Category is write-once (set at scan time, never changes). No staleness risk.
- The project already uses this pattern: `priority`, `score`, and `website_status` are all written once and stored on Lead.
- Exports become trivial — no joinedload needed for category filtering.

**Why not a separate `Category` table with a FK:**

- Over-engineering for a tool that gets categories from Google search queries.
- No category management UI needed.
- Adds join complexity to every filtered query.

## 4. Component Breakdown

### 4.1 Model change (`models.py`)

Add `category` column to `Lead`. The `primary_type` column already exists. No new tables.

### 4.2 Scanner change (`scanner.py`)

In `place_to_lead`, accept and set `category` from the parent scan.

### 4.3 Migration (`alembic/versions/`)

One migration to add the column. One data migration (raw SQL via `op.execute`) to backfill `lead.category` from `scan.category`.

### 4.4 Admin filters (`admin.py`)

Add `AllUniqueStringValuesFilter` for `Lead.category` and `Lead.primary_type`.

### 4.5 Export changes (`exports.py`, `cli.py`)

Add `category` and `primary_type` query params to both the CLI `export` command and the web endpoint. Add both columns to `LEAD_CSV_HEADERS` and the row writer.

## 5. Data Flow

```
Scan (category="plumbers")
  │
  └─► place_to_lead(scan_id, place, category="plumbers")
        │
        └─► Lead(category="plumbers", ...)

Admin: filter by Lead.category ▼ plumbers ▼
Export: GET /exports/leads.csv?category=plumbers
CLI:    bf export leads.csv --category plumbers
CSV:    business_name,category,city,address,...
```

## 6. Interface Contracts

### 6.1 CLI export — new params

```bash
bf export [OUTPUT] [--scan SCAN_ID] [--priority PRIORITY]
          [--website-status STATUS] [--outreach-status STATUS]
          [--category CATEGORY]          # NEW
          [--primary-type PRIMARY_TYPE]  # NEW
```

### 6.2 Web export — new query params

```
GET /exports/leads.csv?category=plumbers&primary_type=plumber
```

Both params are optional, nullable, and additive (AND logic with existing filters).

### 6.3 CSV output — new columns

Insert `category` and `primary_type` between `business_name` and `city`:

```
business_name,category,primary_type,city,address,phone,email,...
```

### 6.4 `place_to_lead` — new param

```python
def place_to_lead(scan_id: int, place: dict, category: str | None = None) -> Lead:
```

## 7. File Changes

- **Modify:** `business_finder/models.py` — add `category` column to `Lead`
- **Modify:** `business_finder/scanner.py` — pass `category` through `place_to_lead` and `upsert_lead`
- **Create:** `alembic/versions/0002_add_category_to_leads.py` — schema migration + data backfill
- **Modify:** `business_finder/admin.py` — add `category` and `primary_type` filters
- **Modify:** `business_finder/exports.py` — add `category` and `primary_type` to CSV headers, row writer, and query filters
- **Modify:** `business_finder/cli.py` — add `--category` and `--primary-type` flags to `export` command
- **Modify:** `tests/test_exports.py` — add test cases for new filters and columns

## 8. Implementation Phases

Branch: `feature/leads-category-filter`

### Phase 1 — Schema + backfill

- Commits:
  - [ ] Add `category` column to `Lead` model
  - [ ] Add Alembic migration (add column + backfill from scan.category)
  - [ ] Update `place_to_lead` and `upsert_lead` to accept and set `category`
- **Done when:** `uv run alembic upgrade head` succeeds, existing leads have their category populated, new scans set category on leads.

### Phase 2 — Admin filters

- Commits:
  - [ ] Add `AllUniqueStringValuesFilter` for `Lead.category` and `Lead.primary_type` in `LeadAdmin`
- **Done when:** Admin lead list shows category/primary_type filter dropdowns with distinct values, filtering works.

### Phase 3 — Export filters + CSV columns

- Commits:
  - [ ] Add `category` and `primary_type` to `LEAD_CSV_HEADERS` and `write_leads_csv` row writer
  - [ ] Add `category` and `primary_type` query params to web export endpoint
  - [ ] Add `--category` and `--primary-type` flags to CLI `export` command
- **Done when:** `bf export leads.csv --category plumbers` produces a CSV with category column populated and only plumber leads. Web export behaves the same.

### Phase 4 — Tests

- Commits:
  - [ ] Add tests for new export filters (category, primary_type)
  - [ ] Add tests for CSV column presence
- **Done when:** `uv run pytest` passes with new test coverage.

## 9. Testing Strategy

- **Unit tests:**
  - `test_exports.py`: category/primary_type filter correctly narrows results; CSV headers include new columns; row values match
- **Integration tests:**
  - Run a real scan, verify `Lead.category` is populated
  - Export via CLI with `--category` flag, verify row count and content
- **Edge cases:**
  - Leads with `category=None` (older scans before category was stored? should be backfilled)
  - Leads with `primary_type=None`
  - Combining `category` filter with existing filters (priority, website_status, etc.)
  - Empty result set from filter combination

## 10. Security Implications

No security implications. This is a local/internal tool. The new query parameters are simple string filters applied server-side via SQLAlchemy WHERE clauses — no injection risk. No new data exposure.

## 11. Risks &amp; Tradeoffs

- **Risk:** Denormalized `category` could become stale if a `Scan.category` is ever edited.

  **Mitigation:** `Scan.category` is write-once (never edited in practice). If editing is ever added, we'd add a hook to sync. For now, acceptable.

- **Risk:** `primary_type` is Google's classification, which may not match the user's search term. Could cause confusion.

  **Mitigation:** Label the filter clearly in the admin. Both axes (search category and Google type) are useful independently — category gives the user's intent, primary_type gives Google's classification. Having both is a feature, not a bug.

## 12. Open Questions

None. All design decisions are resolved.
