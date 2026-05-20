import asyncio
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from business_finder.checker import check_many
from business_finder.config import get_settings
from business_finder.email_enrichment import enrich_lead_email
from business_finder.models import Lead, Priority, Scan, WebsiteStatus
from business_finder.scorer import score_lead
from business_finder.services.places import PlacesClient


@dataclass(frozen=True)
class ScanSummary:
    scan_id: int
    query: str
    api_calls: int
    results_count: int
    high_priority_count: int


def build_query(category: str, city: str) -> str:
    return f"{category} in {city}"


def place_to_lead(scan_id: int, place: dict) -> Lead:
    display_name = place.get("displayName") or {}
    return Lead(
        scan_id=scan_id,
        place_id=place["id"],
        name=display_name.get("text") or "Unknown business",
        address=place.get("formattedAddress"),
        phone=place.get("nationalPhoneNumber"),
        google_maps_uri=place.get("googleMapsUri"),
        website_url=place.get("websiteUri"),
        rating=place.get("rating"),
        review_count=place.get("userRatingCount"),
        business_status=place.get("businessStatus"),
        primary_type=place.get("primaryType"),
        types=place.get("types") or [],
        raw_data=place,
        website_status=WebsiteStatus.UNKNOWN,
        score=0,
        priority=Priority.LOW,
    )


def upsert_lead(session: Session, scan_id: int, place: dict) -> Lead:
    lead = session.scalar(select(Lead).where(Lead.scan_id == scan_id, Lead.place_id == place["id"]))
    incoming = place_to_lead(scan_id, place)
    if lead is None:
        session.add(incoming)
        return incoming
    for field in [
        "name",
        "address",
        "phone",
        "google_maps_uri",
        "website_url",
        "rating",
        "review_count",
        "business_status",
        "primary_type",
        "types",
        "raw_data",
    ]:
        setattr(lead, field, getattr(incoming, field))
    return lead


async def scan_businesses(
    session: Session,
    category: str,
    city: str,
    country_code: str | None = None,
    included_type: str | None = None,
    max_pages: int = 1,
) -> ScanSummary:
    settings = get_settings()
    if not settings.google_maps_api_key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is required to run scans.")
    if max_pages < 1 or max_pages > 3:
        raise ValueError("max_pages must be between 1 and 3.")

    query = build_query(category, city)
    scan = Scan(query=query, category=category, included_type=included_type, city=city, country_code=country_code, max_pages=max_pages)
    session.add(scan)
    session.commit()
    session.refresh(scan)

    client = PlacesClient(settings.google_maps_api_key)
    page_token = None
    api_calls = 0
    seen_place_ids: set[str] = set()
    leads: list[Lead] = []

    for _page_number in range(max_pages):
        page = await client.search_text(query, country_code=country_code, included_type=included_type, page_token=page_token)
        api_calls += 1
        for place in page.places:
            place_id = place.get("id")
            if not place_id or place_id in seen_place_ids:
                continue
            seen_place_ids.add(place_id)
            leads.append(upsert_lead(session, scan.id, place))
        session.commit()
        if not page.next_page_token:
            break
        page_token = page.next_page_token

    await check_websites_for_scan(session, scan.id)
    scan.results_count = len(seen_place_ids)
    scan.high_priority_count = session.query(Lead).filter(Lead.scan_id == scan.id, Lead.priority == "high").count()
    session.commit()
    return ScanSummary(scan_id=scan.id, query=query, api_calls=api_calls, results_count=scan.results_count, high_priority_count=scan.high_priority_count)


async def check_websites_for_scan(session: Session, scan_id: int) -> int:
    leads = list(session.scalars(select(Lead).where(Lead.scan_id == scan_id)))
    for lead, result in await check_many(leads):
        lead.website_status = result.status
        lead.website_final_url = result.final_url
        lead.http_status_code = result.http_status_code
        lead.redirect_chain = result.redirect_chain
        lead.last_checked_at = result.checked_at
        lead_score = score_lead(lead)
        lead.score = lead_score.score
        lead.priority = lead_score.priority
    scan = session.get(Scan, scan_id)
    if scan:
        scan.high_priority_count = sum(1 for lead in leads if lead.priority == "high")
    session.commit()
    return len(leads)


# ---------------------------------------------------------------------------
# Email enrichment service
# ---------------------------------------------------------------------------


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
    """Find public website emails for selected leads and update Lead.email."""
    statement = select(Lead)
    if scan_id is not None:
        statement = statement.where(Lead.scan_id == scan_id)
    if priority:
        statement = statement.where(Lead.priority == priority)
    if limit is not None:
        statement = statement.limit(limit)

    leads = list(session.scalars(statement.order_by(Lead.score.desc(), Lead.name)))

    semaphore = asyncio.Semaphore(concurrency)
    skipped_existing = 0
    skipped_website_status = 0
    found = 0
    failed = 0

    async def _process(lead: Lead) -> None:
        nonlocal skipped_existing, skipped_website_status, found, failed
        url = lead.website_final_url or lead.website_url
        if not url or (not include_non_live and lead.website_status != "live"):
            skipped_website_status += 1
            return
        if lead.email and not overwrite:
            skipped_existing += 1
            return
        async with semaphore:
            try:
                result = await enrich_lead_email(url, max_pages=max_pages)
            except Exception:
                failed += 1
                return
        if result.error:
            failed += 1
        elif result.email:
            lead.email = result.email
            lead.email_source = result.email_source
            found += 1

    tasks = [_process(lead) for lead in leads]
    await asyncio.gather(*tasks)
    if found:
        session.commit()

    return EmailEnrichmentSummary(
        checked=len(leads),
        found=found,
        skipped_existing=skipped_existing,
        skipped_website_status=skipped_website_status,
        failed=failed,
    )
