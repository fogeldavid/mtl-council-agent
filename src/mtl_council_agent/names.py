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

# 0.978 (same person, typo) vs <0.60 (different people) on the real roster.
SIMILARITY_THRESHOLD = 0.92


def display_name(raw: str) -> str:
    """The name as it should be shown: honorific dropped, accents kept."""
    return " ".join(_HONORIFIC_RE.sub("", raw.strip()).split())


def normalized_name(raw: str) -> str:
    """The identity key: no honorific, no accents, lowercase, single spaces."""
    decomposed = unicodedata.normalize("NFKD", display_name(raw))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.lower()


def closest_match(candidate: str, existing: list[str]) -> str | None:
    """The nearest existing normalized name, if one is near-identical.

    Catches misspellings the deterministic rules can't, without merging
    distinct people: the threshold sits far above any real pair's score.
    """
    best: tuple[float, str] | None = None
    for name in existing:
        score = SequenceMatcher(None, candidate, name).ratio()
        if score >= SIMILARITY_THRESHOLD and (best is None or score > best[0]):
            best = (score, name)
    return best[1] if best else None
