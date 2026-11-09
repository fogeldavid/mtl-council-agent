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
        "minutes_text": None, "minutes_page": None,
    }
    translated = {"Approuver un contrat": "Approve a contract",
                  "Le projet améliore le parc.": "The project improves the park."}

    def query_result(query, *args):
        return item if query is queries.item else {}

    with patch.object(meetings, "run", side_effect=query_result), \
         patch.object(meetings, "_votes"), \
         patch.object(translations, "english", side_effect=translated.get):
        meetings._item_view(1, from_feed=True)


def test_english_detail_shows_translated_title_context_and_french_original():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_render_translated_detail, args=("EN",)).run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "Approve a contract" in text
    assert "The project improves the park." in text
    assert "Original complet." not in text
    assert any("Machine-translated from French" in c.value for c in at.caption)
    # The switch shows the French in place, full decision summary included.
    next(b for b in at.button if b.label == "Show the French original").click().run()
    text = " ".join(m.value for m in at.markdown)
    assert "Approuver un contrat" in text and "Original complet." in text
    assert any(b.label == "Show the English translation" for b in at.button)


def _render_untranslated_detail(saved):
    from datetime import date
    from unittest.mock import patch

    from mtl_council_agent.app import queries, translations
    from mtl_council_agent.app.views import meetings

    item = {
        "id": 1, "meeting_id": 1, "meeting_date": date(2026, 3, 23), "item_number": "20.01",
        "section": "council", "title": "Approuver un contrat", "vote_outcome": "adopted",
        "has_minutes": True, "dossier_number": None, "motion_number": None,
        "department": None, "mover": None, "seconder": None,
        "decision_summary": "CONTEXTE\nLe projet améliore le parc.\nDESCRIPTION\nOriginal.",
        "minutes_text": None, "minutes_page": None,
    }

    def query_result(query, *args):
        return item if query is queries.item else {}

    with patch.object(meetings, "run", side_effect=query_result), \
         patch.object(meetings, "_votes"), \
         patch.object(translations, "english", side_effect=saved.get):
        meetings._item_view(1, from_feed=True)


def _captions(saved):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_render_untranslated_detail, args=(saved,)).run()
    assert not at.exception
    return " ".join(c.value for c in at.caption)


def test_nothing_translated_is_not_labelled_as_a_translation():
    captions = _captions({})
    assert "awaiting review" in captions
    assert "Machine-translated" not in captions


def test_a_translated_context_under_a_french_title_is_labelled():
    captions = _captions({"Le projet améliore le parc.": "The project improves the park."})
    assert "Machine-translated" in captions


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



def _render_declaration(saved):
    from datetime import date
    from unittest.mock import patch

    import streamlit as st

    from mtl_council_agent.app import queries, translations
    from mtl_council_agent.app.views import meetings

    # Inside the function: AppTest runs its source alone, without module globals.
    declaration = (
        "CM26 0924\n\nDéclaration soulignant la Journée\n\n"
        "Attendu que la journée est observée le 30 septembre;\n\n"
        "Il est proposé par   Soraya Martinez Ferrada\n\nappuyé par   Josué Corvil\n\n"
        "Et résolu :\n\n1- que la Ville observe la journée.\n\n"
        "Un débat s'engage.\n\nAdopté à l'unanimité."
    )
    st.session_state["lang"] = "EN"
    item = {
        "id": 1, "meeting_id": 1, "meeting_date": date(2026, 9, 21), "item_number": "15.02",
        "section": "council", "title": "Déclaration soulignant la Journée",
        "vote_outcome": "adopted_unanimous", "has_minutes": True, "dossier_number": None,
        "motion_number": "CM26 0924", "department": None, "mover": None, "seconder": None,
        "decision_summary": None, "minutes_text": declaration, "minutes_page": 8,
    }
    docs = {"minutes": "https://example.org/pv.pdf"}

    def query_result(query, *args):
        if query is queries.item:
            return item
        return docs if query is queries.meeting_documents else {}

    with patch.object(meetings, "run", side_effect=query_result), \
         patch.object(meetings, "_votes"), \
         patch.object(translations, "english", side_effect=saved.get):
        meetings._item_view(1, from_feed=True)


def _declaration(saved):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_render_declaration, args=(saved,)).run()
    assert not at.exception
    return at


def test_an_item_without_a_summary_shows_its_minutes_instead():
    at = _declaration({})
    text = " ".join(m.value for m in at.markdown)
    assert "What council adopted" in text
    assert "1- que la Ville observe la journée." in text
    assert "No decision summary on file" not in " ".join(c.value for c in at.caption)
    assert "Full entry in the minutes" in [e.label for e in at.expander]
    assert "Soraya Martinez Ferrada" not in text


def test_minutes_show_in_english_only_when_every_paragraph_is_translated():
    clause = "1- que la Ville observe la journée."
    full = _declaration({clause: "1- that the City observe the day."})
    assert "1- that the City observe the day." in " ".join(m.value for m in full.markdown)
    partial = _declaration({})
    assert "English translation not ready yet" in " ".join(c.value for c in partial.caption)


def test_minutes_link_opens_at_the_item_page():
    at = _declaration({})
    buttons = at.get("link_button")
    assert any(b.proto.url == "https://example.org/pv.pdf#page=8" for b in buttons)
    assert any("page 8" in b.proto.label for b in buttons)


def _render_rejected_motion():
    from datetime import date
    from unittest.mock import patch

    import streamlit as st

    from mtl_council_agent.app import queries, translations
    from mtl_council_agent.app.views import meetings

    st.session_state["lang"] = "EN"
    motion = (
        "CM26 1036\n\nMotion de l'Opposition officielle\n\n"
        "Il est proposé par   Olivier Demers-Dubé\n\nappuyé par   Marie Plourde\n\n"
        "1 - que le conseil municipal souligne le 15 septembre;\n\n"
        "Un débat s'engage."
    )
    item = {
        "id": 1, "meeting_id": 1, "meeting_date": date(2026, 9, 21), "item_number": "65.02",
        "section": "council", "title": "Motion de l'Opposition officielle",
        "vote_outcome": "rejected", "has_minutes": True, "dossier_number": None,
        "motion_number": "CM26 1036", "department": None, "mover": None, "seconder": None,
        "decision_summary": None, "minutes_text": motion, "minutes_page": 85,
    }

    def query_result(query, *args):
        return item if query is queries.item else {}

    with patch.object(meetings, "run", side_effect=query_result), \
         patch.object(meetings, "_votes"), \
         patch.object(translations, "english", return_value=None):
        meetings._item_view(1, from_feed=True)


def test_a_rejected_motion_is_not_headed_as_adopted():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_render_rejected_motion).run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "What council voted down" in text
    assert "What council adopted" not in text


def test_half_converted_amounts_get_english_commas():
    from mtl_council_agent.app.translations import fix_number_grouping

    assert fix_number_grouping("CDN-117-2630 $8,999 704.92 CMS") == "CDN-117-2630 $8,999,704.92 CMS"
    assert fix_number_grouping("a total of $451 000.94, including taxes") == (
        "a total of $451,000.94, including taxes"
    )
    assert fix_number_grouping("support of $877 312 to") == "support of $877,312 to"


def test_half_converted_lot_numbers_keep_their_spaces():
    from mtl_council_agent.app.translations import fix_number_grouping

    assert fix_number_grouping("parts of Lots 1,336 164, 1,336 166 and 1,336 220 of the") == (
        "parts of Lots 1 336 164, 1 336 166 and 1 336 220 of the"
    )


def test_numbers_already_well_formed_are_left_alone():
    from mtl_council_agent.app.translations import fix_number_grouping

    for text in (
        "On August 31, 2026, council adopted CM25 0769.",
        "premises 314, 315 and 317",
        "$13,141,353.68 and lots 2,245,625",
        "for 2026 125 projects",
    ):
        assert fix_number_grouping(text) == text
