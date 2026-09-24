from pathlib import Path

from mtl_council_agent.ingestion.chunker import (
    MAX_CHARS,
    MIN_ALPHA_CHARS,
    OVERLAP_CHARS,
    chunk_text,
)
from mtl_council_agent.ingestion.pdf_extract import strip_page_artifacts

FIXTURES = Path(__file__).parent / "fixtures"


def _paragraphs(n: int) -> str:
    return "\n\n".join(
        f"Paragraphe {i}: le conseil autorise une dépense de {i} 000 $ pour des travaux."
        * 3
        for i in range(n)
    )


def test_chunks_respect_the_embedding_window():
    text = (FIXTURES / "bundle_sample_excerpt.txt").read_text(
        encoding="utf-8", errors="replace"
    )
    chunks = chunk_text(strip_page_artifacts(text))
    assert chunks
    assert all(len(c) <= MAX_CHARS for c in chunks)


def test_page_number_artifacts_are_dropped():
    # pdftotext emits stray page numbers as their own paragraphs.
    body = "Le conseil municipal a autorisé une dépense. " * 5
    assert chunk_text("2\n\n" + body + "\n\n7") == [body.strip()]


def test_every_boundary_overlaps():
    # Overlap used to apply only inside oversized paragraphs, 5% of
    # boundaries. Each chunk now opens with the previous chunk's tail.
    chunks = chunk_text(_paragraphs(40))
    assert len(chunks) > 3
    for previous, current in zip(chunks, chunks[1:], strict=False):
        opening = current[:40]
        assert opening in previous, (previous[-200:], current[:200])
        assert len(current.split("\n\n")[0]) <= OVERLAP_CHARS


def test_long_paragraph_is_split_with_overlap():
    paragraph = "phrase " * 1000
    chunks = chunk_text(paragraph)
    assert len(chunks) > 1
    assert all(len(c) <= MAX_CHARS for c in chunks)


def test_sentence_split_by_a_page_break_is_rejoined():
    text = (
        "Le contrat est accordé pour une durée de trente-six mois, avec deux options\n\n\n"
        "de prolongation de douze mois chacune.\n\n"
        "Justification : le plus bas soumissionnaire conforme."
    )
    chunks = chunk_text(text)
    assert "deux options de prolongation" in chunks[0]
    assert "\n\nJustification" in chunks[0]


def test_symbol_only_chunks_are_dropped():
    # Long but meaningless: a spreadsheet's worth of amounts.
    text = ("Montant total autorisé pour le projet de réfection. " * 20) + "\n\n" + (
        "0.00$ " * 400
    )
    chunks = chunk_text(text)
    assert all(sum(c.isalpha() for c in chunk) >= MIN_ALPHA_CHARS for chunk in chunks)


def test_empty_input_yields_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_short_but_real_text_is_kept():
    # Some agenda items are genuinely brief. Dropping them for being under
    # the letter floor left them with no embedding and unreachable by
    # semantic search.
    assert chunk_text("Dépôt de pétitions") == ["Dépôt de pétitions"]
    assert chunk_text("Période de questions du public") == [
        "Période de questions du public"
    ]
