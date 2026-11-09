"""Offline coverage of the Decisions page: latest first, search, filters, and coming back."""

from streamlit.testing.v1 import AppTest


def _render_decisions():
    from datetime import date
    from unittest.mock import patch

    import streamlit as st

    from mtl_council_agent.app import queries
    from mtl_council_agent.app.views import decisions

    rows = [{
        "id": i, "meeting_date": date(2026, 3, 23), "item_number": f"20.{i:02}",
        "section": "council", "title": f"Decision {i}", "department": "Water",
        "vote_outcome": "adopted_majority", "has_minutes": True, "motion_number": None,
        "dossier_number": None, "snippet": None,
    } for i in range(1, 26)]
    calls = st.session_state.setdefault("calls", [])

    def fake_run(query, *args, **kwargs):
        if query is queries.meetings:
            return [{"id": 1, "meeting_date": date(2026, 3, 23), "has_minutes": True}]
        if query is queries.councillors:
            return [{"id": 3, "name": "Marie Plourde"}]
        if query is queries.departments:
            return ["Water"]
        assert query is queries.search
        calls.append((args, kwargs))
        if args and args[0] == "absent":
            return []
        return rows[:kwargs["limit"]]

    def detail(item_id, from_feed=False):
        from mtl_council_agent.app.common import go

        assert from_feed
        st.write(f"Detail {item_id}")
        if st.button("← Back to decisions"):
            go()

    with patch.object(decisions, "run", side_effect=fake_run), \
         patch.object(decisions, "_query_vector", return_value="[0]"), \
         patch.object(decisions.meetings, "_item_view", side_effect=detail):
        decisions.render()


def _run():
    return AppTest.from_function(_render_decisions, default_timeout=30).run()


def test_opens_on_the_latest_decisions_with_extra_filters_folded_away():
    at = _run()
    assert not at.exception
    assert len(at.text_input) == 1
    assert at.checkbox[0].label == "Decided only" and at.checkbox[0].value is True
    assert at.expander[0].label == "More filters"
    assert any("25 decisions" in m.value for m in at.markdown)
    assert len([b for b in at.button if (b.key or "").startswith("open_decision_")]) == 20
    _, kwargs = at.session_state["calls"][-1]
    assert kwargs["decided"] is True


def test_show_more_and_unticking_decided():
    at = _run()
    next(b for b in at.button if b.label == "Show more").click().run()
    assert len([b for b in at.button if (b.key or "").startswith("open_decision_")]) == 25
    at.checkbox[0].uncheck().run()
    assert not at.exception
    assert at.session_state["calls"][-1][1]["decided"] is False
    # A new search starts from the top again.
    assert len([b for b in at.button if (b.key or "").startswith("open_decision_")]) == 20


def test_one_box_shows_matches_first_then_related_by_meaning():
    at = _run()
    at.text_input[0].set_value("bike lanes").run()
    assert not at.exception
    modes = [kwargs.get("mode") for _, kwargs in at.session_state["calls"]]
    assert "exact" in modes and "meaning" in modes
    assert not at.get("segmented_control")
    # The fake search returns the same rows for both; exact matches aren't repeated.
    assert any("25 matching decisions" in m.value for m in at.markdown)
    assert not any("Related by topic" in m.value for m in at.markdown)
    at.text_input[0].set_value("absent").run()
    assert any("No items match" in info.value for info in at.info)


def test_english_titles_match_every_word_typed():
    from unittest.mock import patch

    from mtl_council_agent.app.views import decisions

    rows = [{"id": 1, "title": "Accorder un contrat de déneigement"},
            {"id": 2, "title": "Accorder un contrat d'éclairage"}]
    english = {"Accorder un contrat de déneigement": "Grant a snow removal contract",
               "Accorder un contrat d'éclairage": "Grant a lighting contract"}
    with patch.object(decisions.translations, "english", side_effect=english.get):
        assert [r["id"] for r in decisions._english_matches("Snow removal", rows)] == [1]
        assert [r["id"] for r in decisions._english_matches("contract", rows)] == [1, 2]
        assert decisions._english_matches("snow lighting", rows) == []


def test_a_record_and_back_keeps_the_search():
    at = _run()
    at.text_input[0].set_value("contract").run()
    # Opening by URL, as the button does: after st.rerun AppTest keeps the aborted
    # run's text box, whose state is gone, and fails reading it on the next run.
    at.query_params["item"] = "1"
    at.run()
    assert not at.exception
    assert any("Detail 1" in m.value for m in at.markdown)
    at.button[0].click().run()
    assert not at.exception
    assert at.text_input[0].value == "contract"


def _render_chat_without_backend():
    from unittest.mock import patch

    import streamlit as st

    from mtl_council_agent.app.views import home

    with patch.object(home, "_chat", side_effect=lambda: st.write("Chat content")):
        home.render()


def test_ask_has_no_record_statistics_or_contested_vote_sidebar():
    at = AppTest.from_function(_render_chat_without_backend).run()
    assert not at.exception
    assert not at.metric
    text = " ".join(m.value for m in at.markdown)
    assert "The record" not in text
    assert "Contested votes" not in text
    assert "Chat content" in text
