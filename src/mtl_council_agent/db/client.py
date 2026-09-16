"""Postgres access layer.

Everything is idempotent on the source URL / natural key so the weekly
ingestion job can re-run over meetings it has already seen without creating
duplicates -- re-running the whole backfill must be safe.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connection_string() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


@contextmanager
def connect():
    with psycopg.connect(connection_string()) as conn:
        register_vector(conn)
        yield conn


def init_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_PATH.read_text())
    conn.commit()


def upsert_meeting(
    conn: psycopg.Connection, meeting_date: date, meeting_type: str, source_url: str
) -> int:
    row = conn.execute(
        """
        insert into meetings (meeting_date, meeting_type, source_url)
        values (%s, %s, %s)
        on conflict (source_url) do update set meeting_date = excluded.meeting_date
        returning id
        """,
        (meeting_date, meeting_type, source_url),
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


def upsert_official(conn: psycopg.Connection, name: str) -> int:
    row = conn.execute(
        """
        insert into officials (name) values (%s)
        on conflict (name) do update set name = excluded.name
        returning id
        """,
        (name,),
    ).fetchone()
    return row[0]


def upsert_agenda_item(
    conn: psycopg.Connection,
    meeting_id: int,
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
            meeting_id, item_number, title, department, decision_summary,
            motion_number, mover_id, seconder_id, vote_outcome, dossier_number
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (meeting_id, item_number) do update set
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
            meeting_id, item_number, title, department, decision_summary,
            motion_number, mover_id, seconder_id, vote_outcome, dossier_number,
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
    for index, (content, embedding) in enumerate(zip(chunks, embeddings)):
        conn.execute(
            """
            insert into item_chunks (agenda_item_id, chunk_index, content, embedding)
            values (%s, %s, %s, %s)
            """,
            (agenda_item_id, index, content, embedding),
        )


def meeting_exists(conn: psycopg.Connection, source_pdf_url: str) -> bool:
    row = conn.execute(
        "select 1 from documents where source_pdf_url = %s", (source_pdf_url,)
    ).fetchone()
    return row is not None
