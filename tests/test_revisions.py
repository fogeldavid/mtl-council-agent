"""Revision detection: the city republishes revised agendas at the same URL."""

from mtl_council_agent.db.client import changed_documents
from mtl_council_agent.scraper.models import Fingerprint

AGENDA = "https://ville.montreal.qc.ca/sel/adi-public/afficherpdf/fichier.pdf?typeDoc=odj&doc=17519"
MINUTES = "https://ville.montreal.qc.ca/sel/adi-public/afficherpdf/fichier.pdf?typeDoc=pv&doc=9000"


class FakeConn:
    """Answers the one query changed_documents makes, from a dict."""

    def __init__(self, stored: dict[str, Fingerprint]):
        self.stored = stored

    def execute(self, sql, params):
        urls = params[0]
        rows = [
            (url, fp.etag, fp.last_modified, fp.content_length)
            for url, fp in self.stored.items()
            if url in urls
        ]
        return type("Result", (), {"fetchall": lambda self: rows})()


V2 = Fingerprint('"1424b8-2f000-6aa00000"', "Wed, 16 Sep 2026 20:00:00 GMT", 190000)
V3 = Fingerprint('"1424b8-3881b-6aad6555"', "Fri, 18 Sep 2026 16:22:45 GMT", 231451)


def test_unchanged_documents_are_skipped():
    assert changed_documents(FakeConn({AGENDA: V3}), {AGENDA: V3}) == []


def test_revision_at_the_same_url_is_detected():
    # 2026-09-21: stored from version 2 (92 items), the portal now serves
    # version 3 (122 items) at the same address.
    assert changed_documents(FakeConn({AGENDA: V2}), {AGENDA: V3}) == [AGENDA]


def test_newly_published_minutes_are_detected():
    assert changed_documents(FakeConn({AGENDA: V3}), {AGENDA: V3, MINUTES: V2}) == [MINUTES]


def test_last_modified_stands_in_when_there_is_no_etag():
    old = Fingerprint(None, V2.last_modified, V2.content_length)
    new = Fingerprint(None, V3.last_modified, V3.content_length)
    assert changed_documents(FakeConn({AGENDA: old}), {AGENDA: new}) == [AGENDA]
    assert changed_documents(FakeConn({AGENDA: new}), {AGENDA: new}) == []


def test_a_known_url_without_headers_is_not_refetched():
    blank = Fingerprint(None, None, None)
    assert changed_documents(FakeConn({AGENDA: V3}), {AGENDA: blank}) == []
