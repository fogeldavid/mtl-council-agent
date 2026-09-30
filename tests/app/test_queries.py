from datetime import date

from mtl_council_agent.agent.tools import get_vote_detail
from mtl_council_agent.app import queries


def test_stats_count_the_record(conn):
    s = queries.stats(conn)
    assert (s["meetings"], s["items"], s["recorded_votes"], s["members"]) == (2, 5, 7, 5)
    assert s["latest_meeting"] == date(2026, 9, 21)


def test_contested_votes_are_items_with_named_opponents(conn):
    rows = queries.contested_votes(conn, limit=5)
    assert [r["id"] for r in rows] == [10, 11]
    motion = next(r for r in rows if r["id"] == 11)
    assert (motion["votes_for"], motion["votes_against"], motion["roll_call"]) == (2, 2, True)
    dissent = next(r for r in rows if r["id"] == 10)
    assert dissent["roll_call"] is False


def test_meetings_list_newest_first_with_minutes_flag(conn):
    rows = queries.meetings(conn)
    assert [r["meeting_date"] for r in rows] == [date(2026, 9, 21), date(2026, 3, 23)]
    assert [r["has_minutes"] for r in rows] == [False, True]
    assert [r["items"] for r in rows] == [1, 4]


def test_meeting_items_keep_agenda_order_and_section(conn):
    rows = queries.meeting_items(conn, 1)
    assert [r["item_number"] for r in rows] == ["20.06", "65.02", "20.29", "20.01"]
    assert rows[-1]["section"] == "agglomeration_orientation"


def test_attendance_per_sitting(conn):
    assert queries.meeting_attendance(conn, 1) == [
        {"sitting": 0, "present": 5, "absent": 0},
        {"sitting": 1, "present": 4, "absent": 1},
    ]
    assert queries.meeting_attendance(conn, 2) == []


def test_meeting_documents_by_type(conn):
    docs = queries.meeting_documents(conn, 1)
    assert set(docs) == {"agenda", "minutes"}


def test_item_detail_names_mover_and_meeting(conn):
    it = queries.item(conn, 10)
    assert it["mover"] == "Julien Hénault-Ratelle"
    assert it["meeting_date"] == date(2026, 3, 23)
    assert queries.item(conn, 999) is None


def test_vote_detail_keeps_recorded_and_inferred_apart(conn):
    # Majority vote with a dissent list: the two dissenters are recorded;
    # "for" is everyone present at that sitting minus them, and inferred.
    detail = get_vote_detail(conn, 10)
    assert sorted(detail.recorded_against) == ["Ericka Alneus", "Marie Plourde"]
    assert detail.present_at_sitting == 5
    assert len(detail.inferred_for) == 3
    roll = get_vote_detail(conn, 11)
    assert roll.inferred_for is None
    assert len(roll.recorded_for) == 2


def test_councillors_are_roster_members_sorted_by_surname(conn):
    names = [r["name"] for r in queries.councillors(conn)]
    assert names == [
        "Ericka Alneus",
        "Julien Hénault-Ratelle",
        "Soraya Martinez Ferrada",
        "Christopher McCray",
        "Marie Plourde",
    ]


def test_councillor_profile_counts_attendance_and_motions(conn):
    p = queries.councillor(conn, 5)
    assert (p["sittings_present"], p["absent_excused"], p["sittings_total"]) == (1, 1, 2)
    j = queries.councillor(conn, 2)
    assert (j["moved"], j["seconded"]) == (3, 0)


def test_roll_calls_show_the_party_position_beside_the_member(conn):
    rows = queries.councillor_roll_calls(conn, 3)
    assert len(rows) == 1
    assert (rows[0]["position"], rows[0]["party_position"]) == ("for", "for")
    mayor = queries.councillor_roll_calls(conn, 1)
    assert (mayor[0]["position"], mayor[0]["party_position"]) == ("against", "against")


def test_other_positions_are_dissents_and_abstentions(conn):
    plourde = queries.councillor_other_positions(conn, 3)
    assert [(r["id"], r["source"]) for r in plourde] == [(10, "dissent_list")]
    mccray = queries.councillor_other_positions(conn, 5)
    assert [(r["id"], r["position"]) for r in mccray] == [(12, "abstained")]


def test_motions_list_moved_and_seconded(conn):
    rows = queries.councillor_motions(conn, 3)
    assert [(r["id"], r["role"]) for r in rows] == [(11, "moved")]


def test_item_knows_whether_its_meetings_minutes_are_in(conn):
    # "unknown" reads as "no minutes yet" only when that's true; otherwise the
    # minutes simply record no decision (a question period, an announcement).
    assert queries.item(conn, 10)["has_minutes"] is True
    assert queries.item(conn, 20)["has_minutes"] is False
