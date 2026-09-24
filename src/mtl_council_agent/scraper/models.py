from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time


@dataclass(frozen=True)
class Fingerprint:
    """What the server says about a PDF's current content, from a HEAD request.

    The portal republishes revised documents at the same URL, so the URL
    alone can't tell an old version from a new one; these headers can.
    """

    etag: str | None
    last_modified: str | None
    content_length: int | None

    @property
    def known(self) -> bool:
        return any(v is not None for v in (self.etag, self.last_modified, self.content_length))


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
