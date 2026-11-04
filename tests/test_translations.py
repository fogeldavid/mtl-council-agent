"""Offline translation lookup and source fidelity; no model download in tests."""

import json

from mtl_council_agent.app import translations


def test_context_is_a_short_source_excerpt_not_metadata_or_justification():
    text = ("Dossier 123\nCONTEXTE\nThe first source sentence. Another source sentence.\n"
            "DESCRIPTION\nDo not include this section.")
    expected = "The first source sentence. Another source sentence."
    assert translations.context_excerpt(text) == expected
    assert translations.context_excerpt(None) == ""
    assert translations.context_excerpt("metadata " * 500) == ""


def test_translation_is_invalidated_by_changed_french_text(tmp_path, monkeypatch):
    path = tmp_path / "english.json"
    path.write_text(json.dumps({"entries": {
        translations.source_key("Un contrat"): "A contract",
    }}))
    monkeypatch.setattr(translations, "TRANSLATIONS_PATH", path)
    assert translations.english("Un contrat") == "A contract"
    assert translations.english("Un contrat révisé") is None


def test_numeric_guard_rejects_changed_amounts_and_identifiers():
    assert translations.numbers_preserved("711 280 $", "$711,280")
    assert not translations.numbers_preserved("711 280 $", "$711,281")
    assert not translations.numbers_preserved("CM26 0316", "CM26 316")
    assert not translations.numbers_preserved("IM-DV-23-0001", "IM-DV-23-001")
    assert not translations.numbers_preserved("Un contrat de 25 $", "A $25,000 contract")


def test_numeric_guard_accepts_faithful_time_and_number_word_conversions():
    assert translations.numbers_preserved(
        "le 21 septembre 2026, à 13 h", "September 21, 2026 at 1 p.m.",
    )
    assert translations.numbers_preserved("une quarantaine de joueurs de 16 à 19 ans",
                                          "approximately 40 players aged 16–19")
    assert translations.numbers_preserved("programme décennal", "10-year program")


def test_long_source_is_split_without_losing_words():
    from scripts.translate_records import split_source

    class Tokenizer:
        def encode(self, text):
            return text.split()

    source = " ".join(f"word{i}" for i in range(1000))
    chunks = split_source(source, Tokenizer(), maximum=400)
    assert " ".join(chunks) == source
    assert all(len(chunk.split()) <= 400 for chunk in chunks)


def _render_translated_detail(language):
    from datetime import date
    from unittest.mock import patch

    import streamlit as st

    from mtl_council_agent.app import queries, translations
    from mtl_council_agent.app.views import meetings

    st.session_state["lang"] = language
    item = {
        "id": 1, "meeting_id": 1, "meeting_date": date(2026, 3, 23),
        "item_number": "20.01", "section": "council", "title": "Approuver un contrat",
        "motion_number": "CM26 0001", "dossier_number": None,
        "vote_outcome": "adopted", "has_minutes": True,
        "department": None, "mover": None, "seconder": None,
        "decision_summary": "CONTEXTE\nLe projet améliore le parc.\nDESCRIPTION\nOriginal complet.",
    }
    translated = {"Approuver un contrat": "Approve a contract",
                  "Le projet améliore le parc.": "The project improves the park."}

    def query_result(query, *args):
        return item if query is queries.item else {}

    with patch.object(meetings, "run", side_effect=query_result), \
         patch.object(meetings, "_votes"), patch.object(meetings, "_explain"), \
         patch.object(translations, "english", side_effect=translated.get):
        meetings._item_view(1, from_feed=True)


def test_english_detail_shows_translated_title_context_and_french_original():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_render_translated_detail, args=("EN",)).run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "Approve a contract" in text
    assert "The project improves the park." in text
    assert "Original complet." in text
    assert at.expander[0].label == "Read the French original"
    assert any("Translated from the French original" in c.value for c in at.caption)


def test_french_detail_keeps_the_original_title_and_summary():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_render_translated_detail, args=("FR",)).run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "Approuver un contrat" in text
    assert "Original complet." in text
    assert "The project improves the park." not in text


def test_thousands_formats_keep_amounts_equal_but_do_not_reinterpret_french_decimals():
    assert translations.numbers_preserved("65 300 $", "$65,300")
    assert translations.numbers_preserved("65 300 $", "$65300")
    assert not translations.numbers_preserved("400,000 $", "$400000")


def test_reference_formatting_is_restored_only_for_the_same_number():
    assert translations.restore_references("CM26 0316", "CM26 316") == "CM26 0316"
    assert translations.restore_references("IM-DV-23-0001", "IM-DV-23-001") == "IM-DV-23-0001"
    assert translations.restore_references("IM-DV-23-0001", "IM-DV-23-002") == "IM-DV-23-002"


def test_numeric_protection_roundtrips_and_rejects_dropped_values():
    source = "CM26 0316 autorise 711 280 $ pour le projet IM-DV-23-0001, lot 6 387 943."
    masked, mapping = translations.protect_numbers(source)
    assert "711" not in masked
    assert "CM26" not in masked
    assert translations.unprotect_numbers(masked, mapping) == source
    assert translations.unprotect_numbers(masked.replace(next(iter(mapping)), ""), mapping) is None


def test_administrative_validation_is_not_presented_as_context():
    metadata = "VALIDATION\nIntervenant et sens de l'intervention 1234"
    assert translations.context_excerpt(metadata) == ""
