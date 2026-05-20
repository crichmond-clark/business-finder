"""Tests for the enrichment database service using mocked enrichment results."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from business_finder.email_enrichment import EmailEnrichmentResult
from business_finder.models import Base, Lead, Scan
from business_finder.scanner import EmailEnrichmentSummary, enrich_leads_emails

# In-memory SQLite for tests.
_test_engine = create_engine("sqlite://", echo=False)
_TestSession = sessionmaker(bind=_test_engine)


@pytest.fixture(autouse=True)
def _setup_db():
    Base.metadata.create_all(_test_engine)
    yield
    Base.metadata.drop_all(_test_engine)


def _make_scan(session: Session, *, city: str = "Plymouth") -> Scan:
    scan = Scan(query=f"plumbers in {city}", city=city, max_pages=1)
    session.add(scan)
    session.commit()
    return scan


def _make_lead(session: Session, scan: Scan, **kwargs: object) -> Lead:
    defaults = {
        "scan_id": scan.id,
        "place_id": f"places/{kwargs.get('name', 'test')}",
        "name": "Test Business",
        "website_status": "live",
        "website_url": "https://example.com",
        "website_final_url": "https://example.com",
        "email": None,
        "email_source": None,
        "score": 50,
        "priority": "high",
        "outreach_status": "not_contacted",
    }
    defaults.update(kwargs)
    lead = Lead(**defaults)  # type: ignore[arg-type]
    session.add(lead)
    session.commit()
    return lead


@pytest.mark.asyncio
async def test_sets_email_when_found():
    with _TestSession() as session:
        scan = _make_scan(session)
        lead = _make_lead(session, scan, name="FoundCo")

        mock_result = EmailEnrichmentResult(email="info@example.com", email_source="website_page_mailto")
        with patch("business_finder.scanner.enrich_lead_email", new=AsyncMock(return_value=mock_result)):
            summary = await enrich_leads_emails(session, overwrite=False, include_non_live=False)

        session.refresh(lead)
        assert summary.found == 1
        assert lead.email == "info@example.com"
        assert lead.email_source == "website_page_mailto"


@pytest.mark.asyncio
async def test_skips_existing_email_by_default():
    with _TestSession() as session:
        scan = _make_scan(session)
        lead = _make_lead(session, scan, name="ExistingCo", email="old@example.com", email_source="manual")

        mock_result = EmailEnrichmentResult(email="new@example.com", email_source="website_page_mailto")
        with patch("business_finder.scanner.enrich_lead_email", new=AsyncMock(return_value=mock_result)):
            summary = await enrich_leads_emails(session, overwrite=False, include_non_live=False)

        session.refresh(lead)
        assert summary.skipped_existing == 1
        assert summary.found == 0
        assert lead.email == "old@example.com"


@pytest.mark.asyncio
async def test_overwrites_existing_email_when_overwrite_true():
    with _TestSession() as session:
        scan = _make_scan(session)
        lead = _make_lead(
            session, scan, name="OverwriteCo", email="old@example.com", email_source="manual"
        )

        mock_result = EmailEnrichmentResult(email="new@example.com", email_source="website_page_mailto")
        with patch("business_finder.scanner.enrich_lead_email", new=AsyncMock(return_value=mock_result)):
            summary = await enrich_leads_emails(session, overwrite=True, include_non_live=False)

        session.refresh(lead)
        assert summary.found == 1
        assert lead.email == "new@example.com"


@pytest.mark.asyncio
async def test_skips_non_live_by_default():
    with _TestSession() as session:
        scan = _make_scan(session)
        _make_lead(session, scan, name="BrokenCo", website_status="broken", email=None)

        mock_result = EmailEnrichmentResult(email="info@example.com", email_source="website_page_mailto")
        with patch("business_finder.scanner.enrich_lead_email", new=AsyncMock(return_value=mock_result)):
            summary = await enrich_leads_emails(session, overwrite=False, include_non_live=False)

        assert summary.skipped_website_status == 1
        assert summary.found == 0


@pytest.mark.asyncio
async def test_include_non_live_processes_broken_websites():
    with _TestSession() as session:
        scan = _make_scan(session)
        lead = _make_lead(session, scan, name="BrokenCo", website_status="broken", email=None)

        mock_result = EmailEnrichmentResult(email="info@example.com", email_source="website_page_text")
        with patch("business_finder.scanner.enrich_lead_email", new=AsyncMock(return_value=mock_result)):
            summary = await enrich_leads_emails(session, overwrite=False, include_non_live=True)

        session.refresh(lead)
        assert summary.skipped_website_status == 0
        assert summary.found == 1


@pytest.mark.asyncio
async def test_summary_counts_are_correct():
    with _TestSession() as session:
        scan = _make_scan(session)
        _make_lead(session, scan, name="Found1", email=None)  # will be found
        _make_lead(session, scan, name="Skipped", email="keep@example.com", email_source="manual")  # skipped
        _make_lead(session, scan, name="Broken", website_status="broken", website_url="https://broken.example")  # skipped status
        _make_lead(session, scan, name="Found2", email=None)  # will be found

        found_result = EmailEnrichmentResult(email="info@example.com", email_source="website_page_mailto")
        with patch("business_finder.scanner.enrich_lead_email", new=AsyncMock(return_value=found_result)):
            summary = await enrich_leads_emails(session, overwrite=False, include_non_live=False)

        assert summary.checked == 4
        assert summary.found == 2
        assert summary.skipped_existing == 1
        assert summary.skipped_website_status == 1
