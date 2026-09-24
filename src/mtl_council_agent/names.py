"""Identity for elected officials' names.

The minutes spell the same person several ways. Measured across one year of
real records, 25 stored names represented 19 people:

    Julien Hénault-Ratelle / M. Julien Hénault-Ratelle   honorific
    Marie Plourde          / Mme Marie Plourde           honorific
    Ericka Alneus          / Ericka Alnéus               accent
    Julien Hénault-Ratelle / Julien Hénault-Ratellte     typo in the source

Honorifics, accents, case and spacing are handled by normalizing, which is
deterministic and predictable. Source typos are not, so they fall back to a
similarity check with a deliberately high threshold: on the real roster the
typo pair scores 0.978 while the closest pair of genuinely different people
scores below 0.60, so anything in between separates them cleanly.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_HONORIFIC_RE = re.compile(r"^(?:M\.|MM\.|Mme\.?|Mmes\.?|Mlle\.?|Dr\.?)\s+", re.IGNORECASE)

# On the real roster the one typo pair scores 0.978 and the closest pair of
# genuinely different people scores below 0.60. The threshold sits just under
# the typo rather than midway between: merging two people is a silent
# correctness bug in the accountability search, while failing to merge leaves
# a visible duplicate that the alias record makes easy to spot and fix.
SIMILARITY_THRESHOLD = 0.95


def display_name(raw: str) -> str:
    """The name as it should be shown: honorific dropped, accents kept."""
    return " ".join(_HONORIFIC_RE.sub("", raw.strip()).split())


def normalized_name(raw: str) -> str:
    """The identity key: no honorific, no accents, lowercase, single spaces."""
    decomposed = unicodedata.normalize("NFKD", display_name(raw))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.lower()


def closest_match(candidate: str, existing: list[str]) -> tuple[str, float] | None:
    """The nearest existing normalized name and its score, if near-identical.

    Catches misspellings the deterministic rules can't, without merging
    distinct people: the threshold sits far above any real pair's score. The
    score comes back so a fuzzy merge can be recorded and audited rather than
    happening invisibly.
    """
    best: tuple[str, float] | None = None
    for name in existing:
        score = SequenceMatcher(None, candidate, name).ratio()
        if score >= SIMILARITY_THRESHOLD and (best is None or score > best[1]):
            best = (name, score)
    return best


def near_miss(candidate: str, existing: list[str], floor: float = 0.80) -> tuple[str, float] | None:
    """The nearest name that was close but not close enough to merge.

    Surfaces the case the threshold deliberately refuses: a spelling that
    looks like an existing official but fell short, which is either a bad
    typo needing a wider threshold or two people who genuinely resemble each
    other. Either way it should be looked at rather than discovered later.
    """
    best: tuple[str, float] | None = None
    for name in existing:
        score = SequenceMatcher(None, candidate, name).ratio()
        if floor <= score < SIMILARITY_THRESHOLD and (best is None or score > best[1]):
            best = (name, score)
    return best


def _given_name_words(first_name: str) -> set[str]:
    """Every word of the roster's given names, nicknames included.

    "Dimitrios (Jim)" yields {"dimitrios", "jim"}; "Alba Stella" yields
    {"alba", "stella"}.
    """
    return set(re.sub(r"[()]", " ", normalized_name(first_name)).split())


def matches_roster_entry(key: str, first_name: str | None, last_name: str | None) -> bool:
    """Whether a normalized name refers to this roster member.

    The surname must end the name exactly and the name's first word must be
    one of the member's given names. Surnames are unique across the 65
    council members, and requiring a given name on top keeps a stray
    surname match from merging two people.
    """
    if not first_name or not last_name:
        return False
    surname = normalized_name(last_name)
    if not key.endswith(" " + surname):
        return False
    return key.split(" ", 1)[0] in _given_name_words(first_name)
