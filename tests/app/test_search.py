from mtl_council_agent.app import queries


def axis_vector(axis: int) -> str:
    """A unit vector along one axis; the seed gives each chunk its own axis."""
    vector = [0.0] * 768
    vector[axis] = 1.0
    return str(vector)


def ids(rows):
    return [r["id"] for r in rows]


def test_exact_words_match_french_word_forms(conn):
    # French stemming: the singular "berge" finds "berges".
    assert ids(queries.search(conn, "Veille")) == [10]
    assert ids(queries.search(conn, "berge")) == [11]


def test_exact_snippet_marks_the_match(conn):
    (row,) = queries.search(conn, "Ouranos")
    assert queries.MARK_START + "Ouranos" + queries.MARK_END in row["snippet"]


def test_no_text_lists_filtered_items_newest_first(conn):
    assert ids(queries.search(conn)) == [20, 10, 11, 12, 13]


def test_outcome_filter(conn):
    assert ids(queries.search(conn, outcomes=["rejected"])) == [11]
    # Items with no outcome yet are selectable too.
    assert ids(queries.search(conn, outcomes=["unknown"])) == [20]


def test_section_filter(conn):
    assert ids(queries.search(conn, section="agglomeration_orientation")) == [13]


def test_meeting_filter(conn):
    assert ids(queries.search(conn, meeting_id=2)) == [20]


def test_department_filter(conn):
    assert ids(queries.search(conn, department="Service de l'eau")) == [20]
    assert "Service de l'eau" in queries.departments(conn)


def test_councillor_filter_covers_moving_and_voting(conn):
    # Plourde moved 11 and dissented on 10.
    assert sorted(ids(queries.search(conn, official_id=3))) == [10, 11]
    # McCray only abstained on 12.
    assert ids(queries.search(conn, official_id=5)) == [12]


def test_filters_combine(conn):
    assert ids(queries.search(conn, official_id=3, outcomes=["rejected"])) == [11]
    assert ids(queries.search(conn, "Veille", outcomes=["rejected"])) == []


def test_meaning_ranks_by_nearest_chunk(conn):
    rows = queries.search(conn, "climate", mode="meaning", embedding=axis_vector(2))
    assert ids(rows)[0] == 12
    assert "Ouranos" in rows[0]["snippet"]


def test_meaning_applies_filters_before_limiting(conn):
    rows = queries.search(
        conn, "anything", mode="meaning", embedding=axis_vector(2), outcomes=["rejected"]
    )
    assert ids(rows) == [11]
