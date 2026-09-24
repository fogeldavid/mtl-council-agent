"""Splits a decision summary into embedding-sized chunks.

Real decision summaries run to ~26,000 characters -- roughly 50x what the
embedding model can take in one pass -- so they're split on paragraph
boundaries into overlapping windows. Every chunk after the first opens with
the tail of the one before it, so a fact that straddles a boundary (a dollar
figure and the sentence explaining it, say) is retrievable from at least one
chunk. Overlap used to be applied only when slicing an oversized paragraph,
which covered 5% of boundaries.
"""

from __future__ import annotations

import re

MAX_CHARS = 1200
OVERLAP_CHARS = 150
# A chunk needs this many letters to be worth embedding. Counting characters
# let through runs of page numbers and "0.00$" spreadsheet cells, which are
# long but mean nothing to a retriever.
MIN_ALPHA_CHARS = 30

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
_SENTENCE_END_RE = re.compile(r"[.:;!?»)\]]$")


def _alpha_count(text: str) -> int:
    return sum(c.isalpha() for c in text)


def _rejoin_broken_paragraphs(paragraphs: list[str]) -> list[str]:
    """Undo paragraph splits that a page break made mid-sentence.

    Once page furniture is stripped, a sentence that ran over a page break
    reads as two paragraphs: the first stops without punctuation, the next
    picks up in lowercase.
    """
    joined: list[str] = []
    for paragraph in paragraphs:
        if (
            joined
            and not _SENTENCE_END_RE.search(joined[-1])
            and paragraph[:1].islower()
        ):
            joined[-1] = f"{joined[-1]} {paragraph}"
        else:
            joined.append(paragraph)
    return joined


def _normalize(text: str) -> list[str]:
    paragraphs = [
        " ".join(paragraph.split())
        for paragraph in _PARAGRAPH_SPLIT_RE.split(text)
        if paragraph.strip()
    ]
    # A paragraph with no letters at all is a stray page number or table
    # cell; it carries nothing to embed.
    return _rejoin_broken_paragraphs([p for p in paragraphs if _alpha_count(p)])


def _tail(text: str, overlap: int) -> str:
    """The last `overlap` characters, starting at a word boundary."""
    if len(text) <= overlap:
        return text
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1 :] if space != -1 else tail


def _windows(paragraph: str, max_chars: int, overlap: int) -> list[str]:
    step = max_chars - overlap
    return [
        paragraph[start : start + max_chars].strip()
        for start in range(0, len(paragraph), step)
        if paragraph[start : start + max_chars].strip()
    ]


def chunk_text(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    paragraphs = _normalize(text)
    if not paragraphs:
        # Nothing with letters in it. Keep a short all-symbol text rather
        # than dropping it: the item still needs to be findable.
        stripped = " ".join(text.split())
        return [stripped[:max_chars]] if stripped else []

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if not current:
            candidate = paragraph
        else:
            candidate = f"{current}\n\n{paragraph}"
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
            seed = _tail(current, overlap)
            candidate = f"{seed}\n\n{paragraph}"
            if len(candidate) <= max_chars:
                current = candidate
                continue
            paragraph = f"{seed} {paragraph}"

        # A single paragraph can exceed the window on its own; slide over it.
        windows = _windows(paragraph, max_chars, overlap)
        chunks.extend(windows[:-1])
        current = windows[-1] if windows else ""

    if current:
        chunks.append(current)

    kept = [c for c in chunks if _alpha_count(c) >= MIN_ALPHA_CHARS]
    if kept:
        return kept

    # The alphabetic floor exists to drop artifacts from inside a long
    # document, not to discard a short one wholesale. Some real items are just
    # brief ("Dépôt de pétitions"), and dropping every chunk would leave them
    # with no embedding and invisible to semantic search.
    return ["\n\n".join(paragraphs)[:max_chars]]
