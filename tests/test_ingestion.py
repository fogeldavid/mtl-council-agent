from collections import Counter
from pathlib import Path

from mtl_council_agent.ingestion import linker
from mtl_council_agent.ingestion.agenda_parser import (
    COUNCIL,
    ORIENTATION,
    AgendaItem,
    parse_agenda,
)
from mtl_council_agent.ingestion.bundle_parser import (
    _trim_to_decision_summary,
    split_bundle_by_dossier,
)
from mtl_council_agent.ingestion.linker import link_items
from mtl_council_agent.ingestion.minutes_parser import (
    MinutesItem,
    parse_attendance,
    parse_minutes,
)
from mtl_council_agent.ingestion.pdf_extract import strip_page_artifacts

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


def test_agenda_parses_bridge_item():
    items = parse_agenda(_read("agenda_sample.txt"))
    bridge = next(i for i in items if i.dossier_number == "1264139001")
    assert bridge.item_number == "20.01"
    assert "urbanisme" in bridge.department.lower()
    assert " ," not in bridge.department
    assert "pont Guy-Lafleur" in bridge.title


def test_items_starting_a_new_page_are_not_dropped():
    # pdftotext puts a form feed at every page break, so an item landing at the
    # top of a page reads as "\f20.05  Service ...". A bare ^ anchor missed
    # those, silently dropping 22% of items from this agenda.
    text = _read("agenda_sample.txt")
    assert "\f" in text, "fixture must retain page breaks for this to mean anything"

    items = parse_agenda(text)
    after_page_break = [i for i in items if i.dossier_number == "1268848007"]
    assert after_page_break, "item at a page boundary was dropped"
    assert after_page_break[0].item_number == "20.05"


def test_item_numbers_repeat_within_one_agenda():
    # The council section and the agglomeration-orientation section run
    # independent series that both use 20.01, 20.02, ... Anything keying on
    # item number alone will silently collapse them.
    items = parse_agenda(_read("agenda_sample.txt"))
    counts = Counter(i.item_number for i in items)
    repeated = {number: n for number, n in counts.items() if n > 1}
    assert repeated, "expected repeated item numbers in a real agenda"

    for number in repeated:
        dossiers = {i.dossier_number for i in items if i.item_number == number}
        assert len(dossiers) > 1, f"{number} repeats but points at one dossier"


def test_agenda_procedural_items_have_no_dossier():
    items = parse_agenda(_read("agenda_sample.txt"))
    question_period = next(i for i in items if i.item_number == "01.01")
    assert question_period.dossier_number is None
    assert "Période de questions" in question_period.title


def test_minutes_bridge_item_has_correct_mover_not_the_grouping_motion():
    items = parse_minutes(_read("minutes_sample.txt"))
    bridge = next(i for i in items if i.dossier_number == "1264139001")
    # Real gotcha: a procedural "réunir, pour fins d'étude" grouping motion
    # precedes the item's own motion in the text, with its own (different)
    # mover/seconder -- the parser must pick the item's OWN vote, not the
    # grouping motion's.
    assert bridge.mover == "Julien Hénault-Ratelle"
    assert bridge.seconder == "Alan DeSousa"
    assert bridge.motion_number == "CM26 0677"
    assert bridge.vote_outcome == "adopted_unanimous"


def test_minutes_orientation_items_are_tagged_with_their_inner_number():
    items = parse_minutes(_read("minutes_sample.txt"))
    # These use a two-line footer ("dossier\n80.01 (NN.NN)"). The inner
    # number is what the agenda lists them under, and the section tag keeps
    # them apart from the council item with the same number.
    assert all(not i.item_number.startswith("80.") for i in items)
    police = next(i for i in items if i.dossier_number == "1267026001")
    assert police.section == ORIENTATION
    assert police.item_number == "20.01"
    bridge = next(i for i in items if i.dossier_number == "1264139001")
    assert bridge.section == COUNCIL
    assert bridge.item_number == "20.01"


def test_agenda_items_after_the_orientation_banner_are_tagged():
    items = parse_agenda(_read("agenda_sample.txt"))
    by_dossier = {i.dossier_number: i for i in items if i.dossier_number}
    assert by_dossier["1264139001"].section == COUNCIL
    assert by_dossier["1267026001"].section == ORIENTATION
    # Within each section, the item number is unique.
    keys = [(i.section, i.item_number) for i in items]
    assert len(keys) == len(set(keys))


def test_page_footer_glued_to_a_banner_stays_out_of_titles():
    # pdftotext sometimes prints a page's footer on the same line as the next
    # page's section banner. Neither belongs in the item title before it.
    text = (
        "20.40     Service de l'eau - 1266848003\n\n"
        "Accorder un contrat pour des travaux de réfection\n"
        "Page 25 80 – Conseil d'agglomération - Dossiers pour orientation\n\n\n"
        "20 – Affaires contractuelles\n\n\n"
        "20.01     Service de police de Montréal - 1267026001\n\n"
        "Conclure une entente-cadre\n"
    )
    for source in (text, strip_page_artifacts(text)):
        items = parse_agenda(source)
        assert items[0].title == "Accorder un contrat pour des travaux de réfection"
        assert items[0].section == COUNCIL
        assert items[1].section == ORIENTATION


def test_minutes_bare_footer_closes_a_dossierless_item():
    # Adopting the agenda, declarations and councillors' motions end with a
    # bare "65.01" footer. Missing it merged each such item into the next.
    items = parse_minutes(_read("minutes_sample.txt"))
    agenda_adoption = next(i for i in items if i.item_number == "03.01")
    assert agenda_adoption.dossier_number is None
    assert agenda_adoption.motion_number == "CM26 0584"
    # No "Adopté" line: the chair's "il est RÉSOLU en conséquence" closes it.
    assert agenda_adoption.vote_outcome == "adopted"


def test_minutes_outcomes_distinguish_unanimous_from_filings():
    items = parse_minutes(_read("minutes_sample.txt"))
    bridge = next(i for i in items if i.dossier_number == "1264139001")
    assert bridge.vote_outcome == "adopted_unanimous"
    filing = next(i for i in items if i.motion_number == "CM26 0596")
    assert filing.vote_outcome == "noted"
    notice = next(i for i in items if i.item_number == "41.01")
    assert notice.vote_outcome == "noted"


def test_attendance_is_recorded_per_sitting():
    # The 13 h and 19 h sittings have different rolls: Danielle Myrand is
    # present at the first and absent from the second.
    sittings = parse_attendance(_read("minutes_sample.txt"))
    assert len(sittings) == 2
    first, second = sittings
    assert "Danielle Myrand" in first.present
    assert "Danielle Myrand" in second.absent_excused
    assert second.absent_unexcused == ["Sterling Downey"]
    # "(par téléconférence)" is how someone attended, not part of the name,
    # and staff under "AUTRES PRÉSENCES" are not members.
    assert "Jean François Lalonde" in second.present
    assert not any("Tani-Moore" in n for n in first.present + second.present)
    # Every sitting accounts for all 65 council members.
    for sitting in sittings:
        total = sitting.present + sitting.absent_excused + sitting.absent_unexcused
        assert len(set(total)) == 65


def test_items_carry_the_sitting_they_were_voted_in():
    items = parse_minutes(_read("minutes_sample.txt"))
    police = next(i for i in items if i.dossier_number == "1267026001")
    bridge = next(i for i in items if i.dossier_number == "1264139001")
    assert police.sitting == 0
    assert bridge.sitting == 1


def _votes_excerpt() -> list[MinutesItem]:
    return parse_minutes(strip_page_artifacts(_read("minutes_votes_excerpt.txt")))


def test_roll_with_a_wrapped_preamble_and_honorifics():
    # 2026-01-28: the "(À moins d'une indication autre ...)" note wraps onto a
    # second line, and names carry "M."/"Mme". The roll must still come out
    # as the 63 members present.
    sittings = parse_attendance(strip_page_artifacts(_read("minutes_votes_excerpt.txt")))
    assert len(sittings[0].present) == 63
    assert "Mme Carla Beauvais" in sittings[0].present
    assert "M. François Limoges" in sittings[0].absent_excused


def test_dissent_list_survives_a_page_header_in_the_middle():
    # 2026-03-23, item 20.06: a running page header splits the 24-name list.
    item = next(i for i in _votes_excerpt() if i.item_number == "20.06")
    assert item.vote_outcome == "adopted_majority"
    assert len(item.dissenters) == 24
    assert item.dissenters[0] == "Ericka Alneus"
    assert item.dissenters[-1] == "Cathy Wong"
    assert "Sylvain Ouellet" in item.dissenters and "Jocelyn Pauzé" in item.dissenters


def test_declared_conflict_of_interest_is_an_abstention():
    item = next(i for i in _votes_excerpt() if i.item_number == "20.29")
    assert item.abstainers == ["Christopher McCray"]
    assert item.vote_outcome == "adopted_unanimous"


def test_roll_call_names_everyone_and_ignores_a_late_arrival_note():
    # 2026-04-20, motion 65.01: an "Ouverture des portes" note (a member who
    # arrived late saying how she'd have voted) sits inside the vote block.
    item = next(
        i for i in _votes_excerpt() if i.item_number == "65.01" and i.vote_outcome == "rejected"
    )
    call = item.roll_call
    assert (len(call.voted_for), len(call.voted_against)) == (23, 37)
    assert (call.declared_for, call.declared_against) == (23, 37)
    assert "Hénault-Ratelle" in call.voted_against  # rejoined across a line wrap
    assert "Soraya Martinez Ferrada" in call.voted_against
    assert not any("Carhuallanqui" in n for n in call.voted_for + call.voted_against)


def test_roll_call_with_nobody_against():
    item = next(i for i in _votes_excerpt() if i.item_number == "65.03")
    assert len(item.roll_call.voted_for) == 60
    assert item.roll_call.voted_against == []


def test_amendment_roll_call_is_not_the_items_vote():
    # 2026-05-11, motion 65.01: a roll call on an amendment, then one on the
    # amended motion. Only the last is the motion's own vote.
    item = next(
        i
        for i in _votes_excerpt()
        if i.item_number == "65.01" and i.vote_outcome == "adopted_majority"
    )
    assert (len(item.roll_call.voted_for), len(item.roll_call.voted_against)) == (37, 25)


def test_roll_call_declaration_beats_a_contradictory_stamp():
    # 2026-03-23, item 44.01: the roll call went 38-24 and the chair declared
    # it "adopté à la majorité"; the minutes then stamp "Adopté à l'unanimité".
    item = next(i for i in _votes_excerpt() if i.item_number == "44.01")
    assert item.vote_outcome == "adopted_majority"
    assert len(item.roll_call.voted_against) == 24


def test_withdrawn_items_without_a_footer_are_recorded():
    text = (
        "d'adopter l'ordre du jour en y retirant les points 15.03, 30.06 et\n"
        "80.01 (30.05) et en y ajoutant le point 7.08.\n\nAdopté à l'unanimité.\n\n03.01\n\n"
        "La leader de l'Opposition officielle retire le point 65.04 conformément à\n"
        "l'article 88 du Règlement.\n"
    )
    items = {(i.section, i.item_number): i for i in parse_minutes(text)}
    for key in [
        (COUNCIL, "15.03"),
        (COUNCIL, "30.06"),
        (ORIENTATION, "30.05"),
        (COUNCIL, "65.04"),
    ]:
        assert items[key].vote_outcome == "withdrawn", key
    assert items[(COUNCIL, "03.01")].vote_outcome == "adopted_unanimous"


def test_bundle_trims_at_the_endorsement_when_there_is_no_approval():
    # Bylaws and transit-authority items stop at the file officer's
    # endorsement ("ENDOSSÉ PAR  Le : 2026-08-05") with no directors'
    # approval. Without this they fell through to a 40KB cap of attachments.
    body = _read("bundle_endorsement_only.txt")
    trimmed = _trim_to_decision_summary(body)
    assert "SOMMAIRE DÉCISIONNEL" in trimmed
    assert "ENDOSSÉ PAR" in trimmed
    assert "Sommaire décisionnel du règlement" not in trimmed  # the attachment
    assert len(trimmed) < 5000


def test_bundle_keeps_each_summary_and_drops_attachments_between_them():
    # An addendum's summary, then its attachment (a contract), then the
    # original summary with the directors' approval.
    body = (
        "Dossier # : 1254501006\nIl est recommandé : d'approuver l'addenda.\n"
        "SOMMAIRE ADDENDA\nContenu de l'addenda.\n"
        "RESPONSABLE DU DOSSIER\n\n\nNom\nTél : 514\n\n\n\n\n"
        + "ADDENDA À UNE PROMESSE DE VENTE " * 400
        + "\nRECOMMANDATION\nSOMMAIRE DÉCISIONNEL\nContexte original.\n"
        "RESPONSABLE DU DOSSIER     ENDOSSÉ PAR     Le : 2026-05-01\n"
        "APPROBATION\nApprouvé le : 2026-05-02    Approuvé le : 2026-05-02\n\n"
        "Grille d'analyse Montréal 2030\nchecklist\n"
    )
    trimmed = _trim_to_decision_summary(body)
    assert "Contenu de l'addenda." in trimmed
    assert "Contexte original." in trimmed
    assert "Approuvé le : 2026-05-02" in trimmed
    assert "PROMESSE DE VENTE" not in trimmed
    assert "Grille d'analyse" not in trimmed


def test_bundle_splits_into_per_item_chunks():
    chunks = split_bundle_by_dossier(_read("bundle_sample_excerpt.txt"))
    assert set(chunks) == {"1269902004", "1269902007", "1267639001"}
    assert len(chunks["1269902004"]) > 100


def test_bundle_trims_attachments_after_the_signoff_block():
    # Everything after the sign-off is attachments: checklists, contracts, and
    # financial spreadsheets whose "0.00$" padding is worthless to embed.
    raw = _read("bundle_sample_excerpt.txt")
    chunks = split_bundle_by_dossier(raw)

    for dossier, body in chunks.items():
        assert len(body) < len(raw), f"{dossier} kept the whole slice"
        # The narrative that answers "why" has to survive the trim.
        assert "Dossier # :" in body

    trimmed = chunks["1269902004"]
    assert "Approuvé le" in trimmed or "Approuve le" in trimmed


def test_linker_joins_all_three_sources_for_bridge_item():
    agenda_items = parse_agenda(_read("agenda_sample.txt"))
    minutes_items = parse_minutes(_read("minutes_sample.txt"))
    # Full bundle text isn't checked in (too large); reuse the excerpt, which
    # doesn't include the bridge item, to prove linking degrades gracefully
    # to a null decision_summary rather than erroring when a dossier isn't
    # present in the bundle chunk map.
    linked = link_items(agenda_items, minutes_items, _read("bundle_sample_excerpt.txt"))

    bridge = next(i for i in linked if i.dossier_number == "1264139001")
    assert bridge.mover == "Julien Hénault-Ratelle"
    assert bridge.decision_summary is None
    assert "urbanisme" in bridge.department.lower()

    other = next(i for i in linked if i.dossier_number == "1269902004")
    assert other.decision_summary is not None


def _agenda(number, dossier, section=COUNCIL):
    return AgendaItem(
        item_number=number, department="", dossier_number=dossier, title="t", section=section
    )


def _minutes(number, dossier, motion, section=COUNCIL, outcome="adopted_unanimous"):
    return MinutesItem(
        item_number=number,
        dossier_number=dossier,
        motion_number=motion,
        mover=None,
        seconder=None,
        vote_outcome=outcome,
        section=section,
    )


def test_shared_dossier_does_not_copy_one_vote_onto_two_items():
    # June 2026: filing 07.07 and resolution 30.19 share a dossier. Joining
    # on dossier alone gave the filing 30.19's resolution number and vote.
    agenda = [_agenda("07.07", "1266254001"), _agenda("30.19", "1266254001")]
    minutes = [
        _minutes("07.07", "1266254001", "CM26 0596", outcome="noted"),
        _minutes("30.19", "1266254001", "CM26 0718"),
    ]
    filing, resolution = link_items(agenda, minutes, None)
    assert (filing.motion_number, filing.vote_outcome) == ("CM26 0596", "noted")
    assert (resolution.motion_number, resolution.vote_outcome) == (
        "CM26 0718",
        "adopted_unanimous",
    )


def test_item_missing_from_the_minutes_gets_no_neighbours_vote():
    agenda = [_agenda("07.07", "1266254001"), _agenda("30.19", "1266254001")]
    minutes = [_minutes("30.19", "1266254001", "CM26 0718")]
    filing, _ = link_items(agenda, minutes, None)
    assert filing.motion_number is None
    assert filing.vote_outcome == "unknown"


def test_dossierless_items_join_on_section_and_number():
    agenda = [_agenda("65.01", None), _agenda("20.58", "1269999001", ORIENTATION)]
    minutes = [
        _minutes("65.01", None, "CM26 0734"),
        _minutes("20.58", None, "CM26 0656", section=ORIENTATION),
    ]
    motion, orientation = link_items(agenda, minutes, None)
    assert motion.motion_number == "CM26 0734"
    assert orientation.motion_number == "CM26 0656"


def test_orientation_votes_stay_off_when_disabled(monkeypatch):
    monkeypatch.setattr(linker, "ATTACH_ORIENTATION_VOTES", False)
    agenda = [_agenda("20.01", "1267026001", ORIENTATION)]
    minutes = [_minutes("20.01", "1267026001", "CM26 0599", section=ORIENTATION)]
    (orientation,) = link_items(agenda, minutes, None)
    assert orientation.motion_number is None
    assert orientation.vote_outcome == "unknown"


def test_orientation_votes_attach_to_the_right_item():
    agenda = [_agenda("20.01", "1264139001"), _agenda("20.01", "1267026001", ORIENTATION)]
    minutes = [
        _minutes("20.01", "1267026001", "CM26 0599", section=ORIENTATION),
        _minutes("20.01", "1264139001", "CM26 0677"),
    ]
    council, orientation = link_items(agenda, minutes, None)
    assert council.motion_number == "CM26 0677"
    assert orientation.motion_number == "CM26 0599"
    assert orientation.section == ORIENTATION


def test_barred_member_is_a_distinct_absence():
    # 2026-04-20: a member lost the right to sit under article 502 of the
    # municipal elections act. Counting him as present or dropping him both
    # misstate the roll.
    text = (
        "PRÉSENCES :\n\nMesdames et messieurs\nSoraya Martinez Ferrada et Ericka Alneus\n\n"
        "ABSENCES AVEC MOTIF AU SENS DU RÈGLEMENT SUR LE TRAITEMENT DES MEMBRES DU\n"
        "CONSEIL :\n\nDanielle Myrand\n\n"
        "ABSENCE - PERTE DU DROIT D'ASSISTER À LA SÉANCE EN VERTU DE L'ARTICLE 502 DE LA\n"
        "LOI SUR LES ÉLECTIONS ET LES RÉFÉRENDUMS DANS LES MUNICIPALITÉS (RLRQ, CHAPITRE\n"
        "E-2.2) :\n\nMauro Barone\n\nAUTRES PRÉSENCES :\n\nStaff\n"
    )
    (sitting,) = parse_attendance(text)
    assert sitting.present == ["Soraya Martinez Ferrada", "Ericka Alneus"]
    assert sitting.absent_excused == ["Danielle Myrand"]
    assert sitting.absent_barred == ["Mauro Barone"]
