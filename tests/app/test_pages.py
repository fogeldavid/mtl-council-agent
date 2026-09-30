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
    from mtl_council_agent.app.views import about, councillors, home, meetings, search

    views = {
        "home": home, "search": search, "meetings": meetings,
        "councillors": councillors, "about": about,
    }
    PAGES.update(
        ask=st.Page(home.render, title="Ask", url_path="ask", default=True),
        search=st.Page(search.render, title="Search", url_path="search"),
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


@pytest.mark.parametrize(
    ("view", "params"),
    [
        ("home", {}),
        ("search", {}),
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


def test_home_shows_the_record_numbers():
    at = _run("home")
    shown = {m.label: m.value for m in at.metric}
    assert shown == {
        "Meetings": "2", "Agenda items": "5", "Recorded votes": "7", "Council members": "5",
    }


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


def test_search_by_words_shows_results_and_csv():
    at = _run("search")
    at.text_input[0].input("Veille").run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "1 results" in text
    assert "<mark>Veille</mark>" in text


def test_search_filter_without_words():
    at = _run("search")
    at.multiselect[0].select("rejected").run()
    assert not at.exception
    assert "1 results" in " ".join(m.value for m in at.markdown)


def test_search_with_no_match_says_so():
    at = _run("search")
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


def test_ask_without_any_key_offers_the_own_key_box(monkeypatch):
    monkeypatch.delenv("WEB_ANTHROPIC_API_KEY", raising=False)
    at = _run("home")
    assert not at.exception
    assert at.chat_input[0].disabled
    assert [ti.label for ti in at.text_input] == ["Your Anthropic API key"]


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


def test_ask_switches_to_own_key_after_the_free_questions(stub_agent):
    at = _run("home")
    for n in range(5):
        at.chat_input[0].set_value(f"q{n}").run()
    assert at.chat_input[0].disabled
    at.text_input[0].input("visitor-key").run()
    assert not at.chat_input[0].disabled
    assert "Using your own Anthropic key." in " ".join(c.value for c in at.caption)


def test_explain_button_on_an_item(stub_agent):
    at = _run("meetings", {"item": "10"})
    button = next(b for b in at.button if b.label == "Explain this item in English")
    button.click().run()
    assert not at.exception
    assert "adopted it by majority" in " ".join(m.value for m in at.markdown)
    question = stub_agent[0][0]
    assert "item_id 10" in question and "20.06" in question
