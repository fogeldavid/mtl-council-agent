"""Tools the agent can call against the council database.

Hybrid retrieval is deliberate: council text is dense with exact tokens --
dossier numbers, resolution numbers like "CM26 0677", dollar figures, tender
numbers -- that embeddings blur together, while semantic search is what
handles a vague question like "what's happening with bike paths". The agent
gets both and picks.

Every result carries the fields needed to cite it (meeting date, item number,
dossier number), because the answering prompt refuses to state a fact it
can't attribute.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from pgvector import HalfVector

from mtl_council_agent.ingestion.embed import embed_query


@dataclass
class ItemResult:
    item_id: int
    meeting_date: date
    item_number: str
    title: str
    dossier_number: str | None
    motion_number: str | None
    vote_outcome: str | None
    mover: str | None
    seconder: str | None
    excerpt: str | None = None

    def citation(self) -> str:
        parts = [f"{self.meeting_date.isoformat()} item {self.item_number}"]
        if self.motion_number:
            parts.append(self.motion_number)
        if self.dossier_number:
            parts.append(f"dossier {self.dossier_number}")
        return " / ".join(parts)


_ITEM_SELECT = """
    select
        ai.id, m.meeting_date, ai.item_number, ai.title, ai.dossier_number,
        ai.motion_number, ai.vote_outcome, mover.name, seconder.name
    from agenda_items ai
    join meetings m on m.id = ai.meeting_id
    left join officials mover on mover.id = ai.mover_id
    left join officials seconder on seconder.id = ai.seconder_id
"""


def _row_to_item(row, excerpt: str | None = None) -> ItemResult:
    return ItemResult(
        item_id=row[0],
        meeting_date=row[1],
        item_number=row[2],
        title=row[3],
        dossier_number=row[4],
        motion_number=row[5],
        vote_outcome=row[6],
        mover=row[7],
        seconder=row[8],
        excerpt=excerpt,
    )


def semantic_search(conn, query: str, limit: int = 8) -> list[ItemResult]:
    """Meaning-based search over decision-summary chunks.

    Works cross-lingually: an English question matches French passages,
    because both sit in one multilingual embedding space.
    """
    vector = HalfVector(embed_query(query))
    rows = conn.execute(
        """
        with matches as (
            select agenda_item_id, content,
                   embedding <=> %s::halfvec as distance
            from item_chunks
            where embedding is not null
            order by distance
            limit %s
        )
        select distinct on (ai.id)
            ai.id, m.meeting_date, ai.item_number, ai.title, ai.dossier_number,
            ai.motion_number, ai.vote_outcome, mover.name, seconder.name,
            matches.content, matches.distance
        from matches
        join agenda_items ai on ai.id = matches.agenda_item_id
        join meetings m on m.id = ai.meeting_id
        left join officials mover on mover.id = ai.mover_id
        left join officials seconder on seconder.id = ai.seconder_id
        order by ai.id, matches.distance
        """,
        (vector, limit * 3),
    ).fetchall()

    results = [_row_to_item(row, excerpt=row[9]) for row in rows]
    return results[:limit]


def full_text_search(conn, query: str, limit: int = 8) -> list[ItemResult]:
    """Exact-token search -- the right tool for resolution numbers, dossier
    numbers, dollar amounts, and proper nouns that embeddings smear."""
    rows = conn.execute(
        f"""
        {_ITEM_SELECT}
        where ai.search_vector @@ plainto_tsquery('french', %s)
        order by ts_rank(ai.search_vector, plainto_tsquery('french', %s)) desc
        limit %s
        """,
        (query, query, limit),
    ).fetchall()
    return [_row_to_item(row) for row in rows]


def get_meeting_items(conn, meeting_date: date, limit: int = 100) -> list[ItemResult]:
    rows = conn.execute(
        f"{_ITEM_SELECT} where m.meeting_date = %s order by ai.position limit %s",
        (meeting_date, limit),
    ).fetchall()
    return [_row_to_item(row) for row in rows]


def get_item_detail(conn, item_id: int) -> tuple[ItemResult, str | None] | None:
    row = conn.execute(
        f"{_ITEM_SELECT} where ai.id = %s", (item_id,)
    ).fetchone()
    if row is None:
        return None
    summary = conn.execute(
        "select decision_summary from agenda_items where id = %s", (item_id,)
    ).fetchone()[0]
    return _row_to_item(row), summary


def get_official_record(conn, name: str, limit: int = 50) -> list[ItemResult]:
    """Accountability search: everything an elected official moved or seconded.

    Scoped to the officials roster on purpose. Names of residents, staff, and
    contractors that appear inside documents are reachable only through
    full_text_search, so this can't be used to profile a private individual.
    """
    rows = conn.execute(
        f"""
        {_ITEM_SELECT}
        where mover.name ilike %s or seconder.name ilike %s
        order by m.meeting_date desc, ai.position
        limit %s
        """,
        (f"%{name}%", f"%{name}%", limit),
    ).fetchall()
    return [_row_to_item(row) for row in rows]
