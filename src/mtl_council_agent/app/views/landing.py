"""The front door: what this site is, and the four things to do on it."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from mtl_council_agent.app.common import PAGES
from mtl_council_agent.app.i18n import t

PHOTO = Path(__file__).parents[1] / "data" / "city-hall.jpg"

# In reading order: page, text key for the box, icon.
BOXES = (
    ("districts", "landing.districts", ":material/location_on:"),
    ("search", "landing.search", ":material/search:"),
    ("ask", "landing.ask", ":material/forum:"),
    ("updates", "landing.recent", ":material/event_note:"),
)


def render() -> None:
    words, picture = st.columns([1, 1], gap="large", vertical_alignment="center")
    with words, st.container(key="landing-words"):
        st.title(t("landing.title"))
        st.write(t("landing.intro"))
    with picture, st.container(key="landing-photo"):
        st.image(PHOTO, width="stretch")
    for row in (BOXES[:2], BOXES[2:]):
        for column, (page, text, icon) in zip(st.columns(2), row, strict=True):
            with column, st.container(key=f"landing-box-{page}"):
                st.page_link(PAGES[page], label=t(text), icon=icon)
                st.caption(t(text + "_help"))
