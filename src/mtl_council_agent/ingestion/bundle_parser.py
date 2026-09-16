"""Splits the giant "Agenda & Decision Documents" bundle PDF text into one
decision-summary chunk per agenda item.

The bundle (verified against a real 4,467-page / 319MB sample) contains, per
item, a short "RECOMMANDATION" cover sheet followed by the full "SOMMAIRE
DÉCISIONNEL" (context, prior decisions, budget, justification -- the richest
content in the whole pipeline) plus occasional attachments. Both the cover
sheet and the summary repeat a "Dossier # : <number>" label near their top.

Splitting strategy: find every "Dossier # : <number>" occurrence, collapse
consecutive occurrences of the *same* dossier number into a single boundary
(the cover sheet and summary share one dossier, so this merges them), and
slice the text between consecutive distinct-dossier boundaries. Verified on
the real sample: 416 raw label occurrences collapse to exactly 139 distinct
items, matching the item count in that meeting's agenda.

Known limitation: each chunk's tail can bleed a few lines into the next
item's "RECOMMANDATION" cover sheet header (there's no clean marker for
"end of this item, before any trailing attachment/signature pages"). This is
minor noise relative to the chunk size and acceptable for v1.
"""

from __future__ import annotations

import re

_DOSSIER_LABEL_RE = re.compile(r"Dossier # :\s*(\d+)")


def split_bundle_by_dossier(text: str) -> dict[str, str]:
    boundaries: list[tuple[str, int]] = []
    last_dossier: str | None = None
    for match in _DOSSIER_LABEL_RE.finditer(text):
        dossier_number = match.group(1)
        if dossier_number != last_dossier:
            boundaries.append((dossier_number, match.start()))
            last_dossier = dossier_number

    chunks: dict[str, str] = {}
    for i, (dossier_number, start) in enumerate(boundaries):
        end = boundaries[i + 1][1] if i + 1 < len(boundaries) else len(text)
        chunks[dossier_number] = text[start:end].strip()

    return chunks
