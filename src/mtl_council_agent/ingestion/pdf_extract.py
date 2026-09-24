"""Text extraction from Montreal council PDFs.

All three document types (agenda, minutes, bundle) are digitally-generated,
text-layer PDFs (confirmed against real samples up to 4,467 pages / 515MB) --
no OCR is needed, just `pdftotext -layout` to preserve the two-column-ish
label/value layout the parsers below key off of.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

# Page furniture that pdftotext leaves inline with the content. Measured on the
# 2026 corpus, 44% of stored chunks carried at least one of these, and an
# agenda footer that lands on the same line as the next section's banner
# ("Page 25 80 – Conseil d'agglomération") leaked into item titles.
_PAGE_FOOTER_RE = re.compile(r"^[ \t]*Page \d+[ \t]*$", re.MULTILINE)
# A footer glued to the banner that follows it: keep the banner, drop the footer.
_GLUED_PAGE_FOOTER_RE = re.compile(r"^[ \t]*Page \d+[ \t]+(?=\d{2} [–-] )", re.MULTILINE)
# Bundle page counters ("6/24"), alone on their line.
_PAGE_COUNTER_RE = re.compile(r"^[ \t]*\d+ ?/ ?\d+[ \t]*$", re.MULTILINE)
# Minutes running header: "Séance ordinaire du conseil municipal du lundi
# 23 mars 2026 à 13 h      58". It interrupts lists mid-way (a dissent list
# was split in two by one), so it has to go before parsing, not after.
_MINUTES_HEADER_RE = re.compile(
    r"^[ \t]*Séance (?:ordinaire|extraordinaire) du conseil municipal du .+?"
    r"\d{1,2} h(?: \d{2})?[ \t]+\d+[ \t]*$",
    re.MULTILINE,
)
# Bundle running header, printed on every page of every decision document.
# It often wraps after "des", leaving "instances" on a line of its own; the
# single-line form alone missed it in 1,165 of 13,570 stored chunks.
_BUNDLE_HEADER_RE = re.compile(
    r"^[ \t]*Système de gestion des décisions des\s+instances[ \t]*$", re.MULTILINE
)


def extract_text(pdf_path: Path) -> str:
    with tempfile.NamedTemporaryFile(suffix=".txt") as tmp:
        subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), tmp.name],
            check=True,
            capture_output=True,
        )
        return Path(tmp.name).read_text(encoding="utf-8", errors="replace")


def strip_page_artifacts(text: str) -> str:
    """Remove page furniture so parsers and chunks see only content.

    Form feeds become newlines: every parser anchors on line starts, and a
    page break is not a meaningful boundary in any of the three documents.
    """
    text = text.replace("\f", "\n")
    text = _GLUED_PAGE_FOOTER_RE.sub("", text)
    for pattern in (_PAGE_FOOTER_RE, _PAGE_COUNTER_RE, _MINUTES_HEADER_RE, _BUNDLE_HEADER_RE):
        text = pattern.sub("", text)
    return text
