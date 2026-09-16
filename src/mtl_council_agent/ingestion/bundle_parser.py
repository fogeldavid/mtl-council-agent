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

Each slice is then trimmed at its sign-off block, which ends the decision
summary and begins the attachments. Untrimmed, the median item carries 38KB
and the worst carries 634KB, nearly all of it financial spreadsheets and
checklists. Trimming drops 75% of the stored text, cuts embedding cost and
storage by the same factor, and keeps every substantive section.

Known limitation: a slice's tail can still bleed a few lines into the next
item's "RECOMMANDATION" cover sheet header. That is minor relative to the
size of the summary itself.
"""

from __future__ import annotations

import re

_DOSSIER_LABEL_RE = re.compile(r"Dossier # :\s*(\d+)")

# The decision summary ends with its sign-off block ("Approuvé le : 2026-05-05",
# usually two of them side by side for the director and service director).
# Everything after that is attachments: strategic-plan checklists, financial
# certification spreadsheets, contracts. Measured over one full meeting, those
# attachments are 75% of the text, and they are worse than useless to embed --
# the largest single item was 634KB of "0.00$" spreadsheet padding.
_APPROVAL_RE = re.compile(r"Approuv[ée] le\s*:\s*\d{4}-\d{2}-\d{2}")

# Paired sign-offs sit close together; a match further out than this belongs to
# an attachment, not the sign-off block.
_APPROVAL_CLUSTER_CHARS = 3000
_APPROVAL_TAIL_CHARS = 400

# Fallback for the ~3% of items with no sign-off block, so a pathological
# attachment dump can't land in the database whole.
_MAX_SUMMARY_CHARS = 40_000


def _trim_to_decision_summary(body: str) -> str:
    matches = list(_APPROVAL_RE.finditer(body))
    if not matches:
        return body[:_MAX_SUMMARY_CHARS]

    end = matches[0].end()
    for match in matches[1:]:
        if match.start() - end > _APPROVAL_CLUSTER_CHARS:
            break
        end = match.end()

    return body[: end + _APPROVAL_TAIL_CHARS]


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
        chunks[dossier_number] = _trim_to_decision_summary(text[start:end].strip())

    return chunks
