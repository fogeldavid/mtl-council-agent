from pathlib import Path

from mtl_council_agent.ingestion.agenda_parser import parse_agenda
from mtl_council_agent.ingestion.bundle_parser import split_bundle_by_dossier
from mtl_council_agent.ingestion.linker import link_items
from mtl_council_agent.ingestion.minutes_parser import parse_minutes

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


def test_agenda_parses_bridge_item():
    items = parse_agenda(_read("agenda_sample.txt"))
    bridge = next(i for i in items if i.dossier_number == "1264139001")
    assert bridge.item_number == "20.01"
    assert "urbanisme" in bridge.department.lower()
    assert "pont Guy-Lafleur" in bridge.title


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
    assert bridge.vote_outcome == "adopted"


def test_minutes_agglomeration_orientation_items_excluded():
    items = parse_minutes(_read("minutes_sample.txt"))
    # These use a two-line footer format ("dossier\n80.01 (NN.NN)") and
    # belong to the agglomeration council, out of this project's scope --
    # they must not leak into the council items and must not cause
    # neighboring council items to bleed into each other.
    assert all(not i.item_number.startswith("80.") for i in items)


def test_bundle_splits_into_per_item_chunks():
    chunks = split_bundle_by_dossier(_read("bundle_sample_excerpt.txt"))
    assert set(chunks) == {"1269902004", "1269902007", "1267639001"}
    assert len(chunks["1269902004"]) > 100


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

    other = next(i for i in linked if i.dossier_number == "1269902004")
    assert other.decision_summary is not None
