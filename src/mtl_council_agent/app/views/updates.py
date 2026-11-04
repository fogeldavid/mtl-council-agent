"""One searchable feed of decisions backed by published minutes."""

from __future__ import annotations

import streamlit as st

from mtl_council_agent.app import queries, translations
from mtl_council_agent.app.common import (
    badge,
    display_number,
    fmt_date,
    go,
    html_text,
    masthead,
    record_title,
    run,
)
from mtl_council_agent.app.i18n import lang, t
from mtl_council_agent.app.views import meetings

PAGE_SIZE = 20


def _reset_page() -> None:
    st.session_state["feed_page"] = 0


def render() -> None:
    masthead()
    if "item" in st.query_params:
        meetings._item_view(int(st.query_params["item"]), from_feed=True)
        return
    st.title(t("updates.title"))
    st.caption(t("feed.minutes_only"))
    if lang() == "en":
        st.caption(t("translation.label"))
    saved = st.session_state.get("feed_filters", {})
    text = st.text_input(
        t("nav.search"), value=saved.get("text", ""), placeholder=t("feed.search_hint"),
        key="_feed_text", on_change=_reset_page,
    )
    if lang() == "en":
        st.caption(t("feed.search_french"))
    filters, feed = st.columns([1, 3], gap="large")
    with filters:
        st.markdown(f"#### {t('feed.filters')}")
        sessions = [m for m in run(queries.meetings) if m["has_minutes"]]
        dates = {m["id"]: m["meeting_date"] for m in sessions}
        choices = [None, *dates]
        selected_meeting = saved.get("meeting_id")
        meeting_id = st.selectbox(
            t("filter.meeting"), choices,
            index=choices.index(selected_meeting) if selected_meeting in choices else 0,
            format_func=lambda value: t("filter.all_meetings") if value is None
            else fmt_date(dates[value]), key="_feed_meeting", on_change=_reset_page,
        )
        outcomes = [None, *queries.VOTED_OUTCOMES]
        selected_outcome = saved.get("outcome")
        outcome = st.selectbox(
            t("filter.outcome"), outcomes,
            index=outcomes.index(selected_outcome) if selected_outcome in outcomes else 0,
            format_func=lambda value: t("filter.any") if value is None
            else t("outcome." + value), key="_feed_outcome", on_change=_reset_page,
        )
        departments = [None, *run(queries.departments)]
        selected_department = saved.get("department")
        department = st.selectbox(
            t("filter.department"), departments,
            index=(departments.index(selected_department)
                   if selected_department in departments else 0),
            format_func=lambda value: value or t("filter.any"),
            key="_feed_department", on_change=_reset_page,
        )
    selected_filters = {
        "text": text, "meeting_id": meeting_id, "outcome": outcome, "department": department,
    }
    # Plain session state survives opening a detail page, unlike widget-only values.
    st.session_state["feed_filters"] = selected_filters
    page = st.session_state.setdefault("feed_page", 0)
    rows = run(queries.newsfeed, **selected_filters, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    with feed:
        if not rows:
            st.info(t("updates.empty"))
            if page and st.button(t("feed.previous")):
                st.session_state["feed_page"] = page - 1
                st.rerun()
            return
        total = rows[0]["total_count"]
        st.caption(t("feed.count", start=page * PAGE_SIZE + 1,
                     end=page * PAGE_SIZE + len(rows), total=total))
        for row in rows:
            number = display_number(row["item_number"], row["section"])
            st.markdown(
                '<article class="record-story">'
                f'<div class="meta">{fmt_date(row["meeting_date"])} · {html_text(number)}</div>'
                f'{badge(row["vote_outcome"], True)}'
                f'<h3>{html_text(record_title(row["title"]))}</h3>'
                '</article>', unsafe_allow_html=True,
            )
            if lang() == "en" and not translations.english(row["title"]):
                st.caption(t("translation.pending"))
            if row["section"] == "agglomeration_orientation":
                st.caption(t("orientation"))
            if st.button(t("updates.read"), key=f"feed_open_{row['id']}", type="tertiary"):
                go(item=row["id"])
        previous, next_page = st.columns(2)
        if previous.button(t("feed.previous"), disabled=page == 0):
            st.session_state["feed_page"] = page - 1
            st.rerun()
        if next_page.button(t("feed.next"), disabled=(page + 1) * PAGE_SIZE >= total):
            st.session_state["feed_page"] = page + 1
            st.rerun()
