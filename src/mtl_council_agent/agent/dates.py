"""Meeting dates as answers print them: ISO, English or French."""

from __future__ import annotations

import re

_MONTHS = {
    name: number
    for number, names in enumerate(
        [("january", "janvier"), ("february", "février"), ("march", "mars"),
         ("april", "avril"), ("may", "mai"), ("june", "juin"), ("july", "juillet"),
         ("august", "août"), ("september", "septembre"), ("october", "octobre"),
         ("november", "novembre"), ("december", "décembre")],
        start=1,
    )
    for name in names
}
_MONTH = "|".join(_MONTHS)
_DATE_RES = (
    re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b"),
    re.compile(rf"\b(?P<mon>{_MONTH})\s+(?P<d>\d{{1,2}}),?\s+(?P<y>\d{{4}})", re.IGNORECASE),
    re.compile(rf"\b(?P<d>\d{{1,2}})(?:er)?\s+(?P<mon>{_MONTH})\s+(?P<y>\d{{4}})", re.IGNORECASE),
)


def dates_in(text: str) -> set[str]:
    """Every date the text names, as YYYY-MM-DD."""
    dates = set()
    for pattern in _DATE_RES:
        for m in pattern.finditer(text):
            month = int(m.group("m")) if "m" in m.groupdict() and m.group("m") else (
                _MONTHS[m.group("mon").lower()]
            )
            dates.add(f"{int(m.group('y')):04d}-{month:02d}-{int(m.group('d')):02d}")
    return dates
