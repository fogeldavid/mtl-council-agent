"""The front door: what this site is, and four ways in, laid out like a front page."""

from __future__ import annotations

from pathlib import Path

import psycopg
import streamlit as st

from mtl_council_agent.app import queries
from mtl_council_agent.app.common import (
    PAGES,
    database_configured,
    fmt_date,
    open_page,
    run,
)
from mtl_council_agent.app.i18n import t

PHOTO = Path(__file__).parents[1] / "data" / "city-hall.jpg"

# In reading order: section key, page, label, title, description.
SECTIONS = (
    ("districts", "districts", "landing.districts_label", "landing.districts",
     "landing.districts_help"),
    ("decisions", "decisions", "landing.search_label", "landing.search", "landing.search_help"),
    ("ask", "ask", "landing.ask_label", "landing.ask", "landing.ask_help"),
    ("latest", "meetings", "landing.latest_label", "landing.latest", "landing.latest_help"),
)
ACTIONS = {
    "districts": "landing.districts_action", "decisions": "landing.search_action",
    "ask": "landing.ask_action", "latest": "landing.latest_action",
}


def _latest() -> dict | None:
    """The newest meeting with published minutes, or None without the database."""
    if not database_configured():
        return None
    try:
        rows = run(queries.meetings)
    except psycopg.Error:
        return None
    return next((m for m in rows if m["has_minutes"]), None)


def _section(key: str, page: str, label: str, title: str, help_text: str, latest) -> None:
    params = {}
    if key == "latest" and latest:
        title_text = fmt_date(latest["meeting_date"])
        help_line = t("landing.latest_items", n=latest["items"])
        params = {"meeting": latest["id"]}
    else:
        title_text, help_line = t(title), t(help_text)
    with st.container(key=f"landing-section-{key}"):
        st.markdown(f'<div class="landing-label">{t(label)}</div>', unsafe_allow_html=True)
        if params:
            open_page(title_text, page, f"landing_open_{key}", **params)
        else:
            st.page_link(PAGES[page], label=title_text)
        st.caption(help_line)
        st.markdown(f'<div class="landing-action">{t(ACTIONS[key])}</div>', unsafe_allow_html=True)


def render() -> None:
    words, picture = st.columns([1, 1], gap="large", vertical_alignment="center")
    with words, st.container(key="landing-words"):
        st.title(t("landing.title"))
        st.write(t("landing.intro"))
    with picture, st.container(key="landing-photo"):
        st.image(PHOTO, width="stretch")
    latest = _latest()
    for row in (SECTIONS[:2], SECTIONS[2:]):
        with st.container(key=f"landing-row-{row[0][0]}"):
            for column, section in zip(st.columns(2, gap=None), row, strict=True):
                with column:
                    _section(*section, latest)
