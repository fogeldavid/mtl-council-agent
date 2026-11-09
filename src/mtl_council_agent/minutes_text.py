"""Readable parts of an item's entry in the minutes.

An entry, as stored in agenda_items.minutes_text, reads:

    CM26 0998

    Accorder un contrat à 9125-5661 Québec inc. (Groupe Specs), pour ...

    Vu la recommandation du comité exécutif en date du 2 septembre 2026 ...

    Il est proposé par   Julien Hénault-Ratelle

    appuyé par    Andréanne Moreau

    Et résolu :

    1- d'accorder à 9125-5661 Québec inc. (Groupe Specs), plus bas ...

    Adopté à l'unanimité.

The mover, seconder and outcome are already stored as columns and shown in
the vote panel, so neither view below repeats them.
"""

from __future__ import annotations

import re

_MOTION_NUMBER_RE = re.compile(r"^(?:CM|CG|CE)\d{2} \d{3,4}$")
_MOVER_RE = re.compile(r"^(?:Il est proposé par|appuyé par)\b")
_SECONDER_RE = re.compile(r"^appuyé par\b")
_RESOLVED_RE = re.compile(r"^Et résolu\s*:?\s*$", re.IGNORECASE)
# Where the vote starts: the outcome line, or a roll call ("Le greffier fait
# l'appel des membres", then VOTE, Résultat and the chair's declaration).
_VOTE_RE = re.compile(
    r"^(?:(?:Adopté|Rejeté|Retiré)e?s?\b|Le greffier fait l.appel|VOTE$|Résultat\s*:"
    r"|La présidente du conseil, [^,]+, déclare le point)"
)
# Where the resolution's clauses stop: the vote, or the debate that some
# declarations and motions record before it.
_CLAUSES_END_RE = re.compile(
    rf"{_VOTE_RE.pattern}|^Un débat s.engage|^À \d{{1,2}} h|^Il est proposé par"
)


def paragraphs(text: str | None) -> list[str]:
    """Blank-line paragraphs with pdftotext's line wraps joined back up.

    The minutes don't hyphenate words at line ends, so a line ending in a
    hyphen is a compound name wrapped mid-way ("Hénault-" / "Ratelle") and
    joins without a space. A spaced dash ("taxes incluses -") joins with one.
    """
    result = []
    for block in re.split(r"\n\s*\n", text or ""):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        joined = lines[0]
        for line in lines[1:]:
            compound = joined.endswith("-") and not joined.endswith(" -")
            joined += line if compound else " " + line
        result.append(joined)
    return result


def _until(pattern: re.Pattern, parts: list[str]) -> list[str]:
    for index, part in enumerate(parts):
        if pattern.match(part):
            return parts[:index]
    return parts


def body(text: str | None) -> list[str]:
    """The entry without its resolution number, title, movers and vote.

    Keeps the debate summary the minutes record for declarations and motions:
    it is the only account of what was said.
    """
    parts = paragraphs(text)
    if parts and _MOTION_NUMBER_RE.match(parts[0]):
        parts = parts[2:]
    return [p for p in _until(_VOTE_RE, parts) if not _MOVER_RE.match(p)]


def resolved(text: str | None) -> list[str]:
    """Only the clauses council voted on.

    They follow the last "Et résolu :" (a block can hold a procedural
    resolution first) or, in motions, which have no such line, the first
    seconder. Filings noted without a resolution return nothing.
    """
    parts = paragraphs(text)
    starts = [i for i, p in enumerate(parts) if _RESOLVED_RE.match(p)]
    if not starts:
        starts = [i for i, p in enumerate(parts) if _SECONDER_RE.match(p)][:1]
    if not starts:
        return []
    return _until(_CLAUSES_END_RE, parts[starts[-1] + 1 :])


def for_search(title: str, text: str | None) -> str:
    """What to embed for an item with no decision summary."""
    return "\n\n".join([title, *body(text)])
