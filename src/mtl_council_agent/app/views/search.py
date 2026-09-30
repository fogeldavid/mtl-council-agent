"""Search: words or meaning, narrowed by filters, with a CSV download."""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from mtl_council_agent.app import queries
from mtl_council_agent.app.common import (
    PAGES,
    badge,
    display_number,
    fmt_date,
    html_text,
    masthead,
    outcome_label,
    run,
)
from mtl_council_agent.app.i18n import t

PAGE_SIZE = 25
CSV_LIMIT = 5000
# Ranking by meaning orders every item, so a total count means nothing; the
# closest few are what's useful.
MEANING_LIMIT = 50

# Off on hosts too small to load the embedding model; exact search still works.
MEANING_ENABLED = os.environ.get("SEMANTIC_SEARCH", "on").lower() != "off"


@st.cache_data(max_entries=256, show_spinner=False)
def _query_vector(text: str) -> str:
    from mtl_council_agent.ingestion.embed import embed_query

    return str(embed_query(text))


def _marked(snippet: str | None) -> str:
    """Escape record text, then turn the database's match markers into <mark>."""
    if not snippet:
        return ""
    return (
        html_text(" ".join(snippet.split()))
        .replace(queries.MARK_START, "<mark>")
        .replace(queries.MARK_END, "</mark>")
    )


def _filters() -> dict:
    meetings = run(queries.meetings)
    councillors = run(queries.councillors)
    departments = run(queries.departments)

    meeting = st.selectbox(
        t("filter.meeting"), [None] + meetings,
        format_func=lambda m: (
            t("filter.all_meetings") if m is None else fmt_date(m["meeting_date"])
        ),
    )
    outcomes = st.multiselect(
        t("filter.outcome"), queries.OUTCOMES, format_func=outcome_label,
    )
    section = st.selectbox(
        t("filter.section"), [None, "council", "agglomeration_orientation"],
        format_func=lambda s: t("filter.any") if s is None else t("section." + s),
    )
    person = st.selectbox(
        t("filter.councillor"), [None] + councillors,
        format_func=lambda c: t("filter.anyone") if c is None else c["name"],
    )
    department = st.selectbox(
        t("filter.department"), [None] + departments,
        format_func=lambda d: t("filter.any") if d is None else d,
    )
    return {
        "meeting_id": meeting["id"] if meeting else None,
        "outcomes": outcomes or None,
        "section": section,
        "official_id": person["id"] if person else None,
        "department": department,
    }


def _csv(rows: list[dict]) -> bytes:
    table = pd.DataFrame(
        {
            "date": [r["meeting_date"].isoformat() for r in rows],
            "item": [display_number(r["item_number"], r["section"]) for r in rows],
            "section": [r["section"] for r in rows],
            "title": [r["title"] for r in rows],
            "outcome": [r["vote_outcome"] for r in rows],
            "department": [r["department"] for r in rows],
            "resolution": [r["motion_number"] for r in rows],
            "dossier": [r["dossier_number"] for r in rows],
        }
    )
    return table.to_csv(index=False).encode("utf-8-sig")


def _result_card(row: dict) -> None:
    number = display_number(row["item_number"], row["section"])
    st.markdown(
        f'<div class="card">{badge(row["vote_outcome"], row["has_minutes"])}'
        f' <span class="meta">&nbsp;{fmt_date(row["meeting_date"])} · {number}</span>'
        f'<div class="title" style="margin:6px 0 4px">{html_text(row["title"][:260])}</div>'
        f'<div class="meta">{html_text(row["department"] or "")}</div>'
        f'<div style="font-size:14px;margin-top:6px">{_marked(row["snippet"])}</div></div>',
        unsafe_allow_html=True,
    )
    st.page_link(
        PAGES["meetings"], label=t("search.open", number=number), query_params={"item": row["id"]}
    )


def render() -> None:
    masthead()
    st.markdown(f"## {t('search.title')}")
    left, right = st.columns([1, 2.6], gap="large")

    with left:
        filters = _filters()

    with right:
        box, switch = st.columns([3, 1.3], vertical_alignment="bottom")
        text = box.text_input(
            t("search.box"), placeholder=t("search.placeholder"), label_visibility="collapsed"
        )
        modes = ["exact", "meaning"] if MEANING_ENABLED else ["exact"]
        mode = switch.segmented_control(
            t("search.box"), modes, default="exact", label_visibility="collapsed",
            format_func=lambda m: t("search." + m), key="search_mode",
        ) or "exact"
        st.caption(t("search.tip_" + mode))

        embedding = None
        if text and mode == "meaning":
            try:
                with st.spinner(t("search.loading_model")):
                    embedding = _query_vector(text)
            except Exception:  # model can't load on this host: fall back, say so
                st.warning(t("search.meaning_unavailable"))
                mode = "exact"

        key = (text, mode, tuple(sorted(str(v) for v in filters.items())))
        if st.session_state.get("search_key") != key:
            st.session_state.search_key = key
            st.session_state.search_shown = PAGE_SIZE
        shown = st.session_state.search_shown

        meaning = mode == "meaning" and embedding is not None
        cap = MEANING_LIMIT if meaning else CSV_LIMIT
        rows = run(
            queries.search, text, mode=mode, embedding=embedding,
            limit=min(shown + 1, cap), **filters,
        )
        everything = run(
            queries.search, text, mode=mode, embedding=embedding,
            limit=cap, snippets=False, **filters,
        )

        if not everything:
            st.info(t("search.none"))
            return

        capped = len(everything) >= cap
        head, download = st.columns([2, 1], vertical_alignment="center")
        head.markdown(
            f"**{t('search.results_capped' if capped else 'search.results', n=len(everything))}**"
        )
        download.download_button(
            t("search.csv"), _csv(everything), file_name="council-record-search.csv",
            mime="text/csv",
        )
        for row in rows[:shown]:
            _result_card(row)
        if len(rows) > shown and shown < cap:
            if st.button(t("search.more")):
                st.session_state.search_shown = shown + PAGE_SIZE
                st.rerun()
