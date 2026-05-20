"""Unit tests for email extraction, filtering, ranking, and crawling."""

import httpx
import pytest

from business_finder.email_enrichment import (
    EmailCandidate,
    choose_best_email,
    discover_contact_links,
    enrich_lead_email,
    extract_emails_from_html,
    is_usable_email,
)

# ---------------------------------------------------------------------------
# extract_emails_from_html
# ---------------------------------------------------------------------------


def test_extract_mailto_email():
    html = '<a href="mailto:info@example.com">email us</a>'
    candidates = extract_emails_from_html(html, "https://example.com")
    assert len(candidates) == 1
    assert candidates[0].email == "info@example.com"
    assert candidates[0].is_mailto is True
    assert candidates[0].source == "website_page_mailto"


def test_extract_mailto_with_query_params():
    html = '<a href="mailto:hello@example.com?subject=Hi">say hi</a>'
    candidates = extract_emails_from_html(html, "https://example.com")
    assert len(candidates) == 1
    assert candidates[0].email == "hello@example.com"


def test_extract_visible_text_email():
    html = "<p>Email us at info@example.com for more details.</p>"
    candidates = extract_emails_from_html(html, "https://example.com")
    assert len(candidates) == 1
    assert candidates[0].email == "info@example.com"
    assert candidates[0].is_mailto is False
    assert candidates[0].source == "website_page_text"


def test_does_not_extract_email_from_script_tags():
    html = "<script>var email = 'info@example.com';</script>"
    candidates = extract_emails_from_html(html, "https://example.com")
    assert len(candidates) == 0


def test_does_not_extract_email_from_style_tags():
    html = "<style>.email::after { content: 'info@example.com'; }</style>"
    candidates = extract_emails_from_html(html, "https://example.com")
    assert len(candidates) == 0


def test_combines_mailto_and_text():
    html = """
    <a href="mailto:contact@example.com">Contact</a>
    <p>Or reach us at info@example.com</p>
    """
    candidates = extract_emails_from_html(html, "https://example.com")
    assert len(candidates) == 2
    emails = {c.email for c in candidates}
    assert "contact@example.com" in emails
    assert "info@example.com" in emails


def test_deduplicates_same_text_email():
    html = "<p>info@example.com info@example.com</p>"
    candidates = extract_emails_from_html(html, "https://example.com")
    assert len(candidates) == 1


# ---------------------------------------------------------------------------
# is_usable_email
# ---------------------------------------------------------------------------


def test_valid_email_is_usable():
    assert is_usable_email("info@example.com") is True
    assert is_usable_email("hello@business.co.uk") is True
    assert is_usable_email("contact@mycompany.com") is True


def test_rejects_noreply_emails():
    assert is_usable_email("noreply@example.com") is False
    assert is_usable_email("no-reply@example.com") is False
    assert is_usable_email("no_reply@example.com") is False
    assert is_usable_email("donotreply@example.com") is False


def test_rejects_example_emails():
    assert is_usable_email("example@example.com") is False


def test_rejects_admin_role_emails():
    assert is_usable_email("abuse@example.com") is False
    assert is_usable_email("postmaster@example.com") is False
    assert is_usable_email("webmaster@example.com") is False
    assert is_usable_email("hostmaster@example.com") is False
    assert is_usable_email("mailer-daemon@example.com") is False
    assert is_usable_email("root@example.com") is False


def test_rejects_malformed_emails():
    assert is_usable_email("") is False
    assert is_usable_email("notanemail") is False
    assert is_usable_email("@example.com") is False
    assert is_usable_email("user@") is False
    assert is_usable_email("user@.com") is False


def test_rejects_file_extension_lookalikes():
    assert is_usable_email("image.png@example.com") is False
    assert is_usable_email("logo.jpg@example.com") is False


# ---------------------------------------------------------------------------
# choose_best_email
# ---------------------------------------------------------------------------


def _c(email: str, **kwargs: object) -> EmailCandidate:
    defaults = {
        "email": email,
        "source": "website_page_text",
        "page_url": "https://example.com",
        "is_mailto": False,
    }
    defaults.update(kwargs)
    return EmailCandidate(**defaults)  # type: ignore[arg-type]


def test_choose_best_prefers_mailto_over_text():
    best = choose_best_email([
        _c("info@example.com", is_mailto=False),
        _c("contact@example.com", is_mailto=True),
    ])
    assert best is not None
    assert best.email == "contact@example.com"


def test_choose_best_prefers_role_inbox_over_personal():
    best = choose_best_email([
        _c("john@example.com"),
        _c("info@example.com"),
    ])
    assert best is not None
    assert best.email == "info@example.com"


def test_choose_best_returns_none_for_empty():
    assert choose_best_email([]) is None


def test_choose_best_returns_sole_candidate():
    best = choose_best_email([_c("hello@example.com")])
    assert best is not None
    assert best.email == "hello@example.com"


# ---------------------------------------------------------------------------
# discover_contact_links
# ---------------------------------------------------------------------------


def test_discovers_contact_link():
    html = '<a href="/contact">Contact Us</a>'
    links = discover_contact_links(html, "https://example.com")
    assert "https://example.com/contact" in links


def test_discovers_about_link():
    html = '<a href="/about-us">About</a>'
    links = discover_contact_links(html, "https://example.com/about")
    assert "https://example.com/about-us" in links


def test_ignores_external_links():
    html = '<a href="https://other-site.com/contact">Contact</a>'
    links = discover_contact_links(html, "https://example.com")
    assert len(links) == 0


def test_discovers_relative_links():
    html = '<a href="contact.html">Contact</a>'
    links = discover_contact_links(html, "https://example.com/page")
    assert "https://example.com/contact.html" in links


# ---------------------------------------------------------------------------
# enrich_lead_email — crawler tests with MockTransport
# ---------------------------------------------------------------------------

HOME_HTML = """<html><body><p>Welcome to Example Co.</p><a href="/contact">Contact Us</a></body></html>"""

CONTACT_HTML = """<html><body><p>Email: <a href="mailto:info@example.com">info@example.com</a></p></body></html>"""

HOME_WITH_EMAIL_HTML = """<html><body><p>hello@example.com</p></body></html>"""

CONTACT_NO_EMAIL_HTML = """<html><body><p>Call us at 555-1234</p></body></html>"""


def _mock_transport(pages: dict[str, str]) -> httpx.MockTransport:
    """Create a MockTransport that serves *pages* keyed by normalized URL."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url).lower().rstrip("/")
        for key, body in pages.items():
            if url == key.lower().rstrip("/"):
                return httpx.Response(200, text=body, headers={"content-type": "text/html"},
                                      request=request)
        return httpx.Response(404, request=request)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_crawler_finds_email_on_contact_page():
    pages = {
        "https://example.com": HOME_HTML,
        "https://example.com/contact": CONTACT_HTML,
    }
    transport = _mock_transport(pages)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        result = await enrich_lead_email("https://example.com", client=client, max_pages=4)

    assert result.email == "info@example.com"
    assert result.email_source == "website_page_mailto"
    assert "https://example.com/contact" in result.pages_checked


@pytest.mark.asyncio
async def test_crawler_finds_email_on_homepage_when_contact_has_none():
    pages = {
        "https://example.com": HOME_WITH_EMAIL_HTML,
        "https://example.com/contact": CONTACT_NO_EMAIL_HTML,
    }
    transport = _mock_transport(pages)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        result = await enrich_lead_email("https://example.com", client=client, max_pages=4)

    assert result.email == "hello@example.com"
    assert "https://example.com" in result.pages_checked


@pytest.mark.asyncio
async def test_crawler_respects_max_pages():
    pages = {
        "https://example.com": HOME_HTML,
        "https://example.com/contact": CONTACT_HTML,
        "https://example.com/about": CONTACT_HTML,
    }
    transport = _mock_transport(pages)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        result = await enrich_lead_email("https://example.com", client=client, max_pages=2)

    assert len(result.pages_checked) <= 2


@pytest.mark.asyncio
async def test_crawler_handles_404_gracefully():
    pages: dict[str, str] = {}
    transport = _mock_transport(pages)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        result = await enrich_lead_email("https://example.com", client=client, max_pages=4)

    assert result.email is None
    assert result.error is None
    assert "https://example.com" in result.pages_checked


@pytest.mark.asyncio
async def test_crawler_handles_no_website_url():
    async with httpx.AsyncClient() as client:
        result = await enrich_lead_email("", client=client)

    assert result.email is None
    assert result.error is not None
    assert "No website URL" in result.error


@pytest.mark.asyncio
async def test_crawler_empty_pages_no_candidates():
    pages = {"https://example.com": "<html><body>No email here.</body></html>"}
    transport = _mock_transport(pages)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        result = await enrich_lead_email("https://example.com", client=client, max_pages=4)

    assert result.email is None
    assert len(result.pages_checked) == 1
