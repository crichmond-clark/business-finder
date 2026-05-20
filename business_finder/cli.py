import asyncio
import socket
from pathlib import Path

import typer
import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from business_finder.config import get_settings
from business_finder.database import SessionLocal
from business_finder.exports import write_leads_csv
from business_finder.models import Lead
from business_finder.scanner import check_websites_for_scan, enrich_leads_emails, scan_businesses

app = typer.Typer(help="Find local businesses with weak or missing websites.")


@app.command("init")
def init_database() -> None:
    """Create/update the local database."""
    command.upgrade(Config("alembic.ini"), "head")
    typer.echo("Database ready.")


def _port_is_free(host: str, port: int) -> bool:
    """Return True if no process is listening on the given host:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _find_port(host: str, start_port: int, max_attempts: int = 100) -> int:
    """Find a free port starting from *start_port*, incrementing until one works."""
    port = start_port
    for _ in range(max_attempts):
        if _port_is_free(host, port):
            return port
        typer.echo(f"Port {port} is in use, trying next...", err=True)
        port += 1
    raise RuntimeError(f"No free port found after {max_attempts} attempts starting at {start_port}.")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to."),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind to."),
    reload: bool = typer.Option(True, "--reload/--no-reload", help="Reload when files change."),
) -> None:
    """Start the admin dashboard."""
    actual_port = _find_port(host, port)
    typer.echo(f"Dashboard: http://{host}:{actual_port}/admin")
    uvicorn.run("business_finder.app:app", host=host, port=actual_port, reload=reload)


@app.command()
def scan(
    category: str = typer.Argument(..., help='Business type, e.g. "plumbers".'),
    city: str = typer.Argument(..., help='City/town/area, e.g. "Plymouth".'),
    country: str | None = typer.Option("gb", "--country", "-c", help="Country/region code hint."),
    max_pages: int = typer.Option(1, "--pages", "--max-pages", min=1, max=3, help="Google result pages to fetch."),
    included_type: str | None = typer.Option(None, "--type", "--included-type", help="Official Google place type."),
    auto_enrich: bool = typer.Option(
        False, "--auto-enrich", help="After scanning, crawl live websites for business emails."
    ),
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

    if auto_enrich:
        typer.echo("\nEnriching emails from live websites...")
        with SessionLocal() as session:
            enrichment = asyncio.run(
                enrich_leads_emails(
                    session,
                    scan_id=summary.scan_id,
                    overwrite=False,
                    include_non_live=False,
                )
            )
        typer.echo(f"  Checked: {enrichment.checked}")
        typer.echo(f"  Emails found: {enrichment.found}")
        typer.echo(f"  Skipped (existing email): {enrichment.skipped_existing}")
        typer.echo(f"  Skipped (not live): {enrichment.skipped_website_status}")
        typer.echo(f"  Failed: {enrichment.failed}")

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
        leads = list(session.scalars(statement.options(joinedload(Lead.scan)).order_by(Lead.score.desc(), Lead.name)))

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(write_leads_csv(leads), encoding="utf-8")
    typer.echo(f"Exported {len(leads)} leads to {output}")


@app.command("enrich-emails")
def enrich_emails(
    scan_id: int | None = typer.Option(None, "--scan", "--scan-id", help="Only enrich leads from one scan."),
    priority: str | None = typer.Option(None, "--priority", help="Only enrich leads with this priority."),
    website_status: str | None = typer.Option("live", "--website-status", help="Website status filter."),
    limit: int | None = typer.Option(None, "--limit", help="Cap number of leads to process."),
    overwrite: bool = typer.Option(False, "--overwrite/--no-overwrite", help="Overwrite existing email addresses."),
    include_non_live: bool = typer.Option(
        False, "--include-non-live", help="Include leads whose website_status is not live."
    ),
    max_pages: int = typer.Option(4, "--max-pages", min=1, max=8, help="Max pages to crawl per website."),
    concurrency: int = typer.Option(5, "--concurrency", min=1, max=20, help="Max concurrent website requests."),
) -> None:
    """Find business emails on live websites and save to the lead record."""
    with SessionLocal() as session:
        summary = asyncio.run(
            enrich_leads_emails(
                session,
                scan_id=scan_id,
                priority=priority,
                website_status=website_status,
                limit=limit,
                overwrite=overwrite,
                include_non_live=include_non_live,
                max_pages=max_pages,
                concurrency=concurrency,
            )
        )
    typer.echo("Email enrichment complete.")
    typer.echo(f"Checked: {summary.checked}")
    typer.echo(f"Found: {summary.found}")
    typer.echo(f"Skipped existing email: {summary.skipped_existing}")
    typer.echo(f"Skipped no/live website mismatch: {summary.skipped_website_status}")
    typer.echo(f"Failed: {summary.failed}")


def _check_websites(scan_id: int) -> None:
    with SessionLocal() as session:
        count = asyncio.run(check_websites_for_scan(session, scan_id))
    typer.echo(f"Checked {count} lead websites for scan #{scan_id}.")


if __name__ == "__main__":
    app()
