import csv
from io import StringIO

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from business_finder.database import get_session
from business_finder.models import Lead

router = APIRouter()


@router.get("/exports/leads.csv")
def export_leads_csv(
    scan_id: int | None = None,
    priority: str | None = None,
    website_status: str | None = None,
    outreach_status: str | None = None,
    session: Session = Depends(get_session),
) -> Response:
    statement = select(Lead)
    if scan_id is not None:
        statement = statement.where(Lead.scan_id == scan_id)
    if priority:
        statement = statement.where(Lead.priority == priority)
    if website_status:
        statement = statement.where(Lead.website_status == website_status)
    if outreach_status:
        statement = statement.where(Lead.outreach_status == outreach_status)

    rows = session.scalars(statement.order_by(Lead.score.desc(), Lead.name)).all()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "name",
        "address",
        "phone",
        "email",
        "website_status",
        "website_url",
        "website_final_url",
        "rating",
        "review_count",
        "score",
        "priority",
        "outreach_status",
        "notes",
        "google_maps_uri",
    ])
    for lead in rows:
        writer.writerow([
            lead.name,
            lead.address,
            lead.phone,
            lead.email,
            lead.website_status,
            lead.website_url,
            lead.website_final_url,
            lead.rating,
            lead.review_count,
            lead.score,
            lead.priority,
            lead.outreach_status,
            lead.notes,
            lead.google_maps_uri,
        ])
    filename = "leads.csv" if scan_id is None else f"leads-scan-{scan_id}.csv"
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
