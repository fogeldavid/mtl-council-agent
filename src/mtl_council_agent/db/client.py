"""Postgres access layer.

Everything is idempotent on the source URL / natural key so the weekly
ingestion job can re-run over meetings it has already seen without creating
duplicates -- re-running the whole backfill must be safe.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, time
from pathlib import Path

import psycopg
from pgvector import HalfVector
from pgvector.psycopg import register_vector

from mtl_council_agent import names

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connection_string() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


@contextmanager
def connect():
    with psycopg.connect(connection_string()) as conn:
        # The extension has to exist before the type adapter can be registered,
        # otherwise a fresh database can never be bootstrapped: registration
        # fails, so init_schema never gets a chance to create the extension.
        conn.execute("create extension if not exists vector")
        conn.commit()
        register_vector(conn)
        yield conn


def init_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_PATH.read_text())
    conn.commit()


def upsert_meeting(
    conn: psycopg.Connection,
    meeting_date: date,
    meeting_time: time,
    meeting_type: str,
    source_url: str,
) -> int:
    row = conn.execute(
        """
        insert into meetings (meeting_date, meeting_time, meeting_type, source_url)
        values (%s, %s, %s, %s)
        on conflict (meeting_date, meeting_time, meeting_type) do update
            set source_url = excluded.source_url
        returning id
        """,
        (meeting_date, meeting_time, meeting_type, source_url),
    ).fetchone()
    return row[0]


def upsert_document(
    conn: psycopg.Connection, meeting_id: int, doc_type: str, source_pdf_url: str
) -> int:
    row = conn.execute(
        """
        insert into documents (meeting_id, doc_type, source_pdf_url)
        values (%s, %s, %s)
        on conflict (source_pdf_url) do update set ingested_at = now()
        returning id
        """,
        (meeting_id, doc_type, source_pdf_url),
    ).fetchone()
    return row[0]


def upsert_official(conn: psycopg.Connection, raw_name: str) -> int:
    """Resolve a name from the minutes to one official, creating it if new.

    Looks up by normalized key first, then falls back to a near-identical
    match so a misspelling in the source doesn't split someone's record.
    Only genuinely new people are inserted, which also stops the id sequence
    advancing on every mover and seconder the pipeline reads.
    """
    key = names.normalized_name(raw_name)

    row = conn.execute(
        "select id from officials where normalized_name = %s", (key,)
    ).fetchone()
    if row:
        _record_alias(conn, row[0], raw_name, key, "normalized", None)
        return row[0]

    existing = conn.execute("select normalized_name, id from officials").fetchall()
    match = names.closest_match(key, [n for n, _ in existing])
    if match:
        matched_name, score = match
        official_id = dict(existing)[matched_name]
        _record_alias(conn, official_id, raw_name, key, "similarity", score)
        return official_id

    row = conn.execute(
        """
        insert into officials (name, normalized_name) values (%s, %s)
        on conflict (normalized_name) do update set name = officials.name
        returning id
        """,
        (names.display_name(raw_name), key),
    ).fetchone()
    _record_alias(conn, row[0], raw_name, key, "new", None)
    return row[0]


def _record_alias(
    conn: psycopg.Connection,
    official_id: int,
    raw_name: str,
    key: str,
    matched_by: str,
    similarity: float | None,
) -> None:
    conn.execute(
        """
        insert into official_aliases
            (official_id, raw_name, normalized_name, matched_by, similarity)
        values (%s, %s, %s, %s, %s)
        on conflict (raw_name) do update
            set times_seen = official_aliases.times_seen + 1
        """,
        (official_id, raw_name.strip(), key, matched_by, similarity),
    )


def upsert_agenda_item(
    conn: psycopg.Connection,
    meeting_id: int,
    position: int,
    item_number: str,
    title: str,
    department: str | None,
    decision_summary: str | None,
    motion_number: str | None,
    mover_id: int | None,
    seconder_id: int | None,
    vote_outcome: str,
    dossier_number: str | None,
) -> int:
    row = conn.execute(
        """
        insert into agenda_items (
            meeting_id, position, item_number, title, department,
            decision_summary, motion_number, mover_id, seconder_id,
            vote_outcome, dossier_number
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (meeting_id, position) do update set
            item_number = excluded.item_number,
            title = excluded.title,
            department = excluded.department,
            decision_summary = excluded.decision_summary,
            motion_number = excluded.motion_number,
            mover_id = excluded.mover_id,
            seconder_id = excluded.seconder_id,
            vote_outcome = excluded.vote_outcome,
            dossier_number = excluded.dossier_number
        returning id
        """,
        (
            meeting_id, position, item_number, title, department,
            decision_summary, motion_number, mover_id, seconder_id,
            vote_outcome, dossier_number,
        ),
    ).fetchone()
    return row[0]


def replace_item_chunks(
    conn: psycopg.Connection,
    agenda_item_id: int,
    chunks: list[str],
    embeddings: list[list[float]],
) -> None:
    conn.execute("delete from item_chunks where agenda_item_id = %s", (agenda_item_id,))
    # strict=True: a length mismatch means the embedder dropped something, and
    # silently storing the shorter list would lose chunks without any error.
    for index, (content, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
        conn.execute(
            """
            insert into item_chunks (agenda_item_id, chunk_index, content, embedding)
            values (%s, %s, %s, %s)
            """,
            (agenda_item_id, index, content, HalfVector(embedding)),
        )


def missing_documents(conn: psycopg.Connection, urls: list[str]) -> list[str]:
    """Which of the portal's current documents for a meeting we don't hold.

    Minutes are published weeks after the meeting they record, so a meeting
    already ingested from its agenda is not finished with. Deciding to skip
    on the agenda alone meant a meeting was visited once and never revisited,
    and its votes stayed unknown forever.
    """
    if not urls:
        return []
    rows = conn.execute(
        "select source_pdf_url from documents where source_pdf_url = any(%s)", (urls,)
    ).fetchall()
    held = {r[0] for r in rows}
    return [u for u in urls if u not in held]
