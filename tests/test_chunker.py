from pathlib import Path

from mtl_council_agent.ingestion.chunker import MAX_CHARS, MIN_CHARS, chunk_text

FIXTURES = Path(__file__).parent / "fixtures"


def test_chunks_respect_the_embedding_window():
    text = (FIXTURES / "bundle_sample_excerpt.txt").read_text(
        encoding="utf-8", errors="replace"
    )
    chunks = chunk_text(text)
    assert chunks
    assert all(len(c) <= MAX_CHARS for c in chunks)


def test_page_number_artifacts_are_dropped():
    # pdftotext emits stray page numbers as their own paragraphs.
    text = "2\n\n" + ("Le conseil municipal a autorisé une dépense. " * 5) + "\n\n7"
    chunks = chunk_text(text)
    assert all(len(c) >= MIN_CHARS for c in chunks)
    assert not any(c.strip() in {"2", "7"} for c in chunks)


def test_long_paragraph_is_split_with_overlap():
    paragraph = "phrase " * 1000
    chunks = chunk_text(paragraph)
    assert len(chunks) > 1
    assert all(len(c) <= MAX_CHARS for c in chunks)


def test_empty_input_yields_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_short_but_real_text_is_kept():
    # Some agenda items are genuinely brief. Dropping them for being under
    # MIN_CHARS left them with no embedding and unreachable by semantic search.
    assert chunk_text("Dépôt de pétitions") == ["Dépôt de pétitions"]
    assert chunk_text("Période de questions du public") == [
        "Période de questions du public"
    ]
