import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from business_finder.models import WebsiteStatus

SOCIAL_DOMAINS = {"facebook.com", "instagram.com", "tiktok.com", "linktr.ee", "linkedin.com", "x.com", "twitter.com"}
THIRD_PARTY_DOMAINS = {
    "yelp.com",
    "tripadvisor.com",
    "fresha.com",
    "treatwell.co.uk",
    "checkatrade.com",
    "booking.com",
    "just-eat.co.uk",
    "deliveroo.co.uk",
}


@dataclass(frozen=True)
class WebsiteCheckResult:
    status: str
    final_url: str | None = None
    http_status_code: int | None = None
    redirect_chain: list[str] = field(default_factory=list)
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: str | None = None


def normalise_domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        return host[4:]
    return host


def domain_matches(domain: str, candidates: set[str]) -> bool:
    return any(domain == candidate or domain.endswith(f".{candidate}") for candidate in candidates)


def classify_url(url: str) -> str:
    domain = normalise_domain(url)
    if domain_matches(domain, SOCIAL_DOMAINS):
        return WebsiteStatus.SOCIAL_ONLY
    if domain_matches(domain, THIRD_PARTY_DOMAINS):
        return WebsiteStatus.THIRD_PARTY_PLATFORM
    return WebsiteStatus.LIVE


async def check_website(url: str | None, client: httpx.AsyncClient | None = None) -> WebsiteCheckResult:
    if not url:
        return WebsiteCheckResult(status=WebsiteStatus.NO_SITE)
    request_url = url if url.startswith(("http://", "https://")) else f"https://{url}"
    try:
        if client is not None:
            response = await client.get(request_url, follow_redirects=True)
        else:
            timeout = httpx.Timeout(8.0, connect=4.0)
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as owned_client:
                response = await owned_client.get(request_url)
    except httpx.TooManyRedirects as exc:
        return WebsiteCheckResult(status=WebsiteStatus.BROKEN, final_url=request_url, error=str(exc))
    except httpx.HTTPError as exc:
        return WebsiteCheckResult(status=WebsiteStatus.BROKEN, final_url=request_url, error=exc.__class__.__name__)

    chain = [str(item.url) for item in response.history] + [str(response.url)]
    if response.status_code >= 400:
        status = WebsiteStatus.BROKEN
    else:
        status = classify_url(str(response.url))
    return WebsiteCheckResult(status=status, final_url=str(response.url), http_status_code=response.status_code, redirect_chain=chain)


async def check_many(leads, *, concurrency: int = 10) -> list[tuple[object, WebsiteCheckResult]]:
    semaphore = asyncio.Semaphore(concurrency)
    timeout = httpx.Timeout(8.0, connect=4.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        async def run(lead):
            async with semaphore:
                return lead, await check_website(lead.website_url, client)

        return await asyncio.gather(*(run(lead) for lead in leads))
