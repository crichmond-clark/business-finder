from dataclasses import dataclass

import httpx

PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.googleMapsUri",
        "places.websiteUri",
        "places.nationalPhoneNumber",
        "places.rating",
        "places.userRatingCount",
        "places.businessStatus",
        "places.primaryType",
        "places.types",
        "nextPageToken",
    ]
)


@dataclass(frozen=True)
class PlacesPage:
    places: list[dict]
    next_page_token: str | None


class PlacesApiError(RuntimeError):
    pass


class PlacesClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def search_text(
        self,
        text_query: str,
        *,
        country_code: str | None = None,
        included_type: str | None = None,
        page_token: str | None = None,
    ) -> PlacesPage:
        payload: dict[str, object] = {"textQuery": text_query}
        if country_code:
            payload["regionCode"] = country_code.upper()
        if included_type:
            payload["includedType"] = included_type
        if page_token:
            payload["pageToken"] = page_token

        headers = {"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": FIELD_MASK}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(PLACES_TEXT_SEARCH_URL, json=payload, headers=headers)

        if response.status_code >= 400:
            raise PlacesApiError(f"Places API request failed ({response.status_code}): {response.text}")
        data = response.json()
        return PlacesPage(places=data.get("places", []), next_page_token=data.get("nextPageToken"))
