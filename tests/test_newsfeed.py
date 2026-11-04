"""Offline coverage of feed controls, detail navigation and the reduced chat page."""

from streamlit.testing.v1 import AppTest


def _render_feed():
    from datetime import date
    from unittest.mock import patch

    rows = [{
        "id": i, "meeting_date": date(2026, 3, 23), "item_number": f"20.{i:02}",
        "section": "council", "title": f"Decision {i}", "department": "Water",
        "vote_outcome": "adopted_majority", "has_minutes": True, "total_count": 25,
    } for i in range(1, 26)]
    from mtl_council_agent.app import queries
    from mtl_council_agent.app.views import updates

    def fake_run(query, *args, **kwargs):
        if query is queries.meetings:
            return [{"id": 1, "meeting_date": date(2026, 3, 23), "has_minutes": True},
                    {"id": 2, "meeting_date": date(2026, 9, 21), "has_minutes": False}]
        if query is queries.departments:
            return ["Water"]
        assert query is queries.newsfeed
        if kwargs.get("text") == "absent":
            return []
        return rows[kwargs["offset"]:kwargs["offset"] + kwargs["limit"]]

    def detail(item_id, from_feed=False):
        import streamlit as st

        from mtl_council_agent.app.common import go

        assert from_feed
        st.write(f"Detail {item_id}")
        if st.button("← Back to the newsfeed"):
            go()

    with patch.object(updates, "run", side_effect=fake_run), \
         patch.object(updates.meetings, "_item_view", side_effect=detail):
        updates.render()


def test_feed_has_one_search_three_filters_and_only_minutes_meetings():
    at = AppTest.from_function(_render_feed, default_timeout=30).run()
    assert not at.exception
    assert len(at.text_input) == 1
    assert len(at.selectbox) == 3
    assert at.selectbox[0].options == ["All meetings", "March 23, 2026"]
    assert any("1–20 of 25" in c.value for c in at.caption)
    assert len([b for b in at.button if b.label == "Read the record"]) == 20


def test_feed_pagination_and_filter_reset():
    at = AppTest.from_function(_render_feed, default_timeout=30).run()
    next(b for b in at.button if b.label == "Next →").click().run()
    assert not at.exception
    assert any("21–25 of 25" in c.value for c in at.caption)
    at.text_input[0].set_value("absent").run()
    assert not at.exception
    assert at.session_state["feed_page"] == 0
    assert any("No records match" in info.value for info in at.info)


def test_open_detail_and_return_preserves_search():
    at = AppTest.from_function(_render_feed, default_timeout=30).run()
    at.text_input[0].set_value("contract").run()
    next(b for b in at.button if b.label == "Read the record").click().run()
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
