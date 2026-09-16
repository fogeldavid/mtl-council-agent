"""Data-quality and completeness metrics for the ingestion pipeline.

These are the pipeline's stated success criteria, computed from the database
so they can be printed into the README or asserted in CI rather than eyeballed:

  completeness  -- share of meetings published on the portal that we hold
  linkage       -- share of items carrying the decision summary they should
  text_quality  -- share of items with non-empty title and embedded chunks
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class QualityReport:
    meetings_on_portal: int
    meetings_ingested: int
    items_total: int
    items_with_dossier: int
    items_with_summary: int
    items_with_chunks: int
    items_missing_title: int

    @property
    def completeness(self) -> float:
        if not self.meetings_on_portal:
            return 0.0
        return self.meetings_ingested / self.meetings_on_portal

    @property
    def linkage(self) -> float:
        """Of items that *should* have a decision summary (those with a
        dossier number), how many actually got one. Procedural items without
        a dossier are excluded rather than counted as failures."""
        if not self.items_with_dossier:
            return 0.0
        return self.items_with_summary / self.items_with_dossier

    @property
    def text_quality(self) -> float:
        if not self.items_total:
            return 0.0
        return self.items_with_chunks / self.items_total

    def format(self) -> str:
        return "\n".join(
            [
                f"meetings on portal:  {self.meetings_on_portal}",
                f"meetings ingested:   {self.meetings_ingested}",
                f"completeness:        {self.completeness:.1%}",
                f"items loaded:        {self.items_total}",
                f"decision linkage:    {self.linkage:.1%} "
                f"({self.items_with_summary}/{self.items_with_dossier} dossier items)",
                f"embedded text:       {self.text_quality:.1%} "
                f"({self.items_with_chunks}/{self.items_total} items)",
                f"items missing title: {self.items_missing_title}",
            ]
        )


def build_report(conn, meetings_on_portal: int) -> QualityReport:
    def scalar(sql: str) -> int:
        return conn.execute(sql).fetchone()[0]

    return QualityReport(
        meetings_on_portal=meetings_on_portal,
        meetings_ingested=scalar("select count(*) from meetings"),
        items_total=scalar("select count(*) from agenda_items"),
        items_with_dossier=scalar(
            "select count(*) from agenda_items where dossier_number is not null"
        ),
        items_with_summary=scalar(
            "select count(*) from agenda_items "
            "where dossier_number is not null and decision_summary is not null"
        ),
        items_with_chunks=scalar(
            "select count(distinct agenda_item_id) from item_chunks"
        ),
        items_missing_title=scalar(
            "select count(*) from agenda_items where title is null or btrim(title) = ''"
        ),
    )


def portal_meeting_count(since: date) -> int:
    from mtl_council_agent.scraper.portal_client import fetch_meetings_since

    return len(fetch_meetings_since(since))
