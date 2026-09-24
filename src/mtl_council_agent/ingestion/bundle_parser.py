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

Each slice is then trimmed to its cover sheet plus each summary up to that
summary's sign-off block, which ends it and begins the attachments.
Untrimmed, the median item carries 38KB and the worst carries 634KB, nearly
all of it financial spreadsheets and checklists. Trimming drops 75% of the
stored text, cuts embedding cost and storage by the same factor, and keeps
every substantive section.

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
# From the endorsement to the first approval can run longer: a director's
# delegation note sits between them on some items (4,500 chars on
# 2026-09-21 item 20.37).
_ENDORSEMENT_TO_APPROVAL_CHARS = 6000
_APPROVAL_TAIL_CHARS = 400

# Not every summary reaches the directors' approval. Bylaws, filings and
# transit-authority items stop at the file officer's endorsement block:
#     RESPONSABLE DU DOSSIER      ENDOSSÉ PAR      Le : 2026-08-05
# Without this, the 13 capped 2026 items with no "Approuvé le" fell through to
# the character cap and stored up to 36KB of attachments each. The earlier
# "Signé par ... Le 2026-08-24" line is the one-page cover sheet's signature,
# which comes BEFORE the summary, so it can't serve as the end.
_ENDORSEMENT_RE = re.compile(r"ENDOSS[ÉE] PAR\s+Le\s*:\s*\d{4}-\d{2}-\d{2}")
_RESPONSIBLE_RE = re.compile(r"RESPONSABLE DU DOSSIER")
_PAGE_GAP_RE = re.compile(r"\n(?:[ \t]*\n){3,}")
_SAME_LINE_CHARS = 120
# The first attachment after most summaries, "Grille d'analyse Montréal 2030".
# The title's spacing varies (a control character in place of the space,
# "Montréal" wrapped onto the next line, Unicode direction marks around it),
# so only its opening is matched.
_FIRST_ATTACHMENT_RE = re.compile(
    r"^[ \t\u200e\u200f\u202a-\u202e]*Grille d.analyse", re.MULTILINE
)

# An item can carry more than one summary: an addendum ("SOMMAIRE ADDENDA")
# followed by the original ("SOMMAIRE DÉCISIONNEL"), with the addendum's
# attachments -- a whole contract, for 2026-06-15 item 20.35 -- in between.
# Each summary is kept up to its own sign-off and what lies between is dropped.
_SUMMARY_START_RE = re.compile(r"SOMMAIRE (?:ADDENDA|DÉCISIONNEL|DECISIONNEL)")

# Fallback for items with none of the markers above, so a pathological
# attachment dump can't land in the database whole.
_MAX_SUMMARY_CHARS = 40_000


def _signoff_end(section: str) -> int | None:
    """Where one summary's sign-off block ends, if it has one.

    Every summary signs off under "RESPONSABLE DU DOSSIER". The endorsement
    date sits on that same line when there is one, and the directors'
    approvals, when there are any, follow within a page. An addendum can stop
    at the bare label with neither, and its attachments follow directly.
    Tail characters keep the signatories' names.
    """
    anchor = _RESPONSIBLE_RE.search(section)
    if anchor:
        end = anchor.end()
        endorsement = _ENDORSEMENT_RE.search(section, end, end + _SAME_LINE_CHARS)
        if endorsement:
            end = endorsement.end()
        approvals = list(_APPROVAL_RE.finditer(section, end))
    else:
        approvals = list(_APPROVAL_RE.finditer(section))
        if not approvals:
            return None
        end = approvals[0].end()
        approvals = approvals[1:]

    window = _ENDORSEMENT_TO_APPROVAL_CHARS if anchor else _APPROVAL_CLUSTER_CHARS
    for match in approvals:
        if match.start() - end > window:
            break
        end = match.end()
        window = _APPROVAL_CLUSTER_CHARS

    tail = section[end : end + _APPROVAL_TAIL_CHARS]
    # The signatories' names and phone numbers follow within a couple of
    # lines; three or more blank lines mean the page (and the summary) ended.
    stop = min(
        (m.start() for m in (_FIRST_ATTACHMENT_RE.search(tail), _PAGE_GAP_RE.search(tail)) if m),
        default=len(tail),
    )
    return end + stop


def _trim_to_decision_summary(body: str) -> str:
    starts = [m.start() for m in _SUMMARY_START_RE.finditer(body)]
    if not starts:
        end = _signoff_end(body)
        if end is not None:
            return body[:end].rstrip()
        attachment = _FIRST_ATTACHMENT_RE.search(body)
        if attachment:
            return body[: attachment.start()].rstrip()
        return body[:_MAX_SUMMARY_CHARS]

    # The cover sheet: everything before the first summary.
    kept = [body[: starts[0]].rstrip()]
    for i, start in enumerate(starts):
        section_end = starts[i + 1] if i + 1 < len(starts) else len(body)
        section = body[start:section_end]
        end = _signoff_end(section)
        if end is None:
            attachment = _FIRST_ATTACHMENT_RE.search(section)
            end = attachment.start() if attachment else min(len(section), _MAX_SUMMARY_CHARS)
        kept.append(section[:end].rstrip())
    return "\n\n".join(part for part in kept if part)[:_MAX_SUMMARY_CHARS]


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
