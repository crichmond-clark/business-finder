import asyncio
import csv
from pathlib import Path

import typer
import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from business_finder.config import get_settings
from business_finder.database import SessionLocal
from business_finder.models import Lead
from business_finder.scanner import check_websites_for_scan, scan_businesses

app = typer.Typer(help="Find local businesses with weak or missing websites.")


@app.command("init")
def init_database() -> None:
    """Create/update the local database."""
    command.upgrade(Config("alembic.ini"), "head")
    typer.echo("Database ready.")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to."),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind to."),
    reload: bool = typer.Option(True, "--reload/--no-reload", help="Reload when files change."),
) -> None:
    """Start the admin dashboard."""
    typer.echo(f"Dashboard: http://{host}:{port}/admin")
    uvicorn.run("business_finder.app:app", host=host, port=port, reload=reload)


@app.command()
def scan(
    category: str = typer.Argument(..., help='Business type, e.g. "plumbers".'),
    city: str = typer.Argument(..., help='City/town/area, e.g. "Plymouth".'),
    country: str | None = typer.Option("gb", "--country", "-c", help="Country/region code hint."),
    max_pages: int = typer.Option(1, "--pages", "--max-pages", min=1, max=3, help="Google result pages to fetch."),
    included_type: str | None = typer.Option(None, "--type", "--included-type", help="Official Google place type."),
) -> None:
    """Search Google Places and store prioritised leads."""
    query = f"{category} in {city}"
    typer.echo(f"Scanning: {query}")
    typer.echo(f"Pages/API calls: up to {max_pages}")
    with SessionLocal() as session:
        try:
            summary = asyncio.run(scan_businesses(session, category, city, country, included_type, max_pages))
        except Exception as exc:
            raise typer.BadParameter(f"Scan failed: {exc}") from exc
    typer.echo(f"Done: scan #{summary.scan_id}")
    typer.echo(f"API calls/pages: {summary.api_calls}")
    typer.echo(f"Results stored: {summary.results_count}")
    typer.echo(f"High priority leads: {summary.high_priority_count}")
    typer.echo(f"Dashboard: {get_settings().app_base_url}/admin")


@app.command("check")
def check(scan_id: int = typer.Argument(..., help="Scan ID to recheck.")) -> None:
    """Recheck websites for a scan without calling Google Places again."""
    _check_websites(scan_id)


@app.command("check-websites")
def check_websites(scan_id: int = typer.Option(..., "--scan-id", help="Scan ID to recheck.")) -> None:
    """Legacy alias for `check`."""
    _check_websites(scan_id)


@app.command()
def export(
    output: Path = typer.Argument(Path("leads.csv"), help="CSV output path."),
    scan_id: int | None = typer.Option(None, "--scan", "--scan-id", help="Only export one scan."),
    priority: str | None = typer.Option(None, "--priority", help="Filter by priority."),
    website_status: str | None = typer.Option(None, "--website-status", help="Filter by website status."),
    outreach_status: str | None = typer.Option(None, "--outreach-status", help="Filter by outreach status."),
) -> None:
    """Export leads directly to CSV."""
    with SessionLocal() as session:
        statement = select(Lead)
        if scan_id is not None:
            statement = statement.where(Lead.scan_id == scan_id)
        if priority:
            statement = statement.where(Lead.priority == priority)
        if website_status:
            statement = statement.where(Lead.website_status == website_status)
        if outreach_status:
            statement = statement.where(Lead.outreach_status == outreach_status)
        leads = list(session.scalars(statement.order_by(Lead.score.desc(), Lead.name)))

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.writer(file_obj)
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
        for lead in leads:
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
    typer.echo(f"Exported {len(leads)} leads to {output}")


def _check_websites(scan_id: int) -> None:
    with SessionLocal() as session:
        count = asyncio.run(check_websites_for_scan(session, scan_id))
    typer.echo(f"Checked {count} lead websites for scan #{scan_id}.")


if __name__ == "__main__":
    app()
