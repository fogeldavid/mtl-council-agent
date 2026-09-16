from datetime import date, time
from pathlib import Path

from mtl_council_agent.scraper.portal_client import parse_portal_page

FIXTURE = Path(__file__).parent / "fixtures" / "portal_sample.html"


def test_parses_all_meetings_on_page():
    html = FIXTURE.read_text(encoding="utf-8", errors="replace")
    meetings = parse_portal_page(html)
    assert len(meetings) == 10


def test_classifies_document_types_correctly():
    html = FIXTURE.read_text(encoding="utf-8", errors="replace")
    meetings = parse_portal_page(html)

    june = next(m for m in meetings if m.meeting_date == date(2026, 6, 15))
    assert june.meeting_time == time(13, 0)
    assert june.meeting_type == "ordinaire"

    bundle = june.document("bundle")
    agenda = june.document("agenda")
    minutes = june.document("minutes")
    assert bundle is not None and "doc=17333" in bundle.url
    assert agenda is not None and "doc=17334" in agenda.url
    assert minutes is not None and "doc=8466" in minutes.url


def test_future_meeting_has_no_minutes_yet():
    html = FIXTURE.read_text(encoding="utf-8", errors="replace")
    meetings = parse_portal_page(html)

    newest = next(m for m in meetings if m.meeting_date == date(2026, 9, 21))
    assert newest.document("minutes") is None
    assert newest.document("bundle") is not None
    assert newest.document("agenda") is not None


def test_attachment_and_motion_docs_classified_as_other():
    html = FIXTURE.read_text(encoding="utf-8", errors="replace")
    meetings = parse_portal_page(html)

    aug = next(m for m in meetings if m.meeting_date == date(2026, 8, 24))
    other_titles = [d.title for d in aug.documents if d.doc_type == "other"]
    assert any("VG_sous embargo" in t for t in other_titles)
    assert any("Résolutions à la suite d'une motion" in t for t in other_titles)
