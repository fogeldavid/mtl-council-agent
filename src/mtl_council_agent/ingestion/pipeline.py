"""End-to-end ingestion: portal -> PDFs -> parsed items -> embeddings -> Postgres.

Bundle PDFs reach 515MB each, so they're streamed to a temp file, converted to
text, and deleted before moving on rather than held in memory or kept on disk
across meetings. A two-year backfill moves several GB in total.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

from mtl_council_agent.db import client as db
from mtl_council_agent.ingestion.agenda_parser import parse_agenda
from mtl_council_agent.ingestion.chunker import chunk_text
from mtl_council_agent.ingestion.embed import embed_passages
from mtl_council_agent.ingestion.linker import link_items
from mtl_council_agent.ingestion.minutes_parser import parse_minutes
from mtl_council_agent.ingestion.pdf_extract import extract_text
from mtl_council_agent.scraper.models import MeetingRef
from mtl_council_agent.scraper.portal_client import fetch_meetings_since

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    meetings_seen: int = 0
    meetings_ingested: int = 0
    items_loaded: int = 0
    chunks_embedded: int = 0
    failures: list[str] = None

    def __post_init__(self):
        if self.failures is None:
            self.failures = []


def _download_and_extract(client: httpx.Client, url: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        with client.stream("GET", url, follow_redirects=True, timeout=300) as response:
            response.raise_for_status()
            for block in response.iter_bytes(chunk_size=1 << 20):
                tmp.write(block)
        tmp.flush()
        return extract_text(Path(tmp.name))


def ingest_meeting(conn, http: httpx.Client, meeting: MeetingRef) -> tuple[int, int]:
    agenda_doc = meeting.document("agenda")
    minutes_doc = meeting.document("minutes")
    bundle_doc = meeting.document("bundle")

    if agenda_doc is None:
        raise ValueError(f"meeting {meeting.meeting_date} has no agenda document")

    agenda_items = parse_agenda(_download_and_extract(http, agenda_doc.url))
    minutes_items = (
        parse_minutes(_download_and_extract(http, minutes_doc.url)) if minutes_doc else []
    )
    bundle_text = _download_and_extract(http, bundle_doc.url) if bundle_doc else None

    linked = link_items(agenda_items, minutes_items, bundle_text)

    meeting_id = db.upsert_meeting(
        conn,
        meeting.meeting_date,
        meeting.meeting_time,
        meeting.meeting_type,
        meeting.source_url,
    )
    for doc in meeting.documents:
        if doc.doc_type in {"agenda", "minutes", "bundle"}:
            db.upsert_document(conn, meeting_id, doc.doc_type, doc.url)

    items_loaded = 0
    chunks_embedded = 0
    for position, item in enumerate(linked):
        mover_id = db.upsert_official(conn, item.mover) if item.mover else None
        seconder_id = db.upsert_official(conn, item.seconder) if item.seconder else None

        item_id = db.upsert_agenda_item(
            conn,
            meeting_id=meeting_id,
            position=position,
            item_number=item.item_number,
            title=item.title,
            department=None,
            decision_summary=item.decision_summary,
            motion_number=item.motion_number,
            mover_id=mover_id,
            seconder_id=seconder_id,
            vote_outcome=item.vote_outcome,
            dossier_number=item.dossier_number,
        )
        items_loaded += 1

        embeddable = item.decision_summary or item.title
        chunks = chunk_text(embeddable)
        if chunks:
            db.replace_item_chunks(conn, item_id, chunks, embed_passages(chunks))
            chunks_embedded += len(chunks)

    conn.commit()
    return items_loaded, chunks_embedded


def run_ingestion(since: date, skip_existing: bool = True) -> IngestionResult:
    result = IngestionResult()

    with httpx.Client() as http, db.connect() as conn:
        db.init_schema(conn)
        meetings = fetch_meetings_since(since, client=http)
        result.meetings_seen = len(meetings)

        for meeting in meetings:
            agenda_doc = meeting.document("agenda")
            if agenda_doc is None:
                result.failures.append(f"{meeting.meeting_date}: no agenda document")
                continue
            if skip_existing:
                listed = [
                    d.url
                    for d in meeting.documents
                    if d.doc_type in {"agenda", "minutes", "bundle"}
                ]
                missing = db.missing_documents(conn, listed)
                if not missing:
                    logger.info("up to date, skipping %s", meeting.meeting_date)
                    continue
                logger.info(
                    "re-ingesting %s: %d new document(s) published since last run",
                    meeting.meeting_date,
                    len(missing),
                )

            try:
                items, chunks = ingest_meeting(conn, http, meeting)
            except Exception as exc:  # keep going; one bad meeting shouldn't stop a backfill
                conn.rollback()
                logger.exception("failed to ingest %s", meeting.meeting_date)
                result.failures.append(f"{meeting.meeting_date}: {exc}")
                continue

            result.meetings_ingested += 1
            result.items_loaded += items
            result.chunks_embedded += chunks
            logger.info(
                "ingested %s: %d items, %d chunks", meeting.meeting_date, items, chunks
            )

    return result
