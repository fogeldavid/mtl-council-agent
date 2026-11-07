"""Three public sections; detail URLs remain shareable inside their parent section."""

from __future__ import annotations

import streamlit as st

from mtl_council_agent.app.common import PAGES
from mtl_council_agent.app.i18n import t

PRIMARY = ("ask", "districts", "council")
CHILDREN = {
    "ask": (),
    "districts": ("districts", "councillors"),
    "council": ("decisions", "meetings"),
}
# The old newsfeed and search addresses now lead to Decisions.
MOVED = {"updates": "council", "search": "council"}


def section_for(page: str) -> str:
    if page in MOVED:
        return MOVED[page]
    return next((section for section, pages in CHILDREN.items() if page in pages), page)


def render(page: str) -> None:
    active = section_for(page)
    with st.container(key="primary-navigation"):
        columns = st.columns(len(PRIMARY))
        for column, section in zip(columns, PRIMARY, strict=True):
            suffix = "-active" if section == active else ""
            with column, st.container(key=f"nav-{section}{suffix}"):
                destination = "decisions" if section == "council" else section
                st.page_link(PAGES[destination], label=t("nav." + section))
    children = CHILDREN.get(active, ())
    if children:
        with st.container(key="section-navigation"):
            columns = st.columns(len(children))
            for column, child in zip(columns, children, strict=True):
                suffix = "-active" if child == page else ""
                with column, st.container(key=f"subnav-{child}{suffix}"):
                    label = {"districts": "nav.map"}.get(
                        child, "nav." + child,
                    )
                    st.page_link(PAGES[child], label=t(label))
