import csv
from io import StringIO
from types import SimpleNamespace

from business_finder.exports import LEAD_CSV_HEADERS, write_leads_csv


def parse_csv(content: str) -> list[dict[str, str]]:
    return list(csv.DictReader(StringIO(content)))


def make_lead(**overrides: object) -> SimpleNamespace:
    values = {
        "name": "Plymouth Plumbing Co",
        "scan": SimpleNamespace(city="Plymouth"),
        "address": "1 Example Street",
        "phone": "01752 000000",
        "email": None,
        "website_url": "https://example.com",
        "place_id": "places/abc123",
        "website_status": "no_site",
        "google_maps_uri": "https://maps.google.com/?cid=123",
        "rating": 4.5,
        "review_count": 42,
        "score": 91,
        "priority": "high",
        "outreach_status": "not_contacted",
        "notes": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_lead_csv_headers_exactly_match_ai_agency_pipeline_shape():
    content = write_leads_csv([])
    headers = next(csv.reader(StringIO(content)))

    assert headers == LEAD_CSV_HEADERS
    assert headers == [
        "business_name",
        "city",
        "address",
        "phone",
        "email",
        "website_url",
        "place_id",
        "website_status",
        "google_maps_uri",
        "rating",
        "review_count",
        "score",
        "priority",
        "outreach_status",
        "notes",
    ]


def test_lead_csv_includes_ai_agency_pipeline_identity_fields():
    rows = parse_csv(write_leads_csv([make_lead()]))

    assert rows[0]["business_name"] == "Plymouth Plumbing Co"
    assert rows[0]["city"] == "Plymouth"
    assert rows[0]["place_id"] == "places/abc123"
    assert rows[0]["website_status"] == "no_site"


def test_lead_csv_exports_nullable_values_as_blank_cells():
    content = write_leads_csv([make_lead(address=None, email=None, rating=None, review_count=None, notes=None)])
    rows = parse_csv(content)

    assert rows[0]["address"] == ""
    assert rows[0]["email"] == ""
    assert rows[0]["rating"] == ""
    assert rows[0]["review_count"] == ""
    assert rows[0]["notes"] == ""
    assert "None" not in content


def test_lead_csv_exports_one_row_per_lead_not_one_row_per_scan():
    scan = SimpleNamespace(city="Plymouth")
    content = write_leads_csv([
        make_lead(name="Lead One", scan=scan, place_id="places/one"),
        make_lead(name="Lead Two", scan=scan, place_id="places/two"),
    ])
    rows = parse_csv(content)

    assert len(rows) == 2
    assert {row["business_name"] for row in rows} == {"Lead One", "Lead Two"}
