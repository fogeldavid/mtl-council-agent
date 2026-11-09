"""Each item's entry in the minutes: its text, its page, and the parts shown.

The fixture is three real entries from the 2026-09-21 minutes, as pdftotext
prints them (form feeds kept): the agenda's adoption, which follows the
meeting's opening pages; a contract preceded by a procedural "réunir"
resolution, its resolution number moved to the top of a page; and an
opposition motion with no "Et résolu", a debate and a roll call.
"""

from pathlib import Path

from mtl_council_agent import minutes_text
from mtl_council_agent.ingestion.minutes_parser import parse_minutes
from mtl_council_agent.ingestion.pdf_extract import strip_page_artifacts

FIXTURE = Path(__file__).parent / "fixtures" / "minutes_entries_excerpt.txt"


def _items():
    raw = FIXTURE.read_text()
    return {i.item_number: i for i in parse_minutes(strip_page_artifacts(raw), raw)}


def test_each_entry_starts_at_its_own_resolution_number():
    items = _items()
    assert items["03.01"].text.startswith("CM26 0922\n\nAdoption de l'ordre du jour")
    assert items["20.01"].text.startswith("CM26 0998\n\nAccorder un contrat")
    assert items["65.02"].text.startswith("CM26 1036\n\nMotion de l'Opposition officielle")


def test_opening_pages_and_procedural_resolutions_stay_out():
    items = _items()
    assert "PRÉSENCES" not in items["03.01"].text
    assert "réunir, pour fins" not in items["20.01"].text
    assert "____" not in items["65.02"].text


def test_page_is_where_the_entry_starts_even_at_a_page_top():
    items = _items()
    assert items["03.01"].page == 5
    # The resolution number follows a form feed: counting from the match
    # instead of the number put it on page 5.
    assert items["20.01"].page == 6
    assert items["65.02"].page == 6


def test_no_page_without_the_raw_text():
    raw = FIXTURE.read_text()
    assert all(i.page is None for i in parse_minutes(strip_page_artifacts(raw)))


def test_resolved_clauses_follow_et_resolu():
    clauses = minutes_text.resolved(_items()["20.01"].text)
    assert len(clauses) == 2
    assert clauses[0].startswith("1- d'accorder à 9125-5661 Québec inc. (Groupe Specs)")
    assert "309 086,79 $" in clauses[0]


def test_motion_clauses_follow_the_seconder_and_stop_at_the_debate():
    clauses = minutes_text.resolved(_items()["65.02"].text)
    assert clauses[0].startswith("1 - que le conseil municipal souligne le 15 septembre")
    assert clauses[-1].startswith("14 - que le conseil municipal réitère")
    assert not any("débat" in c for c in clauses)


def test_body_keeps_preamble_and_debate_but_not_movers_or_the_vote():
    body = minutes_text.body(_items()["65.02"].text)
    assert body[0].startswith("Attendu que l'Organisation des Nations Unies")
    assert "Un débat s'engage." in body
    assert not any(p.startswith(("Il est proposé par", "appuyé par")) for p in body)
    assert not any(p.startswith(("Votent en faveur", "VOTE", "Résultat")) for p in body)


def test_wrapped_compound_names_join_without_a_space():
    assert minutes_text.paragraphs("Julien Hénault-\nRatelle dépose") == [
        "Julien Hénault-Ratelle dépose"
    ]
    assert minutes_text.paragraphs("taxes incluses -\nAppel d'offres") == [
        "taxes incluses - Appel d'offres"
    ]


def test_a_filing_has_no_clauses_but_has_a_body():
    text = (
        "CM26 0932\n\nDépôt du rapport de la Commission\n\n"
        "Le conseiller Richard Deschamps dépose le rapport, et le conseil en prend acte."
    )
    assert minutes_text.resolved(text) == []
    assert minutes_text.body(text) == [
        "Le conseiller Richard Deschamps dépose le rapport, et le conseil en prend acte."
    ]


def test_search_text_leads_with_the_title():
    text = minutes_text.for_search("Motion sur la démocratie", _items()["65.02"].text)
    assert text.startswith("Motion sur la démocratie\n\nAttendu que")


def test_mover_is_the_motion_author_not_the_roll_call_request():
    motion = _items()["65.02"]
    # Marie Plourde moved only "de procéder à un vote enregistré".
    assert motion.mover == "Olivier Demers-Dubé"
    assert _items()["20.01"].mover == "Julien Hénault-Ratelle"


_REFERRAL = """
                                    ____________________________

CM26 0555

Motion de l'Opposition officielle - Motion pour un encadrement responsable

Attendu que la motion vise un encadrement responsable;

Il est proposé par   Olivier Demers-Dubé

appuyé par     Ericka Alneus

1- que le conseil municipal demande un encadrement responsable;

Un débat s'engage.

À 21 h 41,

Il est proposé par   Julien Hénault-Ratelle

appuyé par     Alexandre Teodoresco

de référer la présente motion à la Commission de la présidence pour en faire l'étude.

Adopté à l'unanimité.

À 21 h 54, la présidente du conseil confirme que la motion 65.03 est référée à la Commission de la
présidence, et il est

RÉSOLU

en conséquence.

65.03
"""


def test_a_motion_sent_to_a_committee_is_referred_not_adopted():
    item = parse_minutes(_REFERRAL)[0]
    assert item.vote_outcome == "referred"
    assert item.mover == "Olivier Demers-Dubé"


def test_a_filing_referred_to_a_committee_is_still_a_filing():
    text = (
        "\n____________________________\n\nCM26 0929\n\nDépôt du rapport public 2026\n\n"
        "Le leader dépose le rapport, et le conseil en prend acte.\n\n"
        "Le présent rapport est référé à la Commission sur l'inspecteur général.\n\n07.03\n"
    )
    assert parse_minutes(text)[0].vote_outcome == "noted"


def test_attendance_heading_without_a_colon_is_read_but_not_the_contents_line():
    from mtl_council_agent.ingestion.minutes_parser import parse_attendance

    text = (
        "TABLE DES MATIÈRES\n\nPRÉSENCES ........................ 3\n\n"
        "PRÉSENCES\n\nMesdames et messieurs\n"
        "Soraya Martinez Ferrada, Ericka Alneus et Cathy Wong\n\n\n"
        "ABSENCES AVEC MOTIF AU SENS DU RÈGLEMENT SUR LE TRAITEMENT DES MEMBRES DU\n"
        "CONSEIL :\n\n"
        "Benoit Langevin et Sonny Moroz\n\n\n"
        "AUTRES PRÉSENCES :\n\nAlain Dufort, Directeur général\n"
    )
    sittings = parse_attendance(text)
    assert len(sittings) == 1
    assert sittings[0].present == ["Soraya Martinez Ferrada", "Ericka Alneus", "Cathy Wong"]
    assert sittings[0].absent_excused == ["Benoit Langevin", "Sonny Moroz"]
