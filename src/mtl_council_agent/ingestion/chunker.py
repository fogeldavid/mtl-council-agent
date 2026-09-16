"""Splits a decision summary into embedding-sized chunks.

Real decision summaries run to ~26,000 characters -- roughly 50x what the
embedding model can take in one pass -- so they're split on paragraph
boundaries into overlapping windows. Overlap keeps a fact that straddles a
boundary (a dollar figure and the sentence explaining it, say) retrievable
from at least one chunk.
"""

from __future__ import annotations

import re

MAX_CHARS = 1200
OVERLAP_CHARS = 150
# pdftotext leaves page numbers and rule artifacts as their own "paragraphs";
# embedding a chunk of "2" wastes compute and pollutes retrieval.
MIN_CHARS = 40

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")


def _normalize(text: str) -> str:
    return "\n\n".join(
        " ".join(paragraph.split())
        for paragraph in _PARAGRAPH_SPLIT_RE.split(text)
        if paragraph.strip()
    )


def chunk_text(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    normalized = _normalize(text)
    if not normalized:
        return []

    chunks: list[str] = []
    current = ""
    for paragraph in normalized.split("\n\n"):
        if len(current) + len(paragraph) + 2 <= max_chars:
            current = f"{current}\n\n{paragraph}" if current else paragraph
            continue

        if current:
            chunks.append(current)
            current = ""

        # A single paragraph can exceed the window on its own; slide over it.
        if len(paragraph) > max_chars:
            step = max_chars - overlap
            for start in range(0, len(paragraph), step):
                window = paragraph[start : start + max_chars]
                if window.strip():
                    chunks.append(window.strip())
        else:
            current = paragraph

    if current:
        chunks.append(current)

    kept = [c for c in chunks if len(c) >= MIN_CHARS]
    if kept:
        return kept

    # MIN_CHARS exists to drop page-number artifacts from inside a long
    # document, not to discard a short one wholesale. Some real items are just
    # brief ("Dépôt de pétitions"), and dropping every chunk would leave them
    # with no embedding and invisible to semantic search.
    return [normalized[:max_chars]] if normalized else []
