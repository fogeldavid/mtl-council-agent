"""Three top-level destinations, with records grouped under their parent section."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from mtl_council_agent.app.navigation import PRIMARY, section_for

PRIMARY_LABELS = ["Ask the council", "District explorer", "Council updates"]


@pytest.mark.parametrize(("page", "section"), [
    ("ask", "ask"), ("districts", "districts"), ("councillors", "districts"),
    ("decisions", "council"), ("meetings", "council"),
    ("updates", "council"), ("search", "council"),
])
def test_detail_pages_belong_to_their_parent(page, section):
    assert section_for(page) == section
    assert PRIMARY == ("ask", "districts", "council")


def _render_navigation(page):
    import streamlit as st

    from mtl_council_agent.app import navigation
    from mtl_council_agent.app.common import PAGES

    for key in ("ask", "districts", "decisions", "meetings", "councillors", "about"):
        PAGES[key] = st.Page(lambda: None, title=key, url_path=key, default=key == "ask")
    st.navigation(list(PAGES.values()), position="hidden")
    navigation.render(page)


@pytest.mark.parametrize(("page", "secondary"), [
    ("ask", []),
    ("decisions", ["Decisions", "Meetings"]),
    ("meetings", ["Decisions", "Meetings"]),
    ("landing", []),
    ("about", []),
    ("councillors", ["Districts", "Councillors"]),
])
def test_three_primary_links_and_contextual_secondary_links(page, secondary):
    at = AppTest.from_function(_render_navigation, args=(page,)).run()
    assert not at.exception
    labels = [element.proto.label for element in at.get("page_link")]
    assert labels == [*PRIMARY_LABELS, *secondary]


def _entrypoint(monkeypatch):
    # Local development credentials must never make this offline test query a real database.
    monkeypatch.setattr("mtl_council_agent.app.common.database_configured", lambda: False)
    monkeypatch.setattr("mtl_council_agent.app.views.landing.database_configured", lambda: False)
    app = Path(__file__).parents[1] / "streamlit_app.py"
    return AppTest.from_file(str(app), default_timeout=30).run()


def test_the_landing_page_opens_first_with_four_front_page_sections(monkeypatch):
    at = _entrypoint(monkeypatch)
    assert not at.exception
    assert not at.sidebar.children
    labels = [element.proto.label for element in at.get("page_link")]
    assert labels == [
        "The Montréal Record.", "About", *PRIMARY_LABELS,
        "Find who represents you", "Search every decision",
        "Ask a question about a council vote", "Council meetings",
    ]
    text = " ".join(m.value for m in at.markdown)
    for label in ("Your district", "The record", "Ask", "Latest"):
        assert label in text


def _render_about():
    from mtl_council_agent.app.views import about

    about.render()


def test_the_landing_photo_is_bundled_and_credited_on_the_about_page():
    from mtl_council_agent.app.views import landing

    assert landing.PHOTO.stat().st_size < 400_000
    at = AppTest.from_function(_render_about).run()
    assert not at.exception
    credit = " ".join(m.value for m in at.markdown)
    assert "Concierge.2C" in credit and "CC BY-SA 3.0" in credit


def test_the_top_left_link_goes_home_with_a_home_icon(monkeypatch):
    at = _entrypoint(monkeypatch)
    link = at.get("page_link")[0].proto
    assert link.label == "The Montréal Record."
    assert link.icon == ":material/home:"


def test_each_landing_section_goes_to_its_page(monkeypatch):
    from mtl_council_agent.app.views import landing

    assert [section[1] for section in landing.SECTIONS] == [
        "districts", "decisions", "ask", "meetings",
    ]
    at = _entrypoint(monkeypatch)
    links = {element.proto.label: element.proto.page for element in at.get("page_link")}
    assert links["Find who represents you"] == links["District explorer"]
    assert links["Search every decision"] == links["Council updates"]
    assert links["Ask a question about a council vote"] == links["Ask the council"]
