from mtl_council_agent.ingestion.pdf_extract import strip_page_artifacts


def test_page_footers_and_counters_are_removed():
    text = "Texte avant.\n                     Page 7\n\fTexte après.\n            6/24\n\fSuite"
    cleaned = strip_page_artifacts(text)
    assert "Page 7" not in cleaned
    assert "6/24" not in cleaned
    assert "\f" not in cleaned
    assert "Texte avant." in cleaned and "Suite" in cleaned


def test_footer_glued_to_a_banner_keeps_the_banner():
    cleaned = strip_page_artifacts("fin du titre\n     Page 25 80 – Conseil d'agglomération\n")
    assert "Page 25" not in cleaned
    assert "80 – Conseil d'agglomération" in cleaned


def test_minutes_running_header_is_removed():
    text = (
        "                     Sylvain Ouellet\n"
        "Séance ordinaire du conseil municipal du lundi 23 mars 2026 à 13 h"
        "                                58\n"
        "                     Jocelyn Pauzé\n"
    )
    cleaned = strip_page_artifacts(text)
    assert "Séance ordinaire" not in cleaned
    assert "Sylvain Ouellet" in cleaned and "Jocelyn Pauzé" in cleaned


def test_prose_mentioning_a_sitting_is_kept():
    # Only the header line (which ends in a page number) goes.
    text = (
        "Séance ordinaire du conseil municipal du lundi 23 mars 2026 à 13 h, "
        "tenue à l'hôtel de ville."
    )
    assert strip_page_artifacts(text) == text


def test_bundle_running_header_is_removed():
    text = "Contexte\n      Système de gestion des décisions des instances\nSOMMAIRE DÉCISIONNEL"
    cleaned = strip_page_artifacts(text)
    assert "Système de gestion" not in cleaned
    assert "SOMMAIRE DÉCISIONNEL" in cleaned


def test_wrapped_bundle_header_is_removed():
    text = (
        "Direction générale\n\n"
        "                             Système de gestion des décisions des\n"
        "                             instances\n"
        "                             SOMMAIRE DÉCISIONNEL\n"
    )
    cleaned = strip_page_artifacts(text)
    assert "Système de gestion" not in cleaned
    assert "instances" not in cleaned
    assert "SOMMAIRE DÉCISIONNEL" in cleaned
