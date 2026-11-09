"""Saved English translations of French source text; no inference during browsing."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from functools import lru_cache
from pathlib import Path

TRANSLATIONS_PATH = Path(__file__).with_name("data") / "english-translations.json"
MODEL_NAME = "Helsinki-NLP/opus-mt-fr-en"
_CONTEXT = re.compile(r"^\s*CONTEXTE\s*$", re.MULTILINE | re.IGNORECASE)
_END = re.compile(
    r"^\s*(?:DÉCISION\(S\) ANTÉRIEURE\(S\)|DÉCISIONS? ANTÉRIEURES?|DESCRIPTION|"
    r"JUSTIFICATION|ASPECTS FINANCIERS|DÉVELOPPEMENT DURABLE|CALENDRIER.*)\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def source_key(text: str) -> str:
    # Exact source hashing prevents a revised French record reusing an old translation.
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def department_name(raw: str) -> str:
    """The agenda prints "culture, des sports" as "culture_des sports"."""
    return raw.replace("_", ", ")


def context_excerpt(summary: str | None) -> str:
    """A short source excerpt, not an invented or model-generated summary."""
    if not summary:
        return ""
    match = _CONTEXT.search(summary)
    if match:
        body = _END.split(summary[match.end():], maxsplit=1)[0]
    elif len(summary) <= 1200:
        if re.search(r"VALIDATION|Intervenant et sens|Niveau décisionnel|Dossier #", summary):
            return ""
        body = summary
    else:
        return ""
    body = " ".join(body.split())
    # Up to three complete sentences. Omit an incomplete first sentence if too long.
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ü])", body)
    chosen = []
    for sentence in sentences[:3]:
        if len(" ".join([*chosen, sentence])) > 1100:
            break
        chosen.append(sentence)
    return " ".join(chosen)


def protect_numbers(text: str) -> tuple[str, dict[str, str]]:
    """Keep numeric data and official references outside the neural decoder."""
    pattern = re.compile(
        r"\b(?:CM|CG|CA)\d{2}(?:\s+\d+)+\b|"
        r"\b[A-Z]+(?:-[A-Z]+)*-\d+(?:-\d+)*\b|"
        r"\b[A-Z]+[A-Z0-9]*\d[A-Z0-9]*\b|"
        r"(?<!\w)[−-]?\d(?:[\d., \u00a0\u202f]*\d)?(?:\s*[$€])?",
    )
    mapping = {}

    def substitute(match):
        index = len(mapping)
        letters = ""
        while True:
            letters = chr(65 + index % 26) + letters
            index = index // 26 - 1
            if index < 0:
                break
        marker = "ZXQVAL" + letters
        mapping[marker] = match[0]
        return marker

    return pattern.sub(substitute, text), mapping


def unprotect_numbers(text: str, mapping: dict[str, str]) -> str | None:
    for marker, original in mapping.items():
        pattern = r"\b" + r"\s*".join(marker) + r"\b"
        if len(re.findall(pattern, text, re.IGNORECASE)) != 1:
            return None
        text = re.sub(pattern, lambda _, value=original: value, text, flags=re.IGNORECASE)
    return text


def restore_references(source: str, translated: str) -> str:
    """Copy original reference formatting only when numeric identity is unchanged."""
    patterns = (
        r"\b((?:CM|CG|CA)\d{2}(?:\s+\d{2})*\s+)(\d{4})\b",
        r"\b([A-Z]+(?:-[A-Z]+)*-\d{2}-)(\d{4,})\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, source):
            prefix = re.escape(match[1]).replace(r"\ ", r"[\s-]+")
            equivalent = prefix + "0*" + str(int(match[2])) + r"(?!\d)"
            translated = re.sub(equivalent, lambda _, original=match[0]: original, translated,
                                flags=re.IGNORECASE)
    return translated


def _numeric_runs(text: str, english_text: bool = False) -> Counter:
    separators = r"[ \u00a0\u202f,]" if english_text else r"[ \u00a0\u202f]"
    grouped = rf"(?<!\d)\d{{1,3}}(?:{separators}\d{{3}})+(?!\d)"
    text = re.sub(r"\b(?:km|cm|m)(?:[²³]|[23]\b)", "unit", text, flags=re.IGNORECASE)
    normalized = re.sub(grouped, lambda m: re.sub(r"\D", "", m[0]), text)
    return Counter(re.findall(r"\d+", normalized))


_GROUP_SPACE = "[ \u00a0\u202f]"
# A number the model converted only partly: "8 999 704,92 $" came out as
# "$8,999 704.92", which reads as two numbers. Comma grouping already started,
# then a space before three more digits; or a dollar amount grouped with spaces.
_HALF_GROUPED = re.compile(
    rf"(?<![\d.,])\d{{1,3}}(?:,\d{{3}})+(?:{_GROUP_SPACE}\d{{3}})+(?:,\d{{3}})*(?:\.\d{{2}})?(?!\d)"
    rf"|(?<=\$)\d{{1,3}}(?:{_GROUP_SPACE}\d{{3}})+(?:\.\d{{2}})?(?!\d)"
)


def fix_number_grouping(text: str) -> str:
    """Finish a half-converted number. Money (a dollar sign or cents) takes
    English commas. Anything else is a Quebec cadastre lot ("lot 1 336 164"),
    which is written with spaces in English too, so its stray comma goes."""

    def repair(match: re.Match) -> str:
        number = match[0]
        money = "." in number or text[max(0, match.start() - 1):match.start()] == "$"
        if money:
            return re.sub(_GROUP_SPACE, ",", number)
        return re.sub(f"{_GROUP_SPACE}|,", " ", number)

    return _HALF_GROUPED.sub(repair, text)


def numbers_preserved(source: str, translated: str) -> bool:
    # Resolution, tender and project references must retain their exact digits/zeros.
    reference = r"\b(?:CM|CG|CA)\d{2}(?:\s+\d{2})?\s+\d{4}\b|\b\d{2}-\d{4,}\b"
    for code in re.findall(reference, source):
        if " ".join(code.split()) not in " ".join(translated.split()):
            return False
    original = _numeric_runs(source)
    target = _numeric_runs(translated, english_text=True)
    # A faithful translation can change 13 h into 1 p.m.
    for match in re.finditer(r"\b([01]?\d|2[0-3])\s*h\b", source):
        hour = int(match[1])
        english_hour = str(hour % 12 or 12)
        suffix = "a" if hour < 12 else "p"
        pattern = rf"\b{english_hour}(?::\d{{2}})?\s*{suffix}\.?\s*m\.?"
        if re.search(pattern, translated, re.IGNORECASE) and original[match[1]]:
            original[match[1]] -= 1
            original[english_hour] += 1
    if original - target:
        return False
    extra = target - original
    normalized = "".join(c for c in unicodedata.normalize("NFKD", source.lower())
                         if not unicodedata.combining(c))
    words = Counter(re.findall(r"[a-z]+", normalized))
    # French number words may legitimately become digits in English.
    values = {"un": "1", "une": "1", "deux": "2", "trois": "3", "quatre": "4",
              "cinq": "5", "six": "6", "sept": "7", "huit": "8", "neuf": "9",
              "dix": "10", "onze": "11", "douze": "12", "vingt": "20",
              "trente": "30", "quarante": "40", "cinquante": "50", "cent": "100",
              "dizaine": "10", "douzaine": "12", "vingtaine": "20", "trentaine": "30",
              "quarantaine": "40", "centaine": "100", "decennal": "10", "decennale": "10"}
    for word, value in values.items():
        extra[value] -= min(extra[value], words[word])
    return not +extra


@lru_cache(maxsize=1)
def _read(path: str, modified: int) -> dict:
    del modified
    return json.loads(Path(path).read_text(encoding="utf-8")).get("entries", {})


def english(text: str) -> str | None:
    if not text or not TRANSLATIONS_PATH.exists():
        return None
    entries = _read(str(TRANSLATIONS_PATH), TRANSLATIONS_PATH.stat().st_mtime_ns)
    return entries.get(source_key(text))
