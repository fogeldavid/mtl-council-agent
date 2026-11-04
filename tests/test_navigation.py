"""Four top-level destinations, with records grouped under their parent section."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from mtl_council_agent.app.navigation import PRIMARY, section_for


@pytest.mark.parametrize(("page", "section"), [
    ("ask", "ask"), ("districts", "districts"), ("councillors", "districts"),
    ("updates", "updates"), ("meetings", "records"), ("search", "updates"),
    ("about", "records"),
])
def test_detail_pages_belong_to_their_parent(page, section):
    assert section_for(page) == section
    assert PRIMARY == ("ask", "districts", "updates", "records")


def _render_navigation(page):
    import streamlit as st

    from mtl_council_agent.app import navigation
    from mtl_council_agent.app.common import PAGES

    for key in ("ask", "districts", "updates", "meetings", "search", "councillors", "about"):
        PAGES[key] = st.Page(lambda: None, title=key, url_path=key, default=key == "updates")
    st.navigation(list(PAGES.values()), position="hidden")
    navigation.render(page)


@pytest.mark.parametrize(("page", "secondary"), [
    ("ask", []),
    ("updates", ["Search"]),
    ("search", ["Search"]),
    ("councillors", ["Map", "Councillors"]),
    ("meetings", ["Meetings", "About"]),
    ("about", ["Meetings", "About"]),
])
def test_only_four_primary_links_and_contextual_secondary_links(page, secondary):
    at = AppTest.from_function(_render_navigation, args=(page,)).run()
    assert not at.exception
    assert any(b.label == "Council updates" for b in at.button)
    labels = [element.proto.label for element in at.get("page_link")]
    assert labels == [
        "Ask the council", "District explorer", "Records & about", *secondary,
    ]


def test_real_entrypoint_renders_without_a_sidebar(monkeypatch):
    # Local development credentials must never make this offline test query a real database.
    monkeypatch.setattr("mtl_council_agent.app.common.database_configured", lambda: False)
    app = Path(__file__).parents[1] / "streamlit_app.py"
    at = AppTest.from_file(str(app), default_timeout=30).run()
    assert not at.exception
    assert not at.sidebar.children
    assert any(b.label == "Council updates" for b in at.button)
    labels = [element.proto.label for element in at.get("page_link")]
    assert labels == [
        "Ask the council", "District explorer", "Records & about", "Search",
        "Preview the district map",
    ]
