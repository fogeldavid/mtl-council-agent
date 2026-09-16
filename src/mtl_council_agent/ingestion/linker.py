"""Joins parsed agenda, minutes, and bundle content into one record per agenda item.

Agenda gives the item's title/department; minutes gives who moved/seconded it
and the vote outcome; the bundle gives the rich decision-summary narrative.
The dossier number is the stable key shared across all three documents (item
numbers alone are not globally unique -- they reset per section, and separate
numbering series exist for city-council-only vs. agglomeration-referenced
items -- see minutes_parser for detail on the latter).

Items with no dossier number (procedural items like "Période de questions du
public") are kept with a null decision_summary/vote fields -- they're still
valid rows (an agent might be asked "what's on the agenda", after all), just
thin ones.
"""

from __future__ import annotations

from dataclasses import dataclass

from mtl_council_agent.ingestion.agenda_parser import AgendaItem
from mtl_council_agent.ingestion.bundle_parser import split_bundle_by_dossier
from mtl_council_agent.ingestion.minutes_parser import MinutesItem


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


def link_items(
    agenda_items: list[AgendaItem],
    minutes_items: list[MinutesItem],
    bundle_text: str | None,
) -> list[LinkedItem]:
    minutes_by_dossier = {m.dossier_number: m for m in minutes_items}
    bundle_by_dossier = split_bundle_by_dossier(bundle_text) if bundle_text else {}

    linked: list[LinkedItem] = []
    for agenda_item in agenda_items:
        minutes_item = (
            minutes_by_dossier.get(agenda_item.dossier_number)
            if agenda_item.dossier_number
            else None
        )
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
                motion_number=minutes_item.motion_number if minutes_item else None,
                mover=minutes_item.mover if minutes_item else None,
                seconder=minutes_item.seconder if minutes_item else None,
                vote_outcome=minutes_item.vote_outcome if minutes_item else "unknown",
            )
        )

    return linked
