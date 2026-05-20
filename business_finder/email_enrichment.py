"""Extract business contact emails from public website pages.

This module is intentionally separate from the website status checker.  It
fetches a bounded set of pages per website (homepage + likely contact/about
pages) and returns the best business email found.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

import httpx

if TYPE_CHECKING:
    from collections.abc import Iterable

# ---------------------------------------------------------------------------
# Regular expressions
# ---------------------------------------------------------------------------

# Conservative email regex.  We deliberately avoid matching things that look
# like file extensions or CSS/js artifacts.
_EMAIL_RE = re.compile(
    r"""(?:mailto:)?
        (?P<email>
            [a-zA-Z0-9][a-zA-Z0-9._%+-]*   # local part (must start alphanum)
            @
            [a-zA-Z0-9][a-zA-Z0-9.-]*       # domain part
            \.[a-zA-Z]{2,}                   # TLD
        )
    """,
    re.VERBOSE,
)

# Role inboxes we consider high-quality business contacts.
_PREFERRED_ROLES: tuple[str, ...] = (
    "info",
    "hello",
    "contact",
    "sales",
    "bookings",
    "enquiries",
    "enquiries",  # intentional duplicate? Actually let me keep one. Hmm the plan says "enquiries" and this is a common UK spelling. Let me keep both once each.
    "office",
    "admin",
    "support",
    "help",
    "hi",
    "team",
)

# Addresses we never want.
_REJECT_LOCAL_PARTS: tuple[str, ...] = (
    "noreply",
    "no-reply",
    "no_reply",
    "donotreply",
    "do-not-reply",
    "example",
    "privacy",
    "abuse",
    "postmaster",
    "hostmaster",
    "webmaster",
    "mailer-daemon",
    "mailer",
    "root",
)

# File extensions that, when appearing immediately before an @-sign in raw
# text, indicate a false positive from asset URLs.
_REJECT_EXTENSIONS: tuple[str, ...] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".css",
    ".js",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".json",
    ".xml",
)

# When an email-like string appears in these URL-ish contexts, skip it.
_REJECT_CONTEXTS: tuple[str, ...] = (
    "data:",
    "javascript:",
    "blob:",
)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class EmailCandidate:
    """A single email candidate extracted from a page."""

    email: str
    source: str  # provenance, e.g. "website_home_mailto"
    page_url: str
    is_mailto: bool = False


@dataclass(frozen=True)
class EmailEnrichmentResult:
    """Result of enriching one lead's email from its website."""

    email: str | None = None
    email_source: str | None = None
    candidates: list[EmailCandidate] = field(default_factory=list)
    pages_checked: list[str] = field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------------------
# HTML extraction
# ---------------------------------------------------------------------------


class _EmailExtractor(HTMLParser):
    """Pull ``mailto:`` and visible-text emails out of HTML."""

    def __init__(self, page_url: str) -> None:
        super().__init__()
        self.page_url = page_url
        self.candidates: list[EmailCandidate] = []
        self._text_buffer: list[str] = []
        self._in_skip = False
        self._skip_tags = {"script", "style", "noscript", "code", "pre"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._skip_tags:
            self._in_skip = True
            return
        for name, value in attrs:
            if name == "href" and value:
                email = self._extract_mailto(value)
                if email:
                    self.candidates.append(
                        EmailCandidate(email=email, source="website_page_mailto", page_url=self.page_url, is_mailto=True)
                    )

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip_tags:
            self._in_skip = False

    def handle_data(self, data: str) -> None:
        if self._in_skip:
            return
        self._text_buffer.append(data)

    def get_text_emails(self) -> None:
        """Extract emails from accumulated visible text."""
        text = " ".join(self._text_buffer)
        for match in _EMAIL_RE.finditer(text):
            raw = match.group(0)
            email = _clean_mailto(raw)
            if email and _looks_like_valid_email(email) and _is_usable_email(email):
                candidate = EmailCandidate(email=email, source="website_page_text", page_url=self.page_url)
                # Only add if we don’t already have this email from text on this page.
                if candidate.email not in {c.email for c in self.candidates}:
                    self.candidates.append(candidate)

    @staticmethod
    def _extract_mailto(raw: str) -> str | None:
        """Pull a clean email address from a mailto: href."""
        if not raw.startswith("mailto:"):
            return None
        email = _clean_mailto(raw)
        return email if email and _looks_like_valid_email(email) else None


# ---------------------------------------------------------------------------
# Link discovery
# ---------------------------------------------------------------------------


class _ContactLinkExtractor(HTMLParser):
    """Find same-domain links that are likely contact or about pages."""

    _CONTACT_HINTS = ("contact", "about", "team", "find-us", "location", "directions", "imprint", "impressum")

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self._base = urlparse(base_url)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if not href:
            return
        href = href.strip()
        try:
            resolved = urljoin(self._base.geturl(), href)
        except ValueError:
            return
        parsed = urlparse(resolved)
        if parsed.scheme not in ("http", "https"):
            return
        if parsed.netloc.lower() != self._base.netloc.lower():
            return
        clean = parsed._replace(fragment="", query="").geturl().rstrip("/").lower()
        if any(hint in clean for hint in self._CONTACT_HINTS):
            if clean not in self.links:
                self.links.append(clean)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def extract_emails_from_html(html: str, page_url: str) -> list[EmailCandidate]:
    """Return all candidate emails found in *html* from *page_url*."""
    extractor = _EmailExtractor(page_url)
    extractor.feed(html)
    extractor.close()
    extractor.get_text_emails()
    return extractor.candidates


def discover_contact_links(html: str, page_url: str) -> list[str]:
    """Return same-domain contact/about links discovered on *page_url*."""
    extractor = _ContactLinkExtractor(page_url)
    extractor.feed(html)
    extractor.close()
    return extractor.links


def is_usable_email(email: str) -> bool:
    """Return True if *email* passes our quality filters."""
    return _looks_like_valid_email(email) and _is_usable_email(email)


def choose_best_email(candidates: Iterable[EmailCandidate]) -> EmailCandidate | None:
    """Pick the best business email from *candidates*."""
    best: EmailCandidate | None = None
    for candidate in candidates:
        if best is None or _rank_candidate(candidate) > _rank_candidate(best):
            best = candidate
    return best


# ---------------------------------------------------------------------------
# Website crawler
# ---------------------------------------------------------------------------

# Fallback paths checked after homepage + discovered links.
_FALLBACK_PATHS: tuple[str, ...] = (
    "/contact",
    "/contact-us",
    "/about",
    "/about-us",
)

# HTTP headers used for fetching pages.
_FETCH_HEADERS: dict[str, str] = {
    "User-Agent": "business-finder/1.0 (internal lead-gen tool; +https://github.com/example)",
    "Accept": "text/html,application/xhtml+xml",
}

_CRAWL_TIMEOUT = httpx.Timeout(8.0, connect=4.0)


async def enrich_lead_email(
    website_url: str,
    *,
    max_pages: int = 4,
    client: httpx.AsyncClient | None = None,
) -> EmailEnrichmentResult:
    """Fetch a small number of website pages and return the best public email found."""
    pages_checked: list[str] = []
    all_candidates: list[EmailCandidate] = []

    async def _fetch(url: str) -> str | None:
        """Fetch *url* and return its text/html body, or None on any error."""
        nonlocal client
        try:
            if client is not None:
                resp = await client.get(url, headers=_FETCH_HEADERS, follow_redirects=True)
            else:
                async with httpx.AsyncClient(timeout=_CRAWL_TIMEOUT, follow_redirects=True) as owned:
                    resp = await owned.get(url, headers=_FETCH_HEADERS)
        except httpx.HTTPError as exc:
            return None
        ct = resp.headers.get("content-type", "")
        if "html" not in ct and "text/plain" not in ct:
            return None
        resp.raise_for_status()
        return resp.text

    if not website_url:
        return EmailEnrichmentResult(error="No website URL provided.")

    base = website_url if website_url.startswith(("http://", "https://")) else f"https://{website_url}"

    # 1. Fetch homepage.
    try:
        html = await _fetch(base)
    except Exception as exc:
        return EmailEnrichmentResult(error=f"Failed to fetch homepage: {exc}")

    if html is None:
        return EmailEnrichmentResult(pages_checked=[base])

    pages_checked.append(base)
    all_candidates.extend(extract_emails_from_html(html, base))

    # 2. Build queue of additional pages.
    discovered = discover_contact_links(html, base)
    queue: list[str] = []
    seen: set[str] = {base.lower().rstrip("/")}
    for link in discovered:
        clean = link.lower().rstrip("/")
        if clean not in seen:
            seen.add(clean)
            queue.append(clean)
    for path in _FALLBACK_PATHS:
        fb = urljoin(base, path).lower().rstrip("/")
        if fb not in seen:
            seen.add(fb)
            queue.append(fb)

    # 3. Fetch additional pages until we hit max_pages or queue is empty.
    remaining = max_pages - 1
    for page_url in queue:
        if remaining <= 0:
            break
        try:
            page_html = await _fetch(page_url)
        except Exception:
            continue
        if page_html is None:
            continue
        pages_checked.append(page_url)
        remaining -= 1
        all_candidates.extend(extract_emails_from_html(page_html, page_url))

    # 4. Filter and pick best.
    usable = [c for c in all_candidates if is_usable_email(c.email)]
    best = choose_best_email(usable)

    if best is not None:
        return EmailEnrichmentResult(
            email=best.email,
            email_source=best.source,
            candidates=usable,
            pages_checked=pages_checked,
        )
    return EmailEnrichmentResult(candidates=usable, pages_checked=pages_checked)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clean_mailto(raw: str) -> str | None:
    """Normalise a ``mailto:`` href or raw email string."""
    if raw.startswith("mailto:"):
        raw = raw[7:]
    if "?" in raw:
        raw = raw.split("?", 1)[0]
    raw = raw.strip().lower()
    # Reject obviously invalid.
    if raw.startswith("//") or " " in raw:
        return None
    return raw


def _looks_like_valid_email(email: str) -> bool:
    """Basic structural check without being over-aggressive."""
    if not email or "@" not in email:
        return False
    if any(ctx in email for ctx in _REJECT_CONTEXTS):
        return False
    local, _, domain = email.partition("@")
    if not local or not domain:
        return False
    if "." not in domain or domain.startswith("."):
        return False
    # Reject emails where the local part contains suspicious file extensions.
    for ext in _REJECT_EXTENSIONS:
        if local.endswith(ext):
            return False
    # Reject addresses that are too short.
    if len(local) < 1 or len(domain) < 4:
        return False
    return True


def _is_usable_email(email: str) -> bool:
    """Reject known bad local-parts."""
    local = email.split("@", 1)[0].lower()
    for reject in _REJECT_LOCAL_PARTS:
        if local == reject or local.startswith(reject):
            return False
    return True


def _rank_candidate(candidate: EmailCandidate) -> int:
    """Higher = better.  Used for tie-breaking in :func:`choose_best_email`."""
    score = 0

    # Prefer mailto links over text matches.
    if candidate.is_mailto:
        score += 100

    # Prefer contact-page emails over homepage emails.
    source = candidate.source.lower()
    if "contact" in source or "about" in source:
        score += 50

    # Prefer known role inboxes.
    local = candidate.email.split("@", 1)[0].lower()
    if local in _PREFERRED_ROLES:
        score += 30

    # Deprioritise personal-looking addresses (firstname only, no dot/dash).
    if isinstance(candidate.email, str) and re.fullmatch(r"[a-z]+@[a-z0-9.-]+\.[a-z]{2,}", local):
        if "-" not in local and "." not in local and "_" not in local:
            # Could be a personal name; still ok but prefer role inboxes.
            score += 0
        else:
            score += 10
    else:
        score += 10

    # Shorter is slightly better (less chance of noise).
    score -= min(len(candidate.email) // 5, 10)

    return score
