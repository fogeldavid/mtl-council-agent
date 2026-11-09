"""Re-read attendance and each item's sitting from the stored minutes text.

Run: .venv/bin/python scripts/reparse_attendance.py [--dry-run]

For a fix to the attendance parser. It uses documents.extracted_text, so
nothing is downloaded, and touches only meeting_attendance and
agenda_items.sitting. The 2026-09-21 minutes dropped the colon from
"PRÉSENCES :", so that meeting had no attendance and every item sat in the
first sitting.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mtl_council_agent.db import client as db  # noqa: E402
from mtl_council_agent.ingestion.linker import _find_minutes  # noqa: E402
from mtl_council_agent.ingestion.minutes_parser import parse_minutes  # noqa: E402
from mtl_council_agent.ingestion.pdf_extract import strip_page_artifacts  # noqa: E402
from mtl_council_agent.ingestion.pipeline import _store_attendance  # noqa: E402


def main() -> None:
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Roll everything back at the end")
    args = parser.parse_args()
    load_dotenv()

    with db.connect() as conn:
        meetings = conn.execute(
            "select m.id, m.meeting_date, d.extracted_text from meetings m"
            " join documents d on d.meeting_id = m.id"
            " where d.doc_type = 'minutes' and d.extracted_text is not null"
            " order by m.meeting_date"
        ).fetchall()
        for meeting_id, meeting_date, raw in meetings:
            text = strip_page_artifacts(raw)
            before = conn.execute(
                "select count(*) from meeting_attendance where meeting_id = %s", (meeting_id,)
            ).fetchone()[0]
            conn.execute("delete from meeting_attendance where meeting_id = %s", (meeting_id,))
            _store_attendance(conn, meeting_id, text)
            after = conn.execute(
                "select count(*) from meeting_attendance where meeting_id = %s", (meeting_id,)
            ).fetchone()[0]

            minutes_items = parse_minutes(text)
            exact = {(m.section, m.item_number, m.dossier_number): m for m in minutes_items}
            by_number = {(m.section, m.item_number): m for m in minutes_items}
            moved = 0
            for item_id, section, number, dossier, sitting in conn.execute(
                "select id, section, item_number, dossier_number, sitting from agenda_items"
                " where meeting_id = %s",
                (meeting_id,),
            ).fetchall():
                key = SimpleNamespace(section=section, item_number=number, dossier_number=dossier)
                match = _find_minutes(key, exact, by_number)
                if match and match.sitting != sitting:
                    conn.execute(
                        "update agenda_items set sitting = %s where id = %s",
                        (match.sitting, item_id),
                    )
                    moved += 1
            print(f"{meeting_date}: attendance {before} -> {after}, items moved sitting: {moved}")
        if args.dry_run:
            conn.rollback()
            print("dry run: rolled back")
        else:
            conn.commit()
            print("committed")


if __name__ == "__main__":
    main()
