"""Text extraction from Montreal council PDFs.

All three document types (agenda, minutes, bundle) are digitally-generated,
text-layer PDFs (confirmed against real samples up to 4,467 pages / 515MB) --
no OCR is needed, just `pdftotext -layout` to preserve the two-column-ish
label/value layout the parsers below key off of.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def extract_text(pdf_path: Path) -> str:
    with tempfile.NamedTemporaryFile(suffix=".txt") as tmp:
        subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), tmp.name],
            check=True,
            capture_output=True,
        )
        return Path(tmp.name).read_text(encoding="utf-8", errors="replace")
