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

Item numbers are NOT globally unique within a meeting (they reset per section),
so the dossier number is the true stable key used to join against minutes and
bundle data downstream (see linker.py). Items with no dossier number (e.g.
"01.01 Période de questions du public") are procedural and carry no dossier.
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


@dataclass
class AgendaItem:
    item_number: str
    department: str
    dossier_number: str | None
    title: str


def parse_agenda(text: str) -> list[AgendaItem]:
    headers = list(_ITEM_HEADER_RE.finditer(text))
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
                title=" ".join(description.split("\n\n")[0].split()),
            )
        )

    return items
