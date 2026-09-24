"""Postgres access layer.

Everything is idempotent on the source URL / natural key so the weekly
ingestion job can re-run over meetings it has already seen without creating
duplicates -- re-running the whole backfill must be safe. A meeting that is
re-ingested is replaced wholesale (see replace_meeting_contents), not
patched row by row.
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
from mtl_council_agent.scraper.models import Fingerprint

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
    conn: psycopg.Connection,
    meeting_id: int,
    doc_type: str,
    source_pdf_url: str,
    fingerprint: Fingerprint | None = None,
) -> int:
    fp = fingerprint or Fingerprint(None, None, None)
    row = conn.execute(
        """
        insert into documents
            (meeting_id, doc_type, source_pdf_url, etag, last_modified, content_length)
        values (%s, %s, %s, %s, %s, %s)
        on conflict (source_pdf_url) do update set
            meeting_id = excluded.meeting_id,
            doc_type = excluded.doc_type,
            etag = excluded.etag,
            last_modified = excluded.last_modified,
            content_length = excluded.content_length,
            ingested_at = now()
        returning id
        """,
        (meeting_id, doc_type, source_pdf_url, fp.etag, fp.last_modified, fp.content_length),
    ).fetchone()
    return row[0]


def replace_meeting_contents(conn: psycopg.Connection, meeting_id: int) -> None:
    """Clear a meeting's items and attendance before loading its new version.

    A revised agenda inserts and withdraws items mid-list. Upserting by
    position would hand existing row ids to different items and leave the old
    tail behind, so the meeting is emptied and reloaded instead. Chunks and
    votes go with their items (on delete cascade). Runs inside the caller's
    transaction, so a failed re-ingest leaves the previous version intact.
    """
    conn.execute("delete from agenda_items where meeting_id = %s", (meeting_id,))
    conn.execute("delete from meeting_attendance where meeting_id = %s", (meeting_id,))


def upsert_official(conn: psycopg.Connection, raw_name: str) -> int:
    """Resolve a name from the minutes to one official, creating it if new.

    Looks up by normalized key first, then against the roster's own name
    split, then falls back to a near-identical match so a misspelling in the
    source doesn't split someone's record. Only genuinely new people are
    inserted, which also stops the id sequence advancing on every mover and
    seconder the pipeline reads.
    """
    key = names.normalized_name(raw_name)

    row = conn.execute(
        "select id from officials where normalized_name = %s", (key,)
    ).fetchone()
    if row:
        _record_alias(conn, row[0], raw_name, key, "normalized", None)
        return row[0]

    roster_id = _roster_match(conn, key)
    if roster_id is not None:
        _record_alias(conn, roster_id, raw_name, key, "roster", None)
        return roster_id

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


def _roster_match(conn: psycopg.Connection, key: str) -> int | None:
    """The roster member whose surname ends the name and whose given names
    include its first word, if exactly one qualifies.

    The roster records full given names that the minutes shorten: roster
    "Alba Stella Zuniga Ramos" is "Alba Zuniga Ramos" in every roll call, and
    "Dimitrios (Jim) Beis" moves items as "Jim Beis". Those score far below
    the similarity threshold, so without this they'd each become a second,
    phantom official.
    """
    rows = conn.execute(
        "select id, first_name, last_name from officials where last_name is not null"
    ).fetchall()
    candidates = [
        official_id
        for official_id, first_name, last_name in rows
        if names.matches_roster_entry(key, first_name, last_name)
    ]
    return candidates[0] if len(candidates) == 1 else None


def resolve_surname(conn: psycopg.Connection, printed: str) -> int | None:
    """The official a roll-call entry names, or None if it can't be pinned down.

    Roll calls list members by surname ("Pinard", "V. Doyon", "Hénault" --
    distinct from "Hénault-Ratelle"), except the mayor, who gets her full
    name. A surname resolves only if exactly one roster member has it. This
    never creates an official: a surname alone isn't enough to make one.
    """
    key = names.normalized_name(printed)
    rows = conn.execute(
        "select id from officials where normalized_name = %s", (key,)
    ).fetchall()
    if len(rows) == 1:
        return rows[0][0]
    rows = conn.execute(
        "select id, last_name from officials where last_name is not null"
    ).fetchall()
    matches = [i for i, last in rows if names.normalized_name(last) == key]
    if len(matches) == 1:
        return matches[0]
    return _roster_match(conn, key)


def upsert_roster_official(
    conn: psycopg.Connection,
    first_name: str,
    last_name: str,
    role: str,
    borough: str | None,
    district: str | None,
    party: str | None,
) -> int:
    """Load one roster member, merging into an official the minutes created.

    Goes through the same resolution as a name from the minutes, so a
    councillor already on file under a shortened name gets the roster's
    details rather than a duplicate row.
    """
    full = f"{first_name} {last_name}"
    key = names.normalized_name(full)
    row = conn.execute("select id from officials where normalized_name = %s", (key,)).fetchone()
    if row is None:
        existing = conn.execute("select normalized_name, id from officials").fetchall()
        match = names.closest_match(key, [n for n, _ in existing])
        if match is None:
            # A shortened name the minutes created before the roster loaded.
            shortened = [
                n for n, _ in existing if names.matches_roster_entry(n, first_name, last_name)
            ]
            match = (shortened[0], 1.0) if len(shortened) == 1 else None
        row = (dict(existing)[match[0]],) if match else None
    if row is None:
        row = conn.execute(
            "insert into officials (name, normalized_name) values (%s, %s) returning id",
            (names.display_name(full), key),
        ).fetchone()
    official_id = row[0]
    conn.execute(
        """
        update officials set
            first_name = %s, last_name = %s, role = %s,
            borough = %s, district = %s, party = %s
        where id = %s
        """,
        (first_name, last_name, role, borough, district, party, official_id),
    )
    _record_alias(conn, official_id, full, key, "roster", None)
    return official_id


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
    section: str = "council",
    sitting: int | None = None,
) -> int:
    row = conn.execute(
        """
        insert into agenda_items (
            meeting_id, position, item_number, title, department,
            decision_summary, motion_number, mover_id, seconder_id,
            vote_outcome, dossier_number, section, sitting
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (meeting_id, position) do update set
            item_number = excluded.item_number,
            title = excluded.title,
            department = excluded.department,
            decision_summary = excluded.decision_summary,
            motion_number = excluded.motion_number,
            mover_id = excluded.mover_id,
            seconder_id = excluded.seconder_id,
            vote_outcome = excluded.vote_outcome,
            dossier_number = excluded.dossier_number,
            section = excluded.section,
            sitting = excluded.sitting
        returning id
        """,
        (
            meeting_id, position, item_number, title, department,
            decision_summary, motion_number, mover_id, seconder_id,
            vote_outcome, dossier_number, section, sitting,
        ),
    ).fetchone()
    return row[0]


def insert_attendance(
    conn: psycopg.Connection, meeting_id: int, sitting: int, official_id: int, status: str
) -> None:
    conn.execute(
        """
        insert into meeting_attendance (meeting_id, sitting, official_id, status)
        values (%s, %s, %s, %s)
        on conflict (meeting_id, sitting, official_id) do update set status = excluded.status
        """,
        (meeting_id, sitting, official_id, status),
    )


def insert_item_vote(
    conn: psycopg.Connection, agenda_item_id: int, official_id: int, position: str, source: str
) -> None:
    """Record one individual position. The first record for a person wins:
    callers insert roll calls first, since they're the most complete source."""
    conn.execute(
        """
        insert into item_votes (agenda_item_id, official_id, position, source)
        values (%s, %s, %s, %s)
        on conflict (agenda_item_id, official_id) do nothing
        """,
        (agenda_item_id, official_id, position, source),
    )


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


def changed_documents(
    conn: psycopg.Connection, current: dict[str, Fingerprint]
) -> list[str]:
    """Which of the portal's current documents for a meeting are new or revised.

    Minutes are published weeks after the meeting they record, and agendas are
    revised in place at the same URL, so neither "have we seen this meeting"
    nor "have we seen this URL" is enough. A document counts as changed when
    its URL is new, or when the server's ETag differs from the stored one.
    Where the server sends no ETag, Last-Modified and length stand in.
    """
    if not current:
        return []
    rows = conn.execute(
        """
        select source_pdf_url, etag, last_modified, content_length
        from documents where source_pdf_url = any(%s)
        """,
        (list(current),),
    ).fetchall()
    stored = {url: Fingerprint(etag, modified, length) for url, etag, modified, length in rows}

    changed = []
    for url, fp in current.items():
        held = stored.get(url)
        if held is None:
            changed.append(url)
        elif not fp.known:
            continue  # nothing to compare against; the URL is known, keep it
        elif fp.etag and held.etag:
            if fp.etag != held.etag:
                changed.append(url)
        elif (fp.last_modified, fp.content_length) != (held.last_modified, held.content_length):
            changed.append(url)
    return changed
