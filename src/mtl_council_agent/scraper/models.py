from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time


@dataclass
class DocumentRef:
    """A single PDF attached to a meeting, as listed on the legacy portal."""

    doc_type: str  # "bundle" | "agenda" | "minutes" | "other"
    title: str
    url: str


@dataclass
class MeetingRef:
    """One city council meeting as listed on the legacy portal, with its documents."""

    meeting_date: date
    meeting_time: time
    meeting_type: str  # "ordinaire" | "extraordinaire"
    source_url: str
    documents: list[DocumentRef] = field(default_factory=list)

    def document(self, doc_type: str) -> DocumentRef | None:
        return next((d for d in self.documents if d.doc_type == doc_type), None)
