"""Data-quality and completeness metrics for the ingestion pipeline.

These are the pipeline's stated success criteria, computed from the database
so they can be printed into the README or asserted in CI rather than eyeballed:

  completeness  -- share of meetings published on the portal that we hold
  linkage       -- share of items carrying the decision summary they should
  text_quality  -- share of items with non-empty title and embedded chunks
  outcomes      -- share of council items, in meetings whose minutes are in,
                   that carry an outcome
  roster        -- every official named in the minutes is on the City roster
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
    officials_total: int = 0
    # Pairs of officials whose names nearly matched: either a misspelling the
    # merge threshold refused, or two genuinely similar people. Both want a
    # human's eye, so they surface here rather than being discovered later in
    # a split voting record.
    official_near_duplicates: list[tuple[str, str, float]] = None
    # Named in the minutes but not matched to the roster: a new councillor
    # (by-election), a stale roster, or a name the matcher missed.
    officials_off_roster: list[str] = None
    council_items_in_minuted_meetings: int = 0
    council_items_with_outcome: int = 0
    meetings_with_attendance: int = 0
    recorded_votes: int = 0

    def __post_init__(self):
        if self.official_near_duplicates is None:
            self.official_near_duplicates = []
        if self.officials_off_roster is None:
            self.officials_off_roster = []

    @property
    def outcome_coverage(self) -> float:
        if not self.council_items_in_minuted_meetings:
            return 0.0
        return self.council_items_with_outcome / self.council_items_in_minuted_meetings

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
                (
                    f"decision linkage:    {self.linkage:.1%} "
                    f"({self.items_with_summary}/{self.items_with_dossier} dossier items)"
                ),
                (
                    f"embedded text:       {self.text_quality:.1%} "
                    f"({self.items_with_chunks}/{self.items_total} items)"
                ),
                f"items missing title: {self.items_missing_title}",
                (
                    f"outcome coverage:    {self.outcome_coverage:.1%} "
                    f"({self.council_items_with_outcome}/"
                    f"{self.council_items_in_minuted_meetings} council items with minutes)"
                ),
                f"attendance recorded: {self.meetings_with_attendance} meetings",
                f"recorded positions:  {self.recorded_votes}",
                f"officials:           {self.officials_total}",
            ]
            + (
                [
                    "officials not on the roster (review these):",
                    *(f"  {name}" for name in self.officials_off_roster),
                ]
                if self.officials_off_roster
                else []
            )
            + (
                [
                    "near-duplicate officials (review these):",
                    *(
                        f"  {a!r} ~ {b!r} ({score:.3f})"
                        for a, b, score in self.official_near_duplicates
                    ),
                ]
                if self.official_near_duplicates
                else []
            )
        )


def build_report(conn, meetings_on_portal: int, since: date | None = None) -> QualityReport:
    def scalar(sql: str) -> int:
        return conn.execute(sql).fetchone()[0]

    # Completeness compares the portal against the database over the same
    # window. Counting every ingested meeting against a windowed portal
    # listing reports more than 100% and means nothing.
    if since is None:
        ingested = scalar("select count(*) from meetings")
    else:
        ingested = conn.execute(
            "select count(*) from meetings where meeting_date >= %s", (since,)
        ).fetchone()[0]

    return QualityReport(
        meetings_on_portal=meetings_on_portal,
        meetings_ingested=ingested,
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
        officials_total=scalar("select count(*) from officials"),
        official_near_duplicates=_near_duplicate_officials(conn),
        officials_off_roster=[
            r[0]
            for r in conn.execute(
                "select name from officials where role is null order by name"
            ).fetchall()
        ],
        council_items_in_minuted_meetings=scalar(_MINUTED_COUNCIL_ITEMS),
        council_items_with_outcome=scalar(
            _MINUTED_COUNCIL_ITEMS + " and ai.vote_outcome <> 'unknown'"
        ),
        meetings_with_attendance=scalar(
            "select count(distinct meeting_id) from meeting_attendance"
        ),
        recorded_votes=scalar("select count(*) from item_votes"),
    )


# Council items in meetings whose minutes have been ingested. Orientation
# items are excluded because their outcomes are deliberately not attached,
# and meetings without minutes can't have outcomes yet.
_MINUTED_COUNCIL_ITEMS = """
    select count(*) from agenda_items ai
    where ai.section = 'council'
      and exists (
          select 1 from documents d
          where d.meeting_id = ai.meeting_id and d.doc_type = 'minutes'
      )
"""


def _near_duplicate_officials(conn) -> list[tuple[str, str, float]]:
    from itertools import combinations

    from mtl_council_agent.names import near_miss

    roster = [
        r[0] for r in conn.execute("select normalized_name from officials").fetchall()
    ]
    flagged = []
    for a, b in combinations(roster, 2):
        match = near_miss(a, [b])
        if match:
            flagged.append((a, b, match[1]))
    return sorted(flagged, key=lambda f: -f[2])


def portal_meeting_count(since: date) -> int:
    from mtl_council_agent.scraper.portal_client import fetch_meetings_since

    return len(fetch_meetings_since(since))
