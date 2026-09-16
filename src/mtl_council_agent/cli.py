"""Command line interface: ingest, inspect quality, and ask questions."""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime

import click
from dotenv import load_dotenv

from mtl_council_agent import quality
from mtl_council_agent.db import client as db


def _default_backfill_start() -> date:
    today = date.today()
    return date(today.year - 2, 1, 1)


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Show progress logging.")
def main(verbose: bool) -> None:
    """Montreal city council AI agent."""
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )


@main.command("init-db")
def init_db() -> None:
    """Create the schema in the database at DATABASE_URL."""
    with db.connect() as conn:
        db.init_schema(conn)
    click.echo("schema created")


@main.command()
@click.option(
    "--since",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="Ingest meetings on or after this date (default: two years back).",
)
@click.option(
    "--reingest",
    is_flag=True,
    help="Re-process meetings already in the database.",
)
def ingest(since: datetime | None, reingest: bool) -> None:
    """Scrape the portal and load meetings into the database."""
    from mtl_council_agent.ingestion.pipeline import run_ingestion

    start = since.date() if since else _default_backfill_start()
    click.echo(f"ingesting meetings since {start}")

    result = run_ingestion(start, skip_existing=not reingest)

    click.echo(
        f"{result.meetings_ingested}/{result.meetings_seen} meetings ingested, "
        f"{result.items_loaded} items, {result.chunks_embedded} chunks"
    )
    for failure in result.failures:
        click.echo(f"  FAILED {failure}", err=True)
    if result.failures:
        sys.exit(1)


@main.command("quality-report")
@click.option(
    "--since",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="Window to measure completeness against (default: two years back).",
)
@click.option(
    "--check",
    is_flag=True,
    help="Exit non-zero if any metric falls below its threshold (for CI).",
)
def quality_report(since: datetime | None, check: bool) -> None:
    """Print the pipeline's completeness and data-quality metrics."""
    start = since.date() if since else _default_backfill_start()
    portal_count = quality.portal_meeting_count(start)

    with db.connect() as conn:
        report = quality.build_report(conn, portal_count)

    click.echo(report.format())

    if check:
        failures = []
        if report.completeness < 0.95:
            failures.append(f"completeness {report.completeness:.1%} < 95%")
        if report.linkage < 0.90:
            failures.append(f"linkage {report.linkage:.1%} < 90%")
        if report.items_missing_title:
            failures.append(f"{report.items_missing_title} items missing a title")
        for failure in failures:
            click.echo(f"FAIL {failure}", err=True)
        if failures:
            sys.exit(1)


@main.command()
@click.argument("question")
def ask(question: str) -> None:
    """Ask the agent a question about council decisions."""
    from mtl_council_agent.agent.loop import ask as run_agent

    with db.connect() as conn:
        answer = run_agent(conn, question)

    click.echo(answer.text)
    if answer.citations:
        click.echo("\nSources consulted:")
        for citation in answer.citations:
            click.echo(f"  - {citation}")
    click.echo(
        f"\n[{answer.turns} turns, {answer.input_tokens}+{answer.output_tokens} tokens, "
        f"~${answer.estimated_cost_usd():.4f}]",
        err=True,
    )


if __name__ == "__main__":
    main()
