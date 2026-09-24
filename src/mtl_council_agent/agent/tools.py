"""Tools the agent can call against the council database.

Hybrid retrieval is deliberate: council text is dense with exact tokens --
dossier numbers, resolution numbers like "CM26 0677", dollar figures, tender
numbers -- that embeddings blur together, while semantic search is what
handles a vague question like "what's happening with bike paths". The agent
gets both and picks.

Every result carries the fields needed to cite it (meeting date, item number,
dossier number), because the answering prompt refuses to state a fact it
can't attribute.

Individual votes come in two kinds and are never mixed up. A RECORDED
position is one the minutes name: a roll call, a dissent list, a declared
conflict of interest. An INFERRED "for" is derived: everyone present at the
sitting minus recorded dissenters and abstainers, and only where that is
sound -- an unanimous vote, or a majority vote whose dissenters are named. A
majority vote without names attributes nobody.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    section: str = "council"
    # How a named official was involved, for get_official_record results.
    involvement: list[str] = field(default_factory=list)
    # A one-line digest of recorded individual votes, for meeting listings.
    recorded_votes: str | None = None

    @property
    def display_number(self) -> str:
        """The item number as the minutes print it: orientation items are
        "80.01 (20.01)", since 20.01 alone also names a council item."""
        if self.section == "agglomeration_orientation":
            return f"80.01 ({self.item_number})"
        return self.item_number

    def citation(self) -> str:
        parts = [f"{self.meeting_date.isoformat()} item {self.display_number}"]
        if self.motion_number:
            parts.append(self.motion_number)
        if self.dossier_number:
            parts.append(f"dossier {self.dossier_number}")
        return " / ".join(parts)


_ITEM_SELECT = """
    select
        ai.id, m.meeting_date, ai.item_number, ai.title, ai.dossier_number,
        ai.motion_number, ai.vote_outcome, mover.name, seconder.name, ai.section
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
        section=row[9],
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
            ai.motion_number, ai.vote_outcome, mover.name, seconder.name, ai.section,
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

    results = [_row_to_item(row, excerpt=row[10]) for row in rows]
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


def get_meeting_items(conn, meeting_date: date, limit: int = 300) -> list[ItemResult]:
    """Every item on one meeting's agenda, in running order.

    The limit has to clear the largest real agenda (249 items) or the model
    silently receives a partial list and answers "what was on the agenda" as
    though it were complete.
    """
    rows = conn.execute(
        f"{_ITEM_SELECT} where m.meeting_date = %s order by ai.position limit %s",
        (meeting_date, limit),
    ).fetchall()
    items = [_row_to_item(row) for row in rows]
    digests = _recorded_vote_digests(conn, [item.item_id for item in items])
    for item in items:
        item.recorded_votes = digests.get(item.item_id)
    return items


def _recorded_vote_digests(conn, item_ids: list[int]) -> dict[int, str]:
    """A short note per item that has recorded individual votes.

    Without it, "who declared a conflict of interest at this meeting" meant
    opening every one of 121 items; the agent gave up partway and answered
    that nobody had. Only a handful of items per meeting carry recorded
    votes, so the listing stays compact.
    """
    if not item_ids:
        return {}
    rows = conn.execute(
        """
        select v.agenda_item_id,
               count(*) filter (where v.source = 'roll_call' and v.position = 'for'),
               count(*) filter (where v.source = 'roll_call' and v.position = 'against'),
               array_agg(o.name order by o.name) filter (where v.source = 'dissent_list'),
               array_agg(o.name order by o.name) filter (where v.position = 'abstained')
        from item_votes v join officials o on o.id = v.official_id
        where v.agenda_item_id = any(%s)
        group by v.agenda_item_id
        """,
        (item_ids,),
    ).fetchall()
    digests = {}
    for item_id, roll_for, roll_against, dissenters, abstainers in rows:
        parts = []
        if roll_for or roll_against:
            parts.append(f"roll call: {roll_for} for, {roll_against} against")
        if dissenters:
            parts.append(f"recorded dissent: {len(dissenters)} members")
        if abstainers:
            parts.append("declared conflict of interest, abstained: " + ", ".join(abstainers))
        digests[item_id] = "; ".join(parts)
    return digests


@dataclass
class VoteDetail:
    """Who did what on one item, keeping recorded and inferred apart."""

    outcome: str | None
    recorded_for: list[str] = field(default_factory=list)
    recorded_against: list[str] = field(default_factory=list)
    recorded_abstained: list[str] = field(default_factory=list)
    recorded_by: list[str] = field(default_factory=list)
    present_at_sitting: int | None = None
    inferred_for: list[str] | None = None
    note: str = ""


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


def get_vote_detail(conn, item_id: int) -> VoteDetail:
    """The item's outcome and every individual position the records support."""
    item = conn.execute(
        "select vote_outcome, meeting_id, sitting from agenda_items where id = %s", (item_id,)
    ).fetchone()
    if item is None:
        return VoteDetail(outcome=None)
    outcome, meeting_id, sitting = item

    detail = VoteDetail(outcome=outcome)
    votes = conn.execute(
        """
        select o.name, v.position, v.source
        from item_votes v join officials o on o.id = v.official_id
        where v.agenda_item_id = %s
        order by o.name
        """,
        (item_id,),
    ).fetchall()
    for name, position, source in votes:
        {
            "for": detail.recorded_for,
            "against": detail.recorded_against,
            "abstained": detail.recorded_abstained,
        }[position].append(name)
        if source not in detail.recorded_by:
            detail.recorded_by.append(source)

    present = []
    if sitting is not None:
        present = [
            r[0]
            for r in conn.execute(
                """
                select o.name
                from meeting_attendance a join officials o on o.id = a.official_id
                where a.meeting_id = %s and a.sitting = %s and a.status = 'present'
                order by o.name
                """,
                (meeting_id, sitting),
            ).fetchall()
        ]
        detail.present_at_sitting = len(present)

    if "roll_call" in detail.recorded_by:
        detail.note = "Roll-call vote: every position listed is recorded in the minutes."
    elif outcome == "adopted_unanimous" and present:
        excluded = set(detail.recorded_abstained)
        detail.inferred_for = [n for n in present if n not in excluded]
        detail.note = (
            "Adopted unanimously. The minutes name no individual votes; inferred_for is "
            "everyone recorded present at that sitting minus declared abstentions."
        )
    elif outcome == "adopted_majority" and detail.recorded_against and present:
        excluded = set(detail.recorded_against) | set(detail.recorded_abstained)
        detail.inferred_for = [n for n in present if n not in excluded]
        detail.note = (
            "Adopted by majority with a recorded dissent list; inferred_for is everyone "
            "present at that sitting minus the named dissenters and abstentions."
        )
    elif outcome == "adopted_majority":
        detail.note = (
            "Adopted by majority, but the minutes do not name who voted against, so no "
            "councillor can be attributed a position on this item."
        )
    elif outcome in (None, "unknown"):
        detail.note = "No outcome on file (minutes not published yet, or not covered)."
    return detail


@dataclass
class OfficialProfile:
    name: str
    role: str | None
    borough: str | None
    district: str | None
    party: str | None
    sittings_present: int
    sittings_absent: int


def match_officials(conn, name: str) -> list[str]:
    """Every official a name fragment matches. More than one means the
    record below merges people ("Hénault" is Andrée Hénault and Julien
    Hénault-Ratelle), which the model must see to ask or narrow down."""
    return [
        r[0]
        for r in conn.execute(
            "select name from officials where name ilike %s order by name", (f"%{name}%",)
        ).fetchall()
    ]


def get_official_profile(conn, name: str) -> OfficialProfile | None:
    row = conn.execute(
        """
        select o.id, o.name, o.role, o.borough, o.district, o.party
        from officials o
        where o.name ilike %s
        order by o.role is null, o.name
        limit 1
        """,
        (f"%{name}%",),
    ).fetchone()
    if row is None:
        return None
    official_id = row[0]
    present, absent = conn.execute(
        """
        select count(*) filter (where status = 'present'),
               count(*) filter (where status <> 'present')
        from meeting_attendance where official_id = %s
        """,
        (official_id,),
    ).fetchone()
    return OfficialProfile(
        name=row[1],
        role=row[2],
        borough=row[3],
        district=row[4],
        party=row[5],
        sittings_present=present,
        sittings_absent=absent,
    )


def get_official_record(conn, name: str, limit: int = 400) -> list[ItemResult]:
    """Accountability search: every item an elected official moved or
    seconded, and every recorded vote, dissent or abstention of theirs.

    The limit has to clear a busy councillor's full record -- the majority
    leader moved 289 items in one year -- or the model silently receives a
    slice and understates somebody's voting record.

    Scoped to the officials roster on purpose. Names of residents, staff, and
    contractors that appear inside documents are reachable only through
    full_text_search, so this can't be used to profile a private individual.
    """
    rows = conn.execute(
        """
        with target as (
            select id from officials where name ilike %s
        ),
        involvement as (
            select ai.id as item_id, 'moved' as how
                from agenda_items ai where ai.mover_id in (select id from target)
            union all
            select ai.id, 'seconded'
                from agenda_items ai where ai.seconder_id in (select id from target)
            union all
            select v.agenda_item_id,
                   case
                       when v.position = 'for' then 'voted for (roll call)'
                       when v.source = 'roll_call' then 'voted against (roll call)'
                       when v.position = 'against' then 'dissented (recorded)'
                       else 'abstained (declared conflict of interest)'
                   end
                from item_votes v where v.official_id in (select id from target)
        ),
        grouped as (
            select item_id, array_agg(distinct how order by how) as hows
            from involvement group by item_id
        )
        select
            g.hows, ai.id, m.meeting_date, ai.item_number, ai.title, ai.dossier_number,
            ai.motion_number, ai.vote_outcome, mover.name, seconder.name, ai.section
        from grouped g
        join agenda_items ai on ai.id = g.item_id
        join meetings m on m.id = ai.meeting_id
        left join officials mover on mover.id = ai.mover_id
        left join officials seconder on seconder.id = ai.seconder_id
        order by m.meeting_date desc, ai.position
        limit %s
        """,
        (f"%{name}%", limit),
    ).fetchall()
    results = []
    for row in rows:
        item = _row_to_item(row[1:])
        item.involvement = list(row[0])
        results.append(item)
    return results
