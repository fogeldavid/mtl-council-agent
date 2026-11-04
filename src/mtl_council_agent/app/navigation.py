"""Four public sections; detail URLs remain shareable inside their parent section."""

from __future__ import annotations

import streamlit as st

from mtl_council_agent.app.common import PAGES
from mtl_council_agent.app.i18n import t

PRIMARY = ("ask", "districts", "updates", "records")
CHILDREN = {
    "ask": (),
    "districts": ("districts", "councillors"),
    "updates": ("updates", "search"),
    "records": ("meetings", "about"),
}


def section_for(page: str) -> str:
    if page == "search":
        return "updates"
    return next((section for section, pages in CHILDREN.items() if page in pages), page)


def _link(page: str, label: str, button_key: str) -> None:
    if page == "updates":
        # Streamlit emits an empty href for the default page; browsers
        # resolve that to the current subpage. Switch pages explicitly.
        if st.button(label, key=button_key, type="tertiary"):
            st.switch_page(PAGES["updates"])
    else:
        st.page_link(PAGES[page], label=label)


def render(page: str) -> None:
    active = section_for(page)
    with st.container(key="primary-navigation"):
        columns = st.columns(len(PRIMARY))
        for column, section in zip(columns, PRIMARY, strict=True):
            suffix = "-active" if section == active else ""
            with column, st.container(key=f"nav-{section}{suffix}"):
                destination = "meetings" if section == "records" else section
                _link(destination, t("nav." + section), "nav_updates")
    children = CHILDREN[active]
    if children:
        with st.container(key="section-navigation"):
            columns = st.columns(len(children))
            for column, child in zip(columns, children, strict=True):
                with column:
                    label = {"updates": "nav.feed", "districts": "nav.map"}.get(
                        child, "nav." + child,
                    )
                    _link(child, t(label), "nav_feed")
