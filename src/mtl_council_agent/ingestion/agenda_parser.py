"""Parses the standalone "Ordre du jour" (agenda) PDF text into per-item entries.

Layout (verified against real agenda PDFs, e.g. June 2026 city council):

    20.01     Service de l'urbanisme et de la mobilité , Direction des projets
              d'aménagement urbain - 1264139001

    Autoriser une dépense additionnelle de 66 758,51 $, taxes incluses, pour...


    20.02     Service de la stratégie immobilière et de l'habitation - 1269653003
    ...

Each item is: an "NN.NN" item number, a department/unit line optionally ending
in "- <dossier_number>", a blank line, then a free-text description paragraph
running until the next blank-line-separated item header (or a section banner
like "20 – Décisions..." which we skip over).

Item numbers are NOT unique within a meeting. The agenda ends with a section
"80 – Conseil d'agglomération - Dossiers pour orientation" that restarts the
numbering under its own sub-banners (20.01, 30.01, ...), so every item carries
the section it sits in, and (section, item_number) is what identifies it. In
all ten 2026 agendas section 80 is the last one, so everything after its
banner belongs to it. Items with no dossier number (e.g. "01.01 Période de
questions du public") are procedural and carry no dossier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The leading \f matters: pdftotext puts a form feed at every page break, so an
# item that happens to start a new page reads as "\f20.05  Service ..." and a
# bare ^ anchor misses it. That silently dropped 22% of items per agenda.
_ITEM_HEADER_RE = re.compile(
    r"^\f?(?P<item_number>\d{2}\.\d{2})\s{2,}(?P<rest>\S.*)$", re.MULTILINE
)
_DOSSIER_SUFFIX_RE = re.compile(r"-\s*(\d{6,})\s*$")
_ORIENTATION_BANNER_RE = re.compile(
    r"^\f?[ \t]*(?:Page \d+[ \t]+)?80 [–-] Conseil d.agglom", re.MULTILINE
)
# Any section banner ("20 – Affaires contractuelles"), optionally glued to the
# page footer before it. A description paragraph never contains one, so one
# showing up means the paragraph ran into page furniture.
_BANNER_LINE_RE = re.compile(
    r"^\f?[ \t]*(?:Page \d+[ \t]+)?\d{2} [–-] [A-ZÀ-Ý]", re.MULTILINE
)
_PAGE_FOOTER_LINE_RE = re.compile(r"^\f?[ \t]*Page \d+[ \t]*$", re.MULTILINE)

COUNCIL = "council"
ORIENTATION = "agglomeration_orientation"


@dataclass
class AgendaItem:
    item_number: str
    department: str
    dossier_number: str | None
    title: str
    section: str = COUNCIL


def _first_paragraph(description: str) -> str:
    """The item's title: its first paragraph, cut before any page furniture."""
    paragraph = description.split("\n\n")[0]
    for pattern in (_BANNER_LINE_RE, _PAGE_FOOTER_LINE_RE):
        match = pattern.search(paragraph)
        if match:
            paragraph = paragraph[: match.start()]
    return " ".join(paragraph.split())


def parse_agenda(text: str) -> list[AgendaItem]:
    headers = list(_ITEM_HEADER_RE.finditer(text))
    orientation = _ORIENTATION_BANNER_RE.search(text)
    orientation_start = orientation.start() if orientation else len(text)
    items: list[AgendaItem] = []

    for i, match in enumerate(headers):
        start = match.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        block = text[start:end]

        # The department/unit line can wrap onto continuation lines (indented,
        # no leading item number) before the blank line that starts the body.
        body_start = re.search(r"\n\s*\n", block)
        header_tail = match.group("rest")
        if body_start:
            wrapped_header = block[: body_start.start()]
            header_tail += " " + " ".join(wrapped_header.split())
            description = block[body_start.end() :].strip()
        else:
            description = block.strip()

        header_tail = " ".join(header_tail.split())
        dossier_match = _DOSSIER_SUFFIX_RE.search(header_tail)
        dossier_number = dossier_match.group(1) if dossier_match else None
        department = (
            header_tail[: dossier_match.start()].strip(" ,-")
            if dossier_match
            else header_tail
        )

        items.append(
            AgendaItem(
                item_number=match.group("item_number"),
                department=department,
                dossier_number=dossier_number,
                title=_first_paragraph(description),
                section=ORIENTATION if match.start() > orientation_start else COUNCIL,
            )
        )

    return items
