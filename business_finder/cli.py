import asyncio

import typer

from business_finder.config import get_settings
from business_finder.database import SessionLocal
from business_finder.scanner import check_websites_for_scan, scan_businesses

app = typer.Typer(help="Business Lead Finder CLI")


@app.command()
def scan(
    category: str,
    city: str = typer.Option(..., "--city", help="City/town/area to search."),
    country: str | None = typer.Option("gb", "--country", help="Country/region code hint."),
    max_pages: int = typer.Option(1, "--max-pages", min=1, max=3),
    included_type: str | None = typer.Option(None, "--included-type", help="Official Google place type."),
) -> None:
    query = f"{category} in {city}"
    typer.echo(f"Running Places Text Search: {query}")
    typer.echo(f"Max pages/API calls: {max_pages}")
    with SessionLocal() as session:
        try:
            summary = asyncio.run(scan_businesses(session, category, city, country, included_type, max_pages))
        except Exception as exc:
            raise typer.Exit(f"Scan failed: {exc}") from exc
    typer.echo(f"Scan #{summary.scan_id} complete")
    typer.echo(f"API calls/pages: {summary.api_calls}")
    typer.echo(f"Results stored: {summary.results_count}")
    typer.echo(f"High priority leads: {summary.high_priority_count}")
    typer.echo(f"Dashboard: {get_settings().app_base_url}/admin")


@app.command("check-websites")
def check_websites(scan_id: int = typer.Option(..., "--scan-id", help="Scan ID to recheck.")) -> None:
    with SessionLocal() as session:
        count = asyncio.run(check_websites_for_scan(session, scan_id))
    typer.echo(f"Checked {count} lead websites for scan #{scan_id}.")


if __name__ == "__main__":
    app()
