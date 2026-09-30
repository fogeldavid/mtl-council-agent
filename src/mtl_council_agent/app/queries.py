"""Read-only SQL behind the web app.

Every function takes an open connection and returns plain dicts, so the pages
stay free of SQL and each query can be tested against a seeded database. The
app connects as `web_reader`, which can only read, so nothing here could
change data even by mistake.
"""

from __future__ import annotations

from datetime import date


def _rows(conn, sql: str, params: tuple = ()) -> list[dict]:
    cur = conn.execute(sql, params)
    names = [c.name for c in cur.description]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def _row(conn, sql: str, params: tuple = ()) -> dict | None:
    rows = _rows(conn, sql, params)
    return rows[0] if rows else None


def stats(conn) -> dict:
    return _row(
        conn,
        """
        select
            (select count(*) from meetings) as meetings,
            (select count(*) from agenda_items) as items,
            (select count(*) from item_votes) as recorded_votes,
            (select count(*) from officials where role is not null) as members,
            (select max(meeting_date) from meetings) as latest_meeting
        """,
    )


def contested_votes(conn, limit: int = 3) -> list[dict]:
    """Recent council items where the minutes name at least one member against."""
    return _rows(
        conn,
        """
        select ai.id, m.meeting_date, ai.item_number, ai.title, ai.vote_outcome,
               count(*) filter (where v.position = 'for') as votes_for,
               count(*) filter (where v.position = 'against') as votes_against,
               bool_or(v.source = 'roll_call') as roll_call
        from agenda_items ai
        join meetings m on m.id = ai.meeting_id
        join item_votes v on v.agenda_item_id = ai.id
        where ai.section = 'council'
        group by ai.id, m.meeting_date
        having count(*) filter (where v.position = 'against') > 0
        order by m.meeting_date desc, ai.position
        limit %s
        """,
        (limit,),
    )


def meetings(conn) -> list[dict]:
    return _rows(
        conn,
        """
        select m.id, m.meeting_date, m.meeting_time, m.meeting_type,
               count(ai.id) as items,
               exists (
                   select 1 from documents d
                   where d.meeting_id = m.id and d.doc_type = 'minutes'
               ) as has_minutes
        from meetings m
        left join agenda_items ai on ai.meeting_id = m.id
        group by m.id
        order by m.meeting_date desc, m.meeting_time desc
        """,
    )


def meeting(conn, meeting_id: int) -> dict | None:
    return _row(
        conn,
        """
        select m.id, m.meeting_date, m.meeting_time, m.meeting_type,
               exists (
                   select 1 from documents d
                   where d.meeting_id = m.id and d.doc_type = 'minutes'
               ) as has_minutes
        from meetings m where m.id = %s
        """,
        (meeting_id,),
    )


def meeting_items(conn, meeting_id: int) -> list[dict]:
    return _rows(
        conn,
        """
        select id, item_number, section, title, vote_outcome, department, motion_number
        from agenda_items where meeting_id = %s order by position
        """,
        (meeting_id,),
    )


def meeting_attendance(conn, meeting_id: int) -> list[dict]:
    """Per sitting: how many members were present and absent."""
    return _rows(
        conn,
        """
        select sitting,
               count(*) filter (where status = 'present') as present,
               count(*) filter (where status <> 'present') as absent
        from meeting_attendance where meeting_id = %s
        group by sitting order by sitting
        """,
        (meeting_id,),
    )


def meeting_documents(conn, meeting_id: int) -> dict[str, str]:
    rows = _rows(
        conn,
        "select doc_type, source_pdf_url from documents where meeting_id = %s",
        (meeting_id,),
    )
    return {r["doc_type"]: r["source_pdf_url"] for r in rows}


def item(conn, item_id: int) -> dict | None:
    return _row(
        conn,
        """
        select ai.id, ai.meeting_id, m.meeting_date, ai.item_number, ai.section, ai.title,
               ai.department, ai.decision_summary, ai.motion_number, ai.dossier_number,
               ai.vote_outcome, mover.name as mover, seconder.name as seconder,
               ai.mover_id, ai.seconder_id,
               exists (
                   select 1 from documents d
                   where d.meeting_id = ai.meeting_id and d.doc_type = 'minutes'
               ) as has_minutes
        from agenda_items ai
        join meetings m on m.id = ai.meeting_id
        left join officials mover on mover.id = ai.mover_id
        left join officials seconder on seconder.id = ai.seconder_id
        where ai.id = %s
        """,
        (item_id,),
    )


def councillors(conn) -> list[dict]:
    return _rows(
        conn,
        """
        select o.id, o.name, o.role, o.borough, o.district, o.party,
               (select count(*) from item_votes v where v.official_id = o.id) as recorded_votes
        from officials o
        where o.role is not null
        order by o.last_name, o.first_name
        """,
    )


def councillor(conn, official_id: int) -> dict | None:
    return _row(
        conn,
        """
        select o.id, o.name, o.role, o.borough, o.district, o.party,
               count(a.*) filter (where a.status = 'present') as sittings_present,
               count(a.*) filter (where a.status = 'absent_excused') as absent_excused,
               count(a.*) filter (where a.status = 'absent_unexcused') as absent_unexcused,
               count(a.*) filter (where a.status = 'absent_barred') as absent_barred,
               count(a.*) as sittings_total,
               (select count(*) from agenda_items where mover_id = o.id) as moved,
               (select count(*) from agenda_items where seconder_id = o.id) as seconded
        from officials o
        left join meeting_attendance a on a.official_id = o.id
        where o.id = %s
        group by o.id
        """,
        (official_id,),
    )


def councillor_roll_calls(conn, official_id: int) -> list[dict]:
    """Each roll call the member took part in, beside how their party voted.

    The party position is the majority among that party's members on the
    same roll call; null when the member has no party or the party split
    evenly. It is shown for context, never turned into a score.
    """
    return _rows(
        conn,
        """
        with mine as (
            select v.agenda_item_id, v.position
            from item_votes v
            where v.official_id = %(id)s and v.source = 'roll_call'
        ),
        party_votes as (
            select v.agenda_item_id,
                   count(*) filter (where v.position = 'for') as p_for,
                   count(*) filter (where v.position = 'against') as p_against
            from item_votes v
            join officials o on o.id = v.official_id
            where v.source = 'roll_call'
              and o.party = (select party from officials where id = %(id)s)
            group by v.agenda_item_id
        )
        select ai.id, m.meeting_date, ai.item_number, ai.section, ai.title,
               ai.vote_outcome, mine.position,
               case
                   when (select party from officials where id = %(id)s) is null then null
                   when pv.p_for > pv.p_against then 'for'
                   when pv.p_against > pv.p_for then 'against'
               end as party_position
        from mine
        join agenda_items ai on ai.id = mine.agenda_item_id
        join meetings m on m.id = ai.meeting_id
        left join party_votes pv on pv.agenda_item_id = ai.id
        order by m.meeting_date desc, ai.position
        """,
        {"id": official_id},
    )


def councillor_other_positions(conn, official_id: int) -> list[dict]:
    """Recorded dissents and declared conflicts of interest (not roll calls)."""
    return _rows(
        conn,
        """
        select ai.id, m.meeting_date, ai.item_number, ai.section, ai.title,
               ai.vote_outcome, v.position, v.source
        from item_votes v
        join agenda_items ai on ai.id = v.agenda_item_id
        join meetings m on m.id = ai.meeting_id
        where v.official_id = %s and v.source <> 'roll_call'
        order by m.meeting_date desc, ai.position
        """,
        (official_id,),
    )


def councillor_motions(conn, official_id: int, limit: int = 500) -> list[dict]:
    return _rows(
        conn,
        """
        select ai.id, m.meeting_date, ai.item_number, ai.section, ai.title, ai.vote_outcome,
               case when ai.mover_id = %(id)s then 'moved' else 'seconded' end as role
        from agenda_items ai
        join meetings m on m.id = ai.meeting_id
        where ai.mover_id = %(id)s or ai.seconder_id = %(id)s
        order by m.meeting_date desc, ai.position
        limit %(limit)s
        """,
        {"id": official_id, "limit": limit},
    )


def latest_update(conn) -> date | None:
    row = _row(conn, "select max(ingested_at)::date as updated from documents")
    return row["updated"] if row else None


# ---------------------------------------------------------------- search

# ts_headline marks matches with these; they are swapped for <mark> after the
# snippet is HTML-escaped, so record text can never inject markup.
MARK_START, MARK_END = "⟦", "⟧"

OUTCOMES = [
    "adopted_unanimous", "adopted_majority", "adopted", "rejected", "withdrawn", "noted", "unknown",
]


def departments(conn) -> list[str]:
    return [
        r["department"]
        for r in _rows(
            conn,
            "select distinct department from agenda_items where department is not null "
            "order by department",
        )
    ]


def search(
    conn,
    text: str = "",
    mode: str = "exact",
    embedding=None,
    meeting_id: int | None = None,
    outcomes: list[str] | None = None,
    section: str | None = None,
    official_id: int | None = None,
    department: str | None = None,
    limit: int = 500,
    snippets: bool = True,
) -> list[dict]:
    """Items matching the words (or meaning) and every filter given.

    mode "exact": Postgres French full-text search, which matches word forms
    ("piste" finds "pistes"), ranked by relevance, with the matches marked in
    a snippet. mode "meaning": items ranked by their closest chunk to
    `embedding`, the query's vector. It scans all chunks rather than using the
    vector index: at ~13,500 chunks that takes milliseconds, and an index scan
    followed by filtering can silently return fewer results than exist.
    No text: every item matching the filters, newest first.
    """
    where = ["true"]
    params: dict = {"limit": limit}
    if meeting_id:
        where.append("ai.meeting_id = %(meeting_id)s")
        params["meeting_id"] = meeting_id
    if outcomes:
        where.append("coalesce(ai.vote_outcome, 'unknown') = any(%(outcomes)s)")
        params["outcomes"] = outcomes
    if section:
        where.append("ai.section = %(section)s")
        params["section"] = section
    if department:
        where.append("ai.department = %(department)s")
        params["department"] = department
    if official_id:
        where.append(
            "(ai.mover_id = %(official_id)s or ai.seconder_id = %(official_id)s or exists ("
            "select 1 from item_votes v where v.agenda_item_id = ai.id "
            "and v.official_id = %(official_id)s))"
        )
        params["official_id"] = official_id

    select = """
        select ai.id, m.meeting_date, ai.item_number, ai.section, ai.title, ai.vote_outcome,
               ai.department, ai.motion_number, ai.dossier_number,
               exists (
                   select 1 from documents d
                   where d.meeting_id = ai.meeting_id and d.doc_type = 'minutes'
               ) as has_minutes
    """
    text = (text or "").strip()

    if text and mode == "meaning" and embedding is not None:
        params["embedding"] = embedding
        sql = f"""
            with best as (
                select ch.agenda_item_id,
                       min(ch.embedding <=> %(embedding)s::halfvec) as distance
                from item_chunks ch
                where ch.embedding is not null
                group by ch.agenda_item_id
            )
            {select},
                   (select left(ch.content, 320) from item_chunks ch
                    where ch.agenda_item_id = ai.id
                    order by ch.embedding <=> %(embedding)s::halfvec limit 1) as snippet,
                   best.distance as score
            from best
            join agenda_items ai on ai.id = best.agenda_item_id
            join meetings m on m.id = ai.meeting_id
            where {" and ".join(where)}
            order by best.distance
            limit %(limit)s
        """
    elif text:
        params["q"] = text
        params["opts"] = (
            f"StartSel={MARK_START}, StopSel={MARK_END}, MaxWords=35, MinWords=15, "
            "MaxFragments=1, FragmentDelimiter= … "
        )
        # Rank and trim first, then build snippets only for the rows kept:
        # ts_headline over long summaries is the expensive part, and computing
        # it for every match made a broad query like "contrat" take 2 s.
        snippet = (
            "ts_headline('french', ai.title || ' — ' || coalesce(ai.decision_summary, ''), "
            "plainto_tsquery('french', %(q)s), %(opts)s)"
            if snippets
            else "null"
        )
        sql = f"""
            with ranked as (
                select ai.id,
                       ts_rank(ai.search_vector, plainto_tsquery('french', %(q)s)) as score
                from agenda_items ai
                join meetings m on m.id = ai.meeting_id
                where ai.search_vector @@ plainto_tsquery('french', %(q)s)
                  and {" and ".join(where)}
                order by score desc, m.meeting_date desc
                limit %(limit)s
            )
            {select}, {snippet} as snippet, ranked.score
            from ranked
            join agenda_items ai on ai.id = ranked.id
            join meetings m on m.id = ai.meeting_id
            order by ranked.score desc, m.meeting_date desc
        """
    else:
        sql = f"""
            {select}, null as snippet, null as score
            from agenda_items ai
            join meetings m on m.id = ai.meeting_id
            where {" and ".join(where)}
            order by m.meeting_date desc, ai.position
            limit %(limit)s
        """
    return _rows(conn, sql, params)
