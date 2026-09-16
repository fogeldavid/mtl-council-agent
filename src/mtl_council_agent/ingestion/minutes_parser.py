"""Parses the standalone "Procès-verbal" (minutes) PDF text into per-item entries.

Layout (verified against real minutes PDFs, e.g. June 2026 city council):

    CM26 0678

    Autoriser une dépense additionnelle de 66 758,51 $, taxes incluses, pour...

    Vu la recommandation du comité exécutif en date du 20 mai 2026 par sa résolution CE26 0764;

    Il est proposé par   Julien Hénault-Ratelle

            appuyé par   Alan DeSousa

    Et résolu :
    1 - ...
    2 - ...

    Adopté à l'unanimité.

    20.01 1264139001

Two important, non-obvious things verified against real minutes text:

1. The "<item_number> <dossier_number>" line is a FOOTER stamping the item
   whose motion number/description/vote immediately PRECEDE it -- it does not
   introduce what follows. So each resolved item is bookended by its own
   `CM##/CG##/CE## ####` motion number at the start and its own footer at the
   end, and the motion number is the reliable per-resolution anchor.

2. Not every motion belongs to a direct city council item. Sections whose
   items reference the agglomeration council ("Conseil d'agglomération –
   Dossiers pour orientation") stamp their footer across TWO lines instead of
   one, e.g.:

       1267026001
       80.01 (20.01)

   These are the city council's non-binding "orientation" vote on what
   position to take at a *different* body's meeting, not a conseil municipal
   decision -- out of scope per this project's city-council-only scope, but
   they still have to be recognized as boundaries (with their own motion
   number in between), or the real council items on either side of a run of
   these would incorrectly get merged into one giant block and end up
   attributed the wrong mover/seconder/motion number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Every anchored pattern here tolerates a leading \f: pdftotext emits a form
# feed at each page break, so a marker landing at the top of a page reads as
# "\f20.01 1264139001" and a bare ^ anchor misses it entirely.
_COUNCIL_FOOTER_RE = re.compile(
    r"^\f?(?P<item_number>\d{2}\.\d{2}) (?P<dossier_number>\d{6,})$", re.MULTILINE
)
_AGGLOMERATION_FOOTER_RE = re.compile(
    r"^\f?(?P<dossier_number>\d{6,})\s*\n\s*\f?\d{2}\.\d{2} \(\d{2}\.\d{2}\)\s*$",
    re.MULTILINE,
)
_MOTION_NUMBER_RE = re.compile(r"^\f?(?P<motion>(?:CM|CG|CE)\d{2} \d{3,4})$", re.MULTILINE)
_MOVER_RE = re.compile(r"Il est proposé par\s+(.+)")
_SECONDER_RE = re.compile(r"appuyé par\s+(.+)")

_OUTCOME_RE = re.compile(
    r"Adopté(e)? à l'unanimité|Adopté(e)?\b|Rejeté(e)?\b|Retiré(e)?\b",
    re.IGNORECASE,
)


@dataclass
class MinutesItem:
    item_number: str
    dossier_number: str
    motion_number: str | None
    mover: str | None
    seconder: str | None
    vote_outcome: str


def _clean_name(raw: str) -> str:
    return " ".join(raw.split()).rstrip(" \t")


def _first_line_name(match: re.Match | None) -> str | None:
    """The name on the same line as the proposer/seconder label, cleaned."""
    if match is None:
        return None
    return _clean_name(match.group(1).split("\n")[0])


def _extract_outcome(block: str) -> str:
    match = _last_match(_OUTCOME_RE, block)
    if not match:
        return "unknown"
    text = match.group(0).lower()
    if text.startswith("rejet"):
        return "rejected"
    if text.startswith("retir"):
        return "withdrawn"
    return "adopted"


def _last_match(pattern: re.Pattern, block: str) -> re.Match | None:
    """The LAST match in the block, not the first.

    A block can contain a procedural "réunir, pour fins d'étude" grouping
    motion (with its own proposer/seconder) before the item's real motion --
    the real one is always the one immediately preceding the footer.
    """
    matches = list(pattern.finditer(block))
    return matches[-1] if matches else None


def _all_boundaries(text: str) -> list[tuple[int, int, str, str | None]]:
    """Every footer boundary (council or agglomeration), sorted by position.

    Returns (start, end, item_number_or_None, dossier_number) tuples; a plain
    (non-council) boundary carries item_number=None so callers can filter it
    out after using it to correctly delimit neighboring blocks.
    """
    boundaries = []
    for m in _COUNCIL_FOOTER_RE.finditer(text):
        boundaries.append((m.start(), m.end(), m.group("item_number"), m.group("dossier_number")))
    for m in _AGGLOMERATION_FOOTER_RE.finditer(text):
        boundaries.append((m.start(), m.end(), None, m.group("dossier_number")))
    boundaries.sort(key=lambda b: b[0])
    return boundaries


def parse_minutes(text: str) -> list[MinutesItem]:
    boundaries = _all_boundaries(text)
    items: list[MinutesItem] = []

    prev_end = 0
    for start, end, item_number, dossier_number in boundaries:
        block = text[prev_end:start]
        prev_end = end

        if item_number is None:
            continue  # agglomeration-orientation vote: out of scope, boundary only

        motion_match = _last_match(_MOTION_NUMBER_RE, block)
        mover_match = _last_match(_MOVER_RE, block)
        seconder_match = _last_match(_SECONDER_RE, block)

        items.append(
            MinutesItem(
                item_number=item_number,
                dossier_number=dossier_number,
                motion_number=motion_match.group("motion") if motion_match else None,
                mover=_first_line_name(mover_match),
                seconder=_first_line_name(seconder_match),
                vote_outcome=_extract_outcome(block),
            )
        )

    return items
