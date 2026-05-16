import httpx
import pytest

from business_finder.checker import check_website, classify_url


def test_classify_social_url():
    assert classify_url("https://www.facebook.com/example") == "social_only"


def test_classify_third_party_url():
    assert classify_url("https://www.checkatrade.com/trades/example") == "third_party_platform"


def test_classify_live_url():
    assert classify_url("https://example.com") == "live"


@pytest.mark.asyncio
async def test_empty_url_is_no_site():
    result = await check_website(None)
    assert result.status == "no_site"


@pytest.mark.asyncio
async def test_404_is_broken():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        result = await check_website("https://example.com", client)

    assert result.status == "broken"
    assert result.http_status_code == 404


@pytest.mark.asyncio
async def test_success_is_live():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        result = await check_website("https://example.com", client)

    assert result.status == "live"
