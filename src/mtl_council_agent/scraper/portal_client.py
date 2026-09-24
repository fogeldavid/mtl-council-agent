"""Client for Montreal's legacy council-documents portal.

There is no structured API for city council agendas/minutes/decisions — only
this HTML portal, which lists PDFs per meeting. See project README for how
this was reverse-engineered from the live page.

Portal URL: https://ville.montreal.qc.ca/portal/page?_pageid=5798,85945578
PDF download URL pattern: https://ville.montreal.qc.ca/sel/adi-public/afficherpdf/fichier.pdf?typeDoc={odj|pv|da}&doc={id}

Be polite: this portal has no documented crawl-delay of its own, but we apply
one anyway (matching the 10s delay donnees.montreal.ca specifies for its own
API) since it's the same city IT infrastructure.
"""

from __future__ import annotations

import re
import time as time_module
from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup

from mtl_council_agent.scraper.models import DocumentRef, Fingerprint, MeetingRef

BASE_URL = "https://ville.montreal.qc.ca"
PORTAL_PATH = "/portal/page"
PORTAL_PAGEID = "5798,85945578"

_MEETING_ID_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(\d{2}:\d{2})(ordinaire|extraordinaire)_o$")
_TYPE_DOC_RE = re.compile(r"typeDoc=(\w+)")

CRAWL_DELAY_SECONDS = 10


def _classify_document(doc_type_param: str, title: str) -> str:
    """Map the raw typeDoc query param + link text to our three ingested types."""
    if doc_type_param == "pv":
        return "minutes"
    if doc_type_param == "odj":
        if "documents décisionnels" in title.lower():
            return "bundle"
        if title.strip().lower() == "ordre du jour":
            return "agenda"
        return "other"  # e.g. "Résolutions à la suite d'une motion d'un conseiller"
    return "other"  # typeDoc=da: individual annex/attachment, out of scope for v1


def _outer_meeting_row(id_div):
    """Walk up from the meeting-id div to the <tr> that also holds the PDF-links cell.

    The id div lives inside a nested table; the PDF links live in a sibling <td>
    of the *outer* <tr>, so a plain find_parent('tr') lands one level too deep.
    """
    for parent in id_div.parents:
        if parent.name == "tr" and parent.find("td", class_="eVues_GreyBG", recursive=False):
            return parent
    return None


def parse_portal_page(html: str) -> list[MeetingRef]:
    soup = BeautifulSoup(html, "html.parser")
    meetings: list[MeetingRef] = []

    for id_div in soup.find_all("div", id=_MEETING_ID_RE):
        match = _MEETING_ID_RE.match(id_div["id"])
        date_str, time_str, meeting_type = match.groups()
        meeting_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        meeting_time = datetime.strptime(time_str, "%H:%M").time()

        row = _outer_meeting_row(id_div)
        documents: list[DocumentRef] = []
        if row is not None:
            for anchor in row.find_all("a", href=_TYPE_DOC_RE):
                href = anchor["href"]
                type_param = _TYPE_DOC_RE.search(href).group(1)
                title = anchor.get_text(strip=True)
                documents.append(
                    DocumentRef(
                        doc_type=_classify_document(type_param, title),
                        title=title,
                        url=BASE_URL + href if href.startswith("/") else href,
                    )
                )

        meetings.append(
            MeetingRef(
                meeting_date=meeting_date,
                meeting_time=meeting_time,
                meeting_type=meeting_type,
                source_url=f"{BASE_URL}{PORTAL_PATH}?_pageid={PORTAL_PAGEID}"
                f"&_dad=portal&_schema=PORTAL&dateDebut={meeting_date.year}",
                documents=documents,
            )
        )

    return meetings


def head_document(client: httpx.Client, url: str) -> Fingerprint:
    """The document's current fingerprint, without downloading it.

    Cheap even for a 515MB bundle: a HEAD request returns headers only. The
    server sends ETag and Last-Modified on every PDF (checked on all 2026
    documents), which is what makes a same-URL revision detectable.
    """
    resp = client.head(url, follow_redirects=True, timeout=60)
    resp.raise_for_status()
    length = resp.headers.get("content-length")
    return Fingerprint(
        etag=resp.headers.get("etag"),
        last_modified=resp.headers.get("last-modified"),
        content_length=int(length) if length and length.isdigit() else None,
    )


def fetch_meetings_for_year(client: httpx.Client, year: int) -> list[MeetingRef]:
    resp = client.get(
        f"{BASE_URL}{PORTAL_PATH}",
        params={
            "_pageid": PORTAL_PAGEID,
            "_dad": "portal",
            "_schema": "PORTAL",
            "dateDebut": year,
        },
        headers={"User-Agent": "Mozilla/5.0 (compatible; mtl-council-agent research bot)"},
        follow_redirects=True,
        timeout=30,
    )
    resp.raise_for_status()
    return parse_portal_page(resp.text)


def fetch_meetings_since(start_date: date, client: httpx.Client | None = None) -> list[MeetingRef]:
    """Fetch all meetings from start_date through the present, across year pages."""
    owns_client = client is None
    client = client or httpx.Client()
    try:
        all_meetings: list[MeetingRef] = []
        current_year = date.today().year
        for year in range(start_date.year, current_year + 1):
            all_meetings.extend(fetch_meetings_for_year(client, year))
            time_module.sleep(CRAWL_DELAY_SECONDS)
        return [m for m in all_meetings if m.meeting_date >= start_date]
    finally:
        if owns_client:
            client.close()
