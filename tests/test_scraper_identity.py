"""Meeting identity, which a single-meeting ingest can never exercise.

The legacy portal publishes no per-meeting page: every meeting in a year
carries the same year-listing URL. Treating that URL as a meeting's identity
collapsed a whole year into one row and let agenda items from different
meetings overwrite each other by position.
"""

from pathlib import Path

from mtl_council_agent.scraper.portal_client import parse_portal_page

FIXTURE = Path(__file__).parent / "fixtures" / "portal_sample.html"


def _meetings():
    return parse_portal_page(FIXTURE.read_text(encoding="utf-8", errors="replace"))


def test_source_url_is_not_unique_per_meeting():
    # Documents the hazard rather than the fix: if this ever becomes unique,
    # the portal gained per-meeting pages and the key could be revisited.
    meetings = _meetings()
    urls = {m.source_url for m in meetings}
    assert len(meetings) > len(urls), "source_url unexpectedly distinguishes meetings"


def test_date_time_and_type_uniquely_identify_every_meeting():
    meetings = _meetings()
    keys = {(m.meeting_date, m.meeting_time, m.meeting_type) for m in meetings}
    assert len(keys) == len(meetings)


def test_same_day_meetings_are_separated_by_time_or_type():
    # January 2026 held an ordinary sitting and an extraordinary one two days
    # apart; a same-day pair would collide on date alone.
    meetings = _meetings()
    by_date: dict = {}
    for m in meetings:
        by_date.setdefault(m.meeting_date, []).append(m)

    for meeting_date, same_day in by_date.items():
        distinct = {(m.meeting_time, m.meeting_type) for m in same_day}
        assert len(distinct) == len(same_day), f"{meeting_date} collides"
