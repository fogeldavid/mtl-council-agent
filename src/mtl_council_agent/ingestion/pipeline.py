"""End-to-end ingestion: portal -> PDFs -> parsed items -> embeddings -> Postgres.

Bundle PDFs reach 515MB each, so they're streamed to a temp file, converted to
text, and deleted before moving on rather than held in memory or kept on disk
across meetings. A two-year backfill moves several GB in total.

Whether a meeting needs (re-)ingesting is decided from HEAD requests alone:
a document is new or revised when its URL is unknown or its ETag changed.
Agendas are revised at the same URL before nearly every meeting, and minutes
appear weeks after it, so both cases have to be caught without downloading
anything that hasn't changed.
"""

from __future__ import annotations

import logging
import tempfile
import time as time_module
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

from mtl_council_agent.db import client as db
from mtl_council_agent.ingestion.agenda_parser import parse_agenda
from mtl_council_agent.ingestion.chunker import chunk_text
from mtl_council_agent.ingestion.embed import embed_passages
from mtl_council_agent.ingestion.linker import link_items
from mtl_council_agent.ingestion.minutes_parser import parse_attendance, parse_minutes
from mtl_council_agent.ingestion.pdf_extract import extract_text, strip_page_artifacts
from mtl_council_agent.scraper.models import Fingerprint, MeetingRef
from mtl_council_agent.scraper.portal_client import fetch_meetings_since, head_document

logger = logging.getLogger(__name__)

INGESTED_TYPES = {"agenda", "minutes", "bundle"}
# Between HEAD requests. They're tiny, but it's the same city server the
# portal client already paces itself against.
HEAD_DELAY_SECONDS = 1


@dataclass
class IngestionResult:
    meetings_seen: int = 0
    meetings_ingested: int = 0
    items_loaded: int = 0
    chunks_embedded: int = 0
    unresolved_voters: int = 0
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
        return strip_page_artifacts(extract_text(Path(tmp.name)))


def _fingerprints(http: httpx.Client, meeting: MeetingRef) -> dict[str, Fingerprint]:
    current = {}
    for doc in meeting.documents:
        if doc.doc_type in INGESTED_TYPES:
            current[doc.url] = head_document(http, doc.url)
            time_module.sleep(HEAD_DELAY_SECONDS)
    return current


def _store_votes(conn, item_id: int, item) -> int:
    """Record the item's individual positions; returns how many names failed
    to resolve to an official.

    Roll calls go first: they're complete, and insert_item_vote keeps the
    first record per person.
    """
    unresolved = 0
    if item.roll_call:
        call = item.roll_call
        if (call.declared_for, call.declared_against) != (
            len(call.voted_for),
            len(call.voted_against),
        ):
            # Seen once in 2026 (05-11, item 30.04: 64 names listed, "(62)"
            # declared). The names are what the minutes say; store them and
            # flag the source's arithmetic.
            logger.warning(
                "roll call on item %s lists %d for / %d against but declares %s / %s",
                item.item_number,
                len(call.voted_for),
                len(call.voted_against),
                call.declared_for,
                call.declared_against,
            )
        for position, printed_names in (
            ("for", item.roll_call.voted_for),
            ("against", item.roll_call.voted_against),
        ):
            for printed in printed_names:
                official_id = db.resolve_surname(conn, printed)
                if official_id is None:
                    unresolved += 1
                    logger.warning("roll call name %r matches no single official", printed)
                    continue
                db.insert_item_vote(conn, item_id, official_id, position, "roll_call")
    for name in item.dissenters:
        official_id = db.upsert_official(conn, name)
        db.insert_item_vote(conn, item_id, official_id, "against", "dissent_list")
    for name in item.abstainers:
        official_id = db.upsert_official(conn, name)
        db.insert_item_vote(conn, item_id, official_id, "abstained", "interest_declaration")
    return unresolved


def _store_attendance(conn, meeting_id: int, minutes_text: str) -> None:
    for index, sitting in enumerate(parse_attendance(minutes_text)):
        for status, names in (
            ("present", sitting.present),
            ("absent_excused", sitting.absent_excused),
            ("absent_unexcused", sitting.absent_unexcused),
            ("absent_barred", sitting.absent_barred),
        ):
            for name in names:
                official_id = db.upsert_official(conn, name)
                db.insert_attendance(conn, meeting_id, index, official_id, status)


def ingest_meeting(
    conn,
    http: httpx.Client,
    meeting: MeetingRef,
    fingerprints: dict[str, Fingerprint] | None = None,
) -> tuple[int, int, int]:
    """Load one meeting, replacing whatever version of it was stored.

    Returns (items loaded, chunks embedded, roll-call names left unresolved).
    """
    agenda_doc = meeting.document("agenda")
    minutes_doc = meeting.document("minutes")
    bundle_doc = meeting.document("bundle")

    if agenda_doc is None:
        raise ValueError(f"meeting {meeting.meeting_date} has no agenda document")

    agenda_items = parse_agenda(_download_and_extract(http, agenda_doc.url))
    minutes_text = _download_and_extract(http, minutes_doc.url) if minutes_doc else None
    minutes_items = parse_minutes(minutes_text) if minutes_text else []
    bundle_text = _download_and_extract(http, bundle_doc.url) if bundle_doc else None

    linked = link_items(agenda_items, minutes_items, bundle_text)

    meeting_id = db.upsert_meeting(
        conn,
        meeting.meeting_date,
        meeting.meeting_time,
        meeting.meeting_type,
        meeting.source_url,
    )
    db.replace_meeting_contents(conn, meeting_id)
    fingerprints = fingerprints or {}
    for doc in meeting.documents:
        if doc.doc_type in INGESTED_TYPES:
            db.upsert_document(
                conn, meeting_id, doc.doc_type, doc.url, fingerprints.get(doc.url)
            )
    if minutes_text:
        _store_attendance(conn, meeting_id, minutes_text)

    items_loaded = 0
    chunks_embedded = 0
    unresolved = 0
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
            section=item.section,
            sitting=item.sitting,
        )
        items_loaded += 1
        unresolved += _store_votes(conn, item_id, item)

        embeddable = item.decision_summary or item.title
        chunks = chunk_text(embeddable)
        if chunks:
            db.replace_item_chunks(conn, item_id, chunks, embed_passages(chunks))
            chunks_embedded += len(chunks)

    conn.commit()
    return items_loaded, chunks_embedded, unresolved


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
            try:
                fingerprints = _fingerprints(http, meeting)
                if skip_existing:
                    changed = db.changed_documents(conn, fingerprints)
                    if not changed:
                        logger.info("up to date, skipping %s", meeting.meeting_date)
                        continue
                    logger.info(
                        "ingesting %s: %d new or revised document(s)",
                        meeting.meeting_date,
                        len(changed),
                    )
                items, chunks, unresolved = ingest_meeting(conn, http, meeting, fingerprints)
            except Exception as exc:  # keep going; one bad meeting shouldn't stop a backfill
                conn.rollback()
                logger.exception("failed to ingest %s", meeting.meeting_date)
                result.failures.append(f"{meeting.meeting_date}: {exc}")
                continue

            result.meetings_ingested += 1
            result.items_loaded += items
            result.chunks_embedded += chunks
            result.unresolved_voters += unresolved
            logger.info(
                "ingested %s: %d items, %d chunks", meeting.meeting_date, items, chunks
            )

    return result
