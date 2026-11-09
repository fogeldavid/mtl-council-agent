"""One-off: add minutes text and page numbers to meetings ingested before they were kept.

Run: .venv/bin/python scripts/backfill_minutes_text.py [--dry-run]

Re-reads each meeting's agenda and minutes once, keeps their text on the
documents table, and fills agenda_items.minutes_text and minutes_page. Items
with no decision summary get their search chunks rebuilt from the minutes
text. Movers and seconders are re-read too: the parser used to take the
last proposal in an entry, which on motions is usually the opposition
leader's roll-call request. Titles, outcomes, individual votes and
attendance are left as they are, so a full re-ingest isn't needed. Everything runs in one
transaction, and --dry-run rolls it back after printing what it would do.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mtl_council_agent import minutes_text as entry  # noqa: E402
from mtl_council_agent.db import client as db  # noqa: E402
from mtl_council_agent.ingestion.chunker import chunk_text  # noqa: E402
from mtl_council_agent.ingestion.embed import embed_passages  # noqa: E402
from mtl_council_agent.ingestion.linker import _find_minutes  # noqa: E402
from mtl_council_agent.ingestion.minutes_parser import parse_minutes  # noqa: E402
from mtl_council_agent.ingestion.pdf_extract import strip_page_artifacts  # noqa: E402
from mtl_council_agent.ingestion.pipeline import _download_text  # noqa: E402


def backfill_meeting(conn, http, meeting_id: int, docs: dict[str, str]) -> dict:
    stats = {"items": 0, "with_text": 0, "with_page": 0, "reindexed": 0, "movers_fixed": 0}
    if "agenda" in docs:
        db.save_document_text(conn, docs["agenda"], _download_text(http, docs["agenda"]))
    if "minutes" not in docs:
        return stats
    raw = _download_text(http, docs["minutes"])
    db.save_document_text(conn, docs["minutes"], raw)
    minutes_items = parse_minutes(strip_page_artifacts(raw), raw)
    exact = {(m.section, m.item_number, m.dossier_number): m for m in minutes_items}
    by_number = {(m.section, m.item_number): m for m in minutes_items}

    rows = conn.execute(
        "select id, section, item_number, dossier_number, title, decision_summary,"
        " mover_id, seconder_id from agenda_items where meeting_id = %s order by position",
        (meeting_id,),
    ).fetchall()
    for item_id, section, item_number, dossier_number, title, summary, mover, seconder in rows:
        stats["items"] += 1
        key = SimpleNamespace(
            section=section, item_number=item_number, dossier_number=dossier_number
        )
        match = _find_minutes(key, exact, by_number)
        text = match.text if match else None
        page = match.page if match else None
        conn.execute(
            "update agenda_items set minutes_text = %s, minutes_page = %s where id = %s",
            (text, page, item_id),
        )
        if match:
            new_mover = db.upsert_official(conn, match.mover) if match.mover else None
            new_seconder = db.upsert_official(conn, match.seconder) if match.seconder else None
            if (new_mover, new_seconder) != (mover, seconder):
                conn.execute(
                    "update agenda_items set mover_id = %s, seconder_id = %s where id = %s",
                    (new_mover, new_seconder, item_id),
                )
                stats["movers_fixed"] += 1
        stats["with_text"] += text is not None
        stats["with_page"] += page is not None
        if text and not summary:
            chunks = chunk_text(entry.for_search(title, text))
            if chunks:
                db.replace_item_chunks(conn, item_id, chunks, embed_passages(chunks))
                stats["reindexed"] += 1
    return stats


def main() -> None:
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Roll everything back at the end")
    args = parser.parse_args()
    load_dotenv()

    with db.connect() as conn, httpx.Client() as http:
        db.init_schema(conn)
        meetings = conn.execute(
            "select m.id, m.meeting_date from meetings m order by m.meeting_date"
        ).fetchall()
        totals: dict[str, int] = {}
        for meeting_id, meeting_date in meetings:
            docs = dict(conn.execute(
                "select doc_type, source_pdf_url from documents"
                " where meeting_id = %s and doc_type in ('agenda', 'minutes')",
                (meeting_id,),
            ).fetchall())
            stats = backfill_meeting(conn, http, meeting_id, docs)
            print(meeting_date, stats, flush=True)
            for name, value in stats.items():
                totals[name] = totals.get(name, 0) + value
        print("total", totals)
        no_text = conn.execute(
            "select count(*) from agenda_items ai where decision_summary is null"
            " and minutes_text is null and exists (select 1 from documents d"
            " where d.meeting_id = ai.meeting_id and d.doc_type = 'minutes')"
        ).fetchone()[0]
        print("items in meetings with minutes that still have no text at all:", no_text)
        if args.dry_run:
            conn.rollback()
            print("dry run: rolled back")
        else:
            conn.commit()
            print("committed")


if __name__ == "__main__":
    main()
