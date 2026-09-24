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

Non-obvious things verified against real minutes text:

1. The "<item_number> <dossier_number>" line is a FOOTER stamping the item
   whose motion number/description/vote immediately PRECEDE it -- it does not
   introduce what follows. So each resolved item is bookended by its own
   `CM##/CG##/CE## ####` motion number at the start and its own footer at the
   end, and the motion number is the reliable per-resolution anchor.

2. Items with no dossier (adopting the agenda, declarations, councillors'
   motions) stamp a bare "65.01" footer. Councillors' motions are where most
   recorded roll-call votes happen, so ignoring bare footers lost exactly the
   votes most worth having.

3. Items in the agglomeration-orientation section stamp their footer across
   TWO lines, with the inner item number in brackets:

       1267026001
       80.01 (20.01)

   These are the city council's position on a file going to the
   agglomeration council. They're parsed and tagged with their section (the
   inner number joins them to the agenda); whether their outcomes are attached
   is the linker's call. Either way they must be recognized as boundaries, or
   the council items on either side of a run of them merge into one block and
   pick up the wrong mover, seconder and motion number.

4. A meeting runs over two sittings (13 h and 19 h), each opening with its own
   "PRÉSENCES :" roll. The rolls differ -- a member present at 13 h can be
   absent at 19 h -- so attendance is recorded per sitting and each item
   carries the sitting it was voted in.

What the minutes record about individual votes, and so what can be stored:
    - a roll-call vote ("vote enregistré") names everyone for and against;
    - a majority vote sometimes lists its dissenters ("Dissidences :");
    - a member with a conflict of interest declares it and abstains;
    - an unanimous vote names nobody. Nor does a majority vote without a
      dissent list (4 of 5 in 2026), so nobody can be attributed a position.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mtl_council_agent.ingestion.agenda_parser import COUNCIL, ORIENTATION

# Every anchored pattern here tolerates a leading \f: pdftotext emits a form
# feed at each page break, so a marker landing at the top of a page reads as
# "\f20.01 1264139001" and a bare ^ anchor misses it entirely.
_COUNCIL_FOOTER_RE = re.compile(
    r"^\f?(?P<item_number>\d{2}\.\d{2})(?:[ \t]+(?P<dossier_number>\d{6,}))?[ \t]*$",
    re.MULTILINE,
)
_ORIENTATION_FOOTER_RE = re.compile(
    r"^\f?(?:(?P<dossier_number>\d{6,})[ \t]*\n[ \t]*\f?)?"
    r"80\.\d{2} \((?P<item_number>\d{2}\.\d{2})\)[ \t]*$",
    re.MULTILINE,
)
_MOTION_NUMBER_RE = re.compile(r"^\f?(?P<motion>(?:CM|CG|CE)\d{2} \d{3,4})$", re.MULTILINE)
_MOVER_RE = re.compile(r"Il est proposé par\s+(.+)")
_SECONDER_RE = re.compile(r"appuyé par\s+(.+)")

# "Adopté à l'unanimité.", "Adopté à la majorité des voix.", and the
# chair's declaration after a roll call: "déclare le point 30.01 adopté à la
# majorité des voix". Word-bounded so "Adopter ..." (an item title) and
# "Retirer ..." don't count.
_OUTCOME_RE = re.compile(
    r"\b(?P<verb>adopt|rejet|retir)[ée]e?s?\b"
    r"(?P<how>\s+à\s+(?:l['’]\s*unanimité|la\s+majorité))?",
    re.IGNORECASE,
)

# Recorded but not voted on: a filing the council takes note of ("en prend
# acte"), or a notice of motion for a bylaw to be adopted later.
_NOTED_RE = re.compile(
    r"en\s+prend(?:\s+acte|\s+connaissance)|Avis\s+de\s+motion\s+est\s+donné", re.IGNORECASE
)
# The chair's closing formula when a resolution carries without the usual
# "Adopté" line (adopting an amended agenda, for one): "et il est RÉSOLU en
# conséquence".
_RESOLVED_RE = re.compile(r"RÉSOLU\s+en\s+conséquence")

# Items withdrawn without ever getting a footer: a motion pulled by its
# sponsor ("retire le point 65.04 conformément à l'article 88") or items
# struck when the agenda is adopted ("en y retirant les points 15.03, 30.06,
# 30.09 et 42.01"). An orientation item is written "80.01 (30.05)".
_ITEM_REF = r"(?:80\.01\s*\(\d{2}\.\d{2}\)|\d{2}\.\d{2})"
_WITHDRAWAL_RE = re.compile(
    rf"\bretir(?:e|ant)\s+(?:le|les)\s+points?\s+"
    rf"(?P<refs>{_ITEM_REF}(?:(?:\s*,\s*|\s+et\s+){_ITEM_REF})*)"
)
_ITEM_REF_RE = re.compile(r"80\.01\s*\((?P<inner>\d{2}\.\d{2})\)|(?P<plain>\d{2}\.\d{2})")

_SITTING_RE = re.compile(r"^[ \t]*PRÉSENCES[ \t]*:", re.MULTILINE)
# "ABSENCE(S) AVEC MOTIF ...", "... SANS MOTIF ...", and, on 2026-04-20,
# "ABSENCE - PERTE DU DROIT D'ASSISTER À LA SÉANCE EN VERTU DE L'ARTICLE 502
# ..." for a member barred from sitting. The heading runs to the first colon.
_ABSENCE_HEADER_RE = re.compile(r"^[ \t]*ABSENCES?\b(?P<scope>[^:]*):", re.MULTILINE)
_OTHER_PRESENCES_RE = re.compile(r"^[ \t]*AUTRES PRÉSENCES[ \t]*:", re.MULTILINE)
_ADDRESS_RE = re.compile(r"Mesdames et messieurs|Madame|Monsieur", re.IGNORECASE)
# "(par téléconférence)" is how a member attended, not part of their name.
# "(Jim)" in "Dimitrios (Jim) Beis" is part of the name and stays.
_ATTENDANCE_NOTE_RE = re.compile(r"\s*\((?:par|en)\s[^)]*\)")
# "(À moins d'indication autre, les personnes élues ... sont présentes
# physiquement dans la salle du conseil)" opens some rolls, and wraps.
_ROLL_PREAMBLE_RE = re.compile(r"^\s*\([^)]*\)")

_DISSENT_RE = re.compile(r"^[ \t]*Dissidences?[ \t]*:[ \t]*(?P<first>.*)$", re.MULTILINE)
_ABSTENTION_RE = re.compile(
    r"(?:La|Le)\s+(?:conseillère|conseiller|mairesse|maire)"
    r"(?:\s+d['’]arrondissement)?\s+(?P<name>[^.;]+?)\s+déclare\s+son\s+intérêt\s+et\s+"
    r"s['’]abstient",
)

_VOTE_HEADER_RE = re.compile(r"^[ \t]*VOTE[ \t]*$", re.MULTILINE)
_VOTE_FOR_RE = re.compile(r"Votent en faveur\s*:")
_VOTE_AGAINST_RE = re.compile(r"Vot(?:e|ent) contre\s*:")
_VOTE_RESULT_RE = re.compile(r"Résultat\s*:")
_DECLARED_COUNT_RE = re.compile(r"\((\d+)\)\s*$")
# The chair's declaration after a roll call names what was voted on. A roll
# call on an amendment is not the item's own vote.
_AMENDMENT_DECLARATION_RE = re.compile(r"déclare[^.]*?amendement", re.IGNORECASE)

# One name in a dissent list: capitalized, a few words, no sentence ending.
_NAME_LINE_RE = re.compile(r"^[A-ZÀ-Ý][\w'’.()\- ]{1,60}$")


@dataclass
class RollCall:
    """A recorded vote. Names are as printed: surnames, except the mayor."""

    voted_for: list[str]
    voted_against: list[str]
    declared_for: int | None = None
    declared_against: int | None = None


@dataclass
class MinutesItem:
    item_number: str
    dossier_number: str | None
    motion_number: str | None
    mover: str | None
    seconder: str | None
    vote_outcome: str
    section: str = COUNCIL
    sitting: int = 0
    dissenters: list[str] = field(default_factory=list)
    abstainers: list[str] = field(default_factory=list)
    roll_call: RollCall | None = None


@dataclass
class Sitting:
    """One sitting's roll: who was present and who was absent, and why."""

    start: int
    present: list[str] = field(default_factory=list)
    absent_excused: list[str] = field(default_factory=list)
    absent_unexcused: list[str] = field(default_factory=list)
    # Lost the right to sit (article 502 of the municipal elections act).
    absent_barred: list[str] = field(default_factory=list)


def _clean_name(raw: str) -> str:
    return " ".join(raw.split()).rstrip(" \t")


def _first_line_name(match: re.Match | None) -> str | None:
    """The name on the same line as the proposer/seconder label, cleaned."""
    if match is None:
        return None
    return _clean_name(match.group(1).split("\n")[0])


def _last_match(pattern: re.Pattern, block: str) -> re.Match | None:
    """The LAST match in the block, not the first.

    A block can contain a procedural "réunir, pour fins d'étude" grouping
    motion (with its own proposer/seconder) before the item's real motion --
    the real one is always the one immediately preceding the footer.
    """
    matches = list(pattern.finditer(block))
    return matches[-1] if matches else None


def _extract_outcome(match: re.Match | None) -> str:
    if not match:
        return "unknown"
    verb = match.group("verb").lower()
    if verb == "rejet":
        return "rejected"
    if verb == "retir":
        return "withdrawn"
    how = (match.group("how") or "").lower()
    if "unanimité" in how:
        return "adopted_unanimous"
    if "majorité" in how:
        return "adopted_majority"
    return "adopted"


def _fallback_outcome(block: str) -> str | None:
    """The outcome of a block with no "Adopté/Rejeté/Retiré" line."""
    if _NOTED_RE.search(block):
        return "noted"
    if _RESOLVED_RE.search(block):
        return "adopted"
    return None


def split_names(text: str) -> list[str]:
    """Split a printed list of names: "A, B, C et D (4)".

    Lines wrap mid-name at a hyphen ("Hénault-\\n Ratelle"), so a hyphen at a
    line end is rejoined rather than turned into a space.
    """
    text = re.sub(r"-[ \t]*\n[ \t]*", "-", text)
    text = " ".join(text.split())
    text = _ATTENDANCE_NOTE_RE.sub("", text)
    text = _ADDRESS_RE.sub(" ", text)
    text = _DECLARED_COUNT_RE.sub("", text.strip())
    parts = re.split(r",|\s+et\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _first_paragraph(text: str) -> str:
    """The first run of non-blank lines.

    Attendance lists are one paragraph under their heading. Some years indent
    them and some don't, so the paragraph break is the only reliable end.
    """
    kept: list[str] = []
    for line in text.split("\n"):
        if not line.strip():
            if kept:
                break
            continue
        kept.append(line)
    return "\n".join(kept)


def _indented_list(text: str) -> str:
    """The run of indented lines at the start of `text`, blank lines allowed.

    A dissent list is indented under its label, one name per line, and a page
    break can land in the middle of it (one did, on 2026-03-23), leaving blank
    lines inside the list. The first line at the margin ends it.
    """
    kept = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        if not line[0].isspace():
            break
        kept.append(line)
    return "\n".join(kept)


def parse_attendance(text: str) -> list[Sitting]:
    """Every sitting's roll call, in order.

    Staff listed under "AUTRES PRÉSENCES" are not council members and are
    excluded.
    """
    starts = list(_SITTING_RE.finditer(text))
    sittings = []
    for i, match in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        area = text[match.end() : end]
        other = _OTHER_PRESENCES_RE.search(area)
        if other:
            area = area[: other.start()]

        headers = list(_ABSENCE_HEADER_RE.finditer(area))
        present_text = area[: headers[0].start()] if headers else area
        present_text = _ROLL_PREAMBLE_RE.sub("", present_text)
        sitting = Sitting(start=match.start(), present=split_names(_first_paragraph(present_text)))
        for header in headers:
            # "... LORS DU VOTE ENREGISTRÉ AU POINT 42.05" lists who missed one
            # roll call. It repeats the sitting's own absences, and counting it
            # as a sitting absence would double them.
            scope = header.group("scope")
            if "LORS DU VOTE" in scope:
                continue
            names = split_names(_first_paragraph(area[header.end() :]))
            if "SANS MOTIF" in scope:
                sitting.absent_unexcused.extend(names)
            elif "PERTE DU DROIT" in scope:
                sitting.absent_barred.extend(names)
            else:
                sitting.absent_excused.extend(names)
        # A heading can repeat within one roll (Barone's barred absence is
        # listed twice at the 2026-04-20 19 h sitting).
        for names in (sitting.absent_excused, sitting.absent_unexcused, sitting.absent_barred):
            names[:] = list(dict.fromkeys(names))
        sittings.append(sitting)
    return sittings


def _dissenters(after_outcome: str) -> list[str]:
    match = _DISSENT_RE.search(after_outcome)
    if not match:
        return []
    lines = [match.group("first")] + _indented_list(after_outcome[match.end() + 1 :]).split("\n")
    names = []
    for line in lines:
        name = _clean_name(line)
        if not name:
            continue
        if not _NAME_LINE_RE.match(name) or name.endswith("."):
            break
        names.append(name)
    return names


def _abstainers(block: str) -> list[str]:
    flat = " ".join(block.split())
    return [_clean_name(m.group("name")) for m in _ABSTENTION_RE.finditer(flat)]


def _roll_call(block: str) -> tuple[RollCall, str] | None:
    """The item's own recorded vote, if it had one, and the text after it.

    A block can hold several roll calls: one per amendment, then the item's
    own. Only the last counts, and only if the chair's declaration after it is
    not about an amendment -- an amendment can go to a roll call while the
    item itself passes by voice vote.

    Each list is the paragraph after its label. Taking everything up to the
    next label instead swallowed an "Ouverture des portes" note (a late
    arrival saying how they would have voted) into the names.
    """
    header = _last_match(_VOTE_HEADER_RE, block)
    if header is None:
        return None
    section = block[header.end() :]
    for_match = _VOTE_FOR_RE.search(section)
    against_match = _VOTE_AGAINST_RE.search(section)
    result_match = _VOTE_RESULT_RE.search(section)
    if not (for_match and against_match and result_match):
        return None
    after_result = section[result_match.end() :]
    if _AMENDMENT_DECLARATION_RE.search(after_result[:600]):
        return None

    def names(label: re.Match) -> tuple[list[str], int | None]:
        paragraph = _first_paragraph(section[label.end() :])
        count = _DECLARED_COUNT_RE.search(" ".join(paragraph.split()))
        listed = [n for n in split_names(paragraph) if n.lower() != "aucun"]
        return listed, int(count.group(1)) if count else (0 if not listed else None)

    voted_for, declared_for = names(for_match)
    voted_against, declared_against = names(against_match)
    return (
        RollCall(
            voted_for=voted_for,
            voted_against=voted_against,
            declared_for=declared_for,
            declared_against=declared_against,
        ),
        after_result,
    )


def _all_boundaries(text: str) -> list[tuple[int, int, str, str | None, str]]:
    """Every footer boundary, sorted by position.

    Returns (start, end, item_number, dossier_number, section) tuples. For an
    orientation item, item_number is the inner number in brackets, which is
    what the agenda lists it under.
    """
    boundaries = []
    for m in _COUNCIL_FOOTER_RE.finditer(text):
        boundaries.append(
            (m.start(), m.end(), m.group("item_number"), m.group("dossier_number"), COUNCIL)
        )
    for m in _ORIENTATION_FOOTER_RE.finditer(text):
        boundaries.append(
            (m.start(), m.end(), m.group("item_number"), m.group("dossier_number"), ORIENTATION)
        )
    boundaries.sort(key=lambda b: b[0])
    return boundaries


def parse_minutes(text: str) -> list[MinutesItem]:
    boundaries = _all_boundaries(text)
    sitting_starts = [s.start for s in parse_attendance(text)]
    items: list[MinutesItem] = []

    prev_end = 0
    for start, end, item_number, dossier_number, section in boundaries:
        block = text[prev_end:start]
        prev_end = end

        motion_match = _last_match(_MOTION_NUMBER_RE, block)
        mover_match = _last_match(_MOVER_RE, block)
        seconder_match = _last_match(_SECONDER_RE, block)
        outcome_match = _last_match(_OUTCOME_RE, block)
        after_outcome = block[outcome_match.end() :] if outcome_match else ""

        roll_call = _roll_call(block)
        if roll_call:
            # After a roll call the chair's declaration is the outcome. The
            # minutes can follow it with a contradictory boilerplate line (the
            # 2026-03-23 item 44.01 roll call went 38-24, "adopté à la
            # majorité", and is then stamped "Adopté à l'unanimité").
            declaration = _OUTCOME_RE.search(roll_call[1])
            if declaration:
                outcome_match = declaration
        items.append(
            MinutesItem(
                item_number=item_number,
                dossier_number=dossier_number,
                motion_number=motion_match.group("motion") if motion_match else None,
                mover=_first_line_name(mover_match),
                seconder=_first_line_name(seconder_match),
                vote_outcome=_fallback_outcome(block) or _extract_outcome(outcome_match)
                if outcome_match is None
                else _extract_outcome(outcome_match),
                section=section,
                sitting=max(0, sum(1 for s in sitting_starts if s <= start) - 1),
                dissenters=_dissenters(after_outcome),
                abstainers=_abstainers(block),
                roll_call=roll_call[0] if roll_call else None,
            )
        )

    seen = {(i.section, i.item_number) for i in items}
    for match in _WITHDRAWAL_RE.finditer(text):
        for ref in _ITEM_REF_RE.finditer(match.group("refs")):
            key = (ORIENTATION, ref.group("inner")) if ref.group("inner") else (
                COUNCIL,
                ref.group("plain"),
            )
            if key in seen:
                continue
            seen.add(key)
            items.append(
                MinutesItem(
                    item_number=key[1],
                    dossier_number=None,
                    motion_number=None,
                    mover=None,
                    seconder=None,
                    vote_outcome="withdrawn",
                    section=key[0],
                    sitting=max(0, sum(1 for s in sitting_starts if s <= match.start()) - 1),
                )
            )

    return items
