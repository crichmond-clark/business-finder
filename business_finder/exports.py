import csv
from io import StringIO

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from business_finder.database import get_session
from business_finder.models import Lead

router = APIRouter()

LEAD_CSV_HEADERS = [
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


def csv_value(value: object) -> object:
    return "" if value is None else value


def write_leads_csv(leads: list[Lead]) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(LEAD_CSV_HEADERS)
    for lead in leads:
        writer.writerow([
            csv_value(lead.name),
            csv_value(lead.scan.city),
            csv_value(lead.address),
            csv_value(lead.phone),
            csv_value(lead.email),
            csv_value(lead.website_url),
            csv_value(lead.place_id),
            csv_value(lead.website_status),
            csv_value(lead.google_maps_uri),
            csv_value(lead.rating),
            csv_value(lead.review_count),
            csv_value(lead.score),
            csv_value(lead.priority),
            csv_value(lead.outreach_status),
            csv_value(lead.notes),
        ])
    return output.getvalue()


@router.get("/exports/leads.csv")
def export_leads_csv(
    scan_id: int | None = None,
    priority: str | None = None,
    website_status: str | None = None,
    outreach_status: str | None = None,
    session: Session = Depends(get_session),
) -> Response:
    statement = select(Lead).options(joinedload(Lead.scan))
    if scan_id is not None:
        statement = statement.where(Lead.scan_id == scan_id)
    if priority:
        statement = statement.where(Lead.priority == priority)
    if website_status:
        statement = statement.where(Lead.website_status == website_status)
    if outreach_status:
        statement = statement.where(Lead.outreach_status == outreach_status)

    rows = list(session.scalars(statement.order_by(Lead.score.desc(), Lead.name)))
    filename = "leads.csv" if scan_id is None else f"leads-scan-{scan_id}.csv"
    return Response(
        write_leads_csv(rows),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
