"""Each page renders against the seeded database without an exception.

Streamlit's test runner can only switch between file-based pages, and the
app's pages are functions behind st.navigation, so each view is rendered
directly with the query parameters that select it.
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import ButtonGroup


def _indices(self):
    # Streamlit's test runner iterates a single-select segmented control's
    # value ("EN") character by character and fails on the next widget
    # interaction. The app is unaffected; this reads a lone string as one value.
    values = [self.value] if isinstance(self.value, str) else (self.value or [])
    return [self.options.index(self.format_func(v)) for v in values]


ButtonGroup.indices = property(_indices)


def _render(view: str, params: dict[str, str]) -> None:
    import streamlit as st

    from mtl_council_agent.app.common import PAGES
    from mtl_council_agent.app.views import (
        about,
        councillors,
        decisions,
        districts,
        home,
        meetings,
    )

    views = {
        "home": home, "decisions": decisions, "meetings": meetings,
        "councillors": councillors, "about": about, "districts": districts,
    }
    PAGES.update(
        decisions=st.Page(decisions.render, title="Decisions", url_path="decisions"),
        ask=st.Page(home.render, title="Ask", url_path="ask", default=True),
        meetings=st.Page(meetings.render, title="Meetings", url_path="meetings"),
        councillors=st.Page(councillors.render, title="Councillors", url_path="councillors"),
        about=st.Page(about.render, title="About", url_path="about"),
    )
    for key, value in params.items():
        st.query_params[key] = value
    views[view].render()


def _run(view: str, params: dict | None = None) -> AppTest:
    return AppTest.from_function(_render, args=(view, params or {}), default_timeout=60).run()


@pytest.fixture(autouse=True)
def _web_database(db_url, monkeypatch):
    monkeypatch.setenv("WEB_DATABASE_URL", db_url)
    # Searching by meaning would load the embedding model; these tests cover exact words.
    monkeypatch.setattr("mtl_council_agent.app.views.decisions.MEANING_ENABLED", False)


@pytest.mark.parametrize(
    ("view", "params"),
    [
        ("home", {}),
        ("decisions", {}),
        ("decisions", {"item": "10"}),
        ("districts", {}),
        ("meetings", {}),
        ("meetings", {"meeting": "1"}),
        ("meetings", {"meeting": "2"}),
        ("meetings", {"item": "10"}),
        ("meetings", {"item": "11"}),
        ("meetings", {"item": "13"}),
        ("meetings", {"item": "20"}),
        ("councillors", {}),
        ("councillors", {"id": "3"}),
        ("councillors", {"id": "5"}),
        ("about", {}),
    ],
)
def test_view_renders_without_error(view, params):
    at = _run(view, params)
    assert not at.exception, at.exception[0].value


def test_home_only_shows_chat_without_record_statistics():
    at = _run("home")
    assert not at.metric
    assert "The record" not in " ".join(m.value for m in at.markdown)


def test_item_page_labels_inferred_votes():
    at = _run("meetings", {"item": "10"})
    text = " ".join(m.value for m in at.markdown)
    assert "inferred from attendance" in text
    assert "Marie Plourde" in text


def test_orientation_item_says_the_final_decision_is_elsewhere():
    at = _run("meetings", {"item": "13"})
    text = " ".join(m.value for m in at.markdown)
    assert "agglomeration council, which makes the final decision" in text


def test_missing_item_shows_a_warning_not_a_crash():
    at = _run("meetings", {"item": "999"})
    assert not at.exception
    assert at.warning


def test_decisions_by_words_shows_results_and_csv():
    at = _run("decisions")
    at.text_input[0].input("Veille").run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "1 results" in text
    assert "<mark>Veille</mark>" in text
    assert at.get("download_button")


def test_decisions_open_on_decided_items_newest_first():
    at = _run("decisions")
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "4 decisions" in text
    at.checkbox[0].uncheck().run()
    assert "5 decisions" in " ".join(m.value for m in at.markdown)


def test_decisions_filter_without_words():
    at = _run("decisions")
    at.multiselect[0].select("rejected").run()
    assert not at.exception
    assert "1 decision" in " ".join(m.value for m in at.markdown)


def test_decisions_with_no_match_says_so():
    at = _run("decisions")
    at.text_input[0].input("zzzqqq").run()
    assert "No items match" in " ".join(i.value for i in at.info)


@pytest.fixture
def stub_agent(monkeypatch):
    """The chat answers without calling Anthropic, and records the questions."""
    from mtl_council_agent.agent.loop import AgentAnswer
    from mtl_council_agent.app import chat

    asked = []

    def fake_ask(conn, question, client, history=None, tools=None):
        asked.append((question, history))
        return AgentAnswer(text="Council adopted it by majority (2026-03-23 item 20.06).")

    monkeypatch.setattr(chat, "ask", fake_ask)
    monkeypatch.setenv("WEB_ANTHROPIC_API_KEY", "pool-key")
    chat.ledger.clear()
    return asked


def test_ask_without_team_key_never_requests_a_visitor_key(monkeypatch):
    monkeypatch.delenv("WEB_ANTHROPIC_API_KEY", raising=False)
    at = _run("home")
    assert not at.exception
    assert at.chat_input[0].disabled
    assert not at.text_input
    assert any("temporarily unavailable" in info.value for info in at.info)


def test_ask_answers_and_keeps_follow_up_context(stub_agent):
    at = _run("home")
    assert not at.chat_input[0].disabled
    at.chat_input[0].set_value("Who voted against 20.06?").run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "adopted it by majority" in text
    assert "4 of 5 free questions left today." in " ".join(c.value for c in at.caption)

    at.chat_input[0].set_value("And who moved it?").run()
    assert stub_agent[1] == (
        "And who moved it?",
        [("Who voted against 20.06?", "Council adopted it by majority (2026-03-23 item 20.06).")],
    )


def test_ask_closes_after_allowance_without_requesting_visitor_keys(stub_agent):
    at = _run("home")
    for n in range(5):
        at.chat_input[0].set_value(f"q{n}").run()
    assert at.chat_input[0].disabled
    assert not at.text_input
    assert any("used up" in info.value for info in at.info)


def _render_vote_panel(outcome, inferred):
    from unittest.mock import patch

    import streamlit as st

    from mtl_council_agent.agent.tools import VoteDetail
    from mtl_council_agent.app.common import PAGES
    from mtl_council_agent.app.views import meetings

    PAGES["councillors"] = st.Page(lambda: None, title="c", url_path="councillors", default=True)
    item = {
        "id": 1, "vote_outcome": outcome, "section": "council",
        "mover": "Soraya Martinez Ferrada", "mover_id": 57,
        "seconder": "Josué Corvil", "seconder_id": 63,
    }
    detail = VoteDetail(outcome=outcome, inferred_for=inferred)
    with patch.object(meetings, "run", return_value=detail):
        meetings._votes(item)


def test_a_unanimous_item_without_attendance_says_so_and_labels_the_mover():
    at = AppTest.from_function(_render_vote_panel, args=("adopted_unanimous", None)).run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "Adopted unanimously. The minutes don" in text
    assert "No individual votes" not in text
    assert [link.proto.label for link in at.get("page_link")] == [
        "Moved by Soraya Martinez Ferrada →", "Seconded by Josué Corvil →",
    ]


def test_only_unanimous_items_are_described_as_unanimous():
    at = AppTest.from_function(_render_vote_panel, args=("rejected", None)).run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "No individual votes" in text and "unanimously" not in text


def test_the_app_connection_can_send_search_vectors():
    # The agent's semantic_search sends one of these; the eval connects another
    # way, so it can't catch this failing on the app's connection.
    from pgvector import HalfVector

    from mtl_council_agent.app import common

    common._connection.clear()
    try:
        row = common._connection().execute(
            "select %s::halfvec::text", (HalfVector([1.0, 2.0]),)
        ).fetchone()
    finally:
        common._connection.clear()
    assert row[0] == "[1,2]"


def test_explain_without_questions_left_never_asks_for_a_key(monkeypatch):
    from mtl_council_agent.app import chat

    monkeypatch.setenv("WEB_ANTHROPIC_API_KEY", "pool-key")
    monkeypatch.setattr(chat, "FREE_PER_DAY", 0)
    at = _run("meetings", {"item": "10"})
    assert not at.exception
    captions = " ".join(c.value for c in at.caption)
    assert "used up" in captions
    assert "key" not in captions.lower()


def test_explain_button_on_an_item(stub_agent):
    at = _run("meetings", {"item": "10"})
    button = next(b for b in at.button if b.label == "Explain this item in English")
    button.click().run()
    assert not at.exception
    assert "adopted it by majority" in " ".join(m.value for m in at.markdown)
    question = stub_agent[0][0]
    assert "item_id 10" in question and "20.06" in question


def test_district_selector_shows_the_imported_representative():
    at = _run("districts")
    at.selectbox[0].select("111").run()
    assert not at.exception
    links = [element.proto.label for element in at.get("page_link")]
    assert "Marie Plourde: see votes →" in links
    assert not any("Soraya Martinez Ferrada" in link for link in links)
    # Meetings and votes live on the councillor's own page now.
    assert "Original minutes" not in " ".join(b.proto.label for b in at.get("link_button"))
