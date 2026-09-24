"""Joins parsed agenda, minutes, and bundle content into one record per agenda item.

Agenda gives the item's title/department; minutes gives who moved/seconded it,
the outcome, and any recorded individual votes; the bundle gives the rich
decision-summary narrative.

Minutes join on (section, item_number, dossier_number). Joining on dossier
alone copied one vote onto two items whenever two agenda items shared a
dossier: in June 2026, 07.07 (a filing, never voted on) showed resolution
CM26 0718, which belongs to 30.19. Item numbers alone aren't enough either,
since the agglomeration-orientation section reuses them.

Bundle summaries stay keyed on dossier alone: two items sharing a dossier
really do share one decision summary.

Items with no dossier number (procedural items like "Période de questions du
public", councillors' motions) join on (section, item_number) and carry no
decision summary.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mtl_council_agent.ingestion.agenda_parser import COUNCIL, AgendaItem
from mtl_council_agent.ingestion.bundle_parser import split_bundle_by_dossier
from mtl_council_agent.ingestion.minutes_parser import MinutesItem, RollCall

# The city council's orientation votes are its position on files going to the
# agglomeration council: 49% of recorded votes in 2026. Whether they belong in
# a city-council-only tool is an open decision, so they are parsed and tagged
# but not attached. Flipping this and re-ingesting is all it takes to enable.
ATTACH_ORIENTATION_VOTES = False


@dataclass
class LinkedItem:
    item_number: str
    title: str
    dossier_number: str | None
    decision_summary: str | None
    motion_number: str | None
    mover: str | None
    seconder: str | None
    vote_outcome: str
    section: str = COUNCIL
    sitting: int | None = None
    dissenters: list[str] = field(default_factory=list)
    abstainers: list[str] = field(default_factory=list)
    roll_call: RollCall | None = None


def _find_minutes(
    agenda_item: AgendaItem,
    exact: dict[tuple, MinutesItem],
    by_number: dict[tuple, MinutesItem],
) -> MinutesItem | None:
    """The minutes entry for an agenda item.

    Falls back to (section, item_number) when one side lacks a dossier -- a
    footer can be stamped without one (June 2026, orientation 20.58) -- but
    never when both carry different dossiers, which is exactly the
    shared-dossier mismatch the full key exists to prevent.
    """
    key = (agenda_item.section, agenda_item.item_number)
    match = exact.get((*key, agenda_item.dossier_number))
    if match:
        return match
    candidate = by_number.get(key)
    if candidate and (candidate.dossier_number is None or agenda_item.dossier_number is None):
        return candidate
    return None


def link_items(
    agenda_items: list[AgendaItem],
    minutes_items: list[MinutesItem],
    bundle_text: str | None,
) -> list[LinkedItem]:
    exact = {(m.section, m.item_number, m.dossier_number): m for m in minutes_items}
    by_number = {(m.section, m.item_number): m for m in minutes_items}
    bundle_by_dossier = split_bundle_by_dossier(bundle_text) if bundle_text else {}

    linked: list[LinkedItem] = []
    for agenda_item in agenda_items:
        minutes_item = None
        if agenda_item.section == COUNCIL or ATTACH_ORIENTATION_VOTES:
            minutes_item = _find_minutes(agenda_item, exact, by_number)
        decision_summary = (
            bundle_by_dossier.get(agenda_item.dossier_number)
            if agenda_item.dossier_number
            else None
        )

        linked.append(
            LinkedItem(
                item_number=agenda_item.item_number,
                title=agenda_item.title,
                dossier_number=agenda_item.dossier_number,
                decision_summary=decision_summary,
                section=agenda_item.section,
                motion_number=minutes_item.motion_number if minutes_item else None,
                mover=minutes_item.mover if minutes_item else None,
                seconder=minutes_item.seconder if minutes_item else None,
                vote_outcome=minutes_item.vote_outcome if minutes_item else "unknown",
                sitting=minutes_item.sitting if minutes_item else None,
                dissenters=minutes_item.dissenters if minutes_item else [],
                abstainers=minutes_item.abstainers if minutes_item else [],
                roll_call=minutes_item.roll_call if minutes_item else None,
            )
        )

    return linked
