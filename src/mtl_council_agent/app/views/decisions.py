"""Council decisions: the latest first, or searched by meaning or exact words."""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from mtl_council_agent.app import queries, translations
from mtl_council_agent.app.common import (
    badge,
    display_number,
    fmt_date,
    go,
    html_text,
    record_title,
    run,
)
from mtl_council_agent.app.i18n import lang, t
from mtl_council_agent.app.views import meetings

PAGE_SIZE = 20
CSV_LIMIT = 5000
# Ranking by meaning orders every item, so a total count means nothing; the
# closest few are what's useful.
MEANING_LIMIT = 50

# Off on hosts too small to load the embedding model; exact search still works.
MEANING_ENABLED = os.environ.get("SEMANTIC_SEARCH", "on").lower() != "off"

# Streamlit drops a widget's value on leaving the page, so each one is copied
# here and restored when the page comes back.
SAVED = "decisions_saved"


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


def _restore(options: dict[str, list]) -> None:
    """Bring back each widget's value, if it is still one of its options."""
    saved = st.session_state.get(SAVED, {})
    defaults = {
        "dec_text": "", "dec_mode": options["dec_mode"][0], "dec_decided": True,
        "dec_meeting": None, "dec_outcomes": [], "dec_section": None,
        "dec_person": None, "dec_department": None,
    }
    for key, default in defaults.items():
        if key in st.session_state:
            continue
        value = saved.get(key, default)
        if key in options and key != "dec_outcomes" and value not in options[key]:
            value = default
        if key == "dec_outcomes":
            value = [v for v in value if v in options[key]]
        st.session_state[key] = value


def _mode(options: dict[str, list]) -> str:
    # Clicking the selected mode again clears it; fall back to the first one.
    return st.session_state["dec_mode"] or options["dec_mode"][0]


def _filters(options: dict[str, list], labels: dict) -> None:
    box, switch = st.columns([3, 1.3], vertical_alignment="bottom")
    box.text_input(
        t("decisions.search"), key="dec_text", placeholder=t("feed.search_hint"),
        label_visibility="collapsed",
    )
    switch.segmented_control(
        t("decisions.search"), options["dec_mode"], key="dec_mode",
        format_func=lambda m: t("search." + m), label_visibility="collapsed",
    )
    st.caption(t("search.tip_" + _mode(options)))
    st.checkbox(t("decisions.decided"), key="dec_decided", help=t("decisions.decided_help"))
    active = any(
        st.session_state[k] for k in ("dec_meeting", "dec_outcomes", "dec_section",
                                      "dec_person", "dec_department")
    )
    with st.expander(t("decisions.more_filters"), expanded=active):
        first, second, third = st.columns(3)
        first.selectbox(
            t("filter.meeting"), options["dec_meeting"], key="dec_meeting",
            format_func=lambda m: t("filter.all_meetings") if m is None else labels["meeting"][m],
        )
        second.multiselect(
            t("filter.outcome"), options["dec_outcomes"], key="dec_outcomes",
            format_func=lambda o: t("outcome." + o),
        )
        third.selectbox(
            t("filter.section"), options["dec_section"], key="dec_section",
            format_func=lambda s: t("filter.any") if s is None else t("section." + s),
        )
        fourth, fifth = st.columns(2)
        fourth.selectbox(
            t("filter.councillor"), options["dec_person"], key="dec_person",
            format_func=lambda p: t("filter.anyone") if p is None else labels["person"][p],
        )
        fifth.selectbox(
            t("filter.department"), options["dec_department"], key="dec_department",
            format_func=lambda d: t("filter.any") if d is None else d,
        )
    st.session_state[SAVED] = {
        key: st.session_state[key] for key in (
            "dec_text", "dec_mode", "dec_decided", "dec_meeting", "dec_outcomes",
            "dec_section", "dec_person", "dec_department",
        )
    }


def _card(row: dict) -> None:
    number = display_number(row["item_number"], row["section"])
    snippet = _marked(row.get("snippet"))
    st.markdown(
        '<article class="record-story">'
        f'<div class="meta">{fmt_date(row["meeting_date"])} · {html_text(number)}</div>'
        f'{badge(row["vote_outcome"], row["has_minutes"])}'
        f'<h3>{html_text(record_title(row["title"]))}</h3>'
        + (f'<div class="record-snippet" lang="fr">{snippet}</div>' if snippet else "")
        + "</article>",
        unsafe_allow_html=True,
    )
    if lang() == "en" and not translations.english(row["title"]):
        st.caption(t("translation.pending"))
    if row["section"] == "agglomeration_orientation":
        st.caption(t("orientation"))
    if st.button(t("updates.read"), key=f"feed_open_{row['id']}", type="tertiary"):
        go(item=row["id"])


def render() -> None:
    if "item" in st.query_params:
        meetings._item_view(int(st.query_params["item"]), from_feed=True)
        return
    st.title(t("decisions.title"))
    st.caption(
        f"{t('decisions.subtitle')} {t('translation.label')}." if lang() == "en"
        else t("decisions.subtitle")
    )

    meeting_rows = run(queries.meetings)
    people = run(queries.councillors)
    options = {
        "dec_mode": ["meaning", "exact"] if MEANING_ENABLED else ["exact"],
        "dec_meeting": [None, *(m["id"] for m in meeting_rows)],
        "dec_outcomes": list(queries.OUTCOMES),
        "dec_section": [None, "council", "agglomeration_orientation"],
        "dec_person": [None, *(p["id"] for p in people)],
        "dec_department": [None, *run(queries.departments)],
    }
    labels = {
        "meeting": {m["id"]: fmt_date(m["meeting_date"]) for m in meeting_rows},
        "person": {p["id"]: p["name"] for p in people},
    }
    _restore(options)
    _filters(options, labels)

    state = st.session_state
    text = state["dec_text"].strip()
    mode = _mode(options)
    filters = {
        "meeting_id": state["dec_meeting"], "outcomes": state["dec_outcomes"] or None,
        "section": state["dec_section"], "official_id": state["dec_person"],
        "department": state["dec_department"], "decided": state["dec_decided"],
    }

    embedding = None
    if text and mode == "meaning":
        try:
            with st.spinner(t("search.loading_model")):
                embedding = _query_vector(text)
        except Exception:  # the model can't load on this host: fall back, say so
            st.warning(t("search.meaning_unavailable"))
            mode = "exact"
    meaning = bool(text) and mode == "meaning" and embedding is not None
    cap = MEANING_LIMIT if meaning else CSV_LIMIT

    key = (text, mode, tuple(sorted(str(v) for v in filters.items())))
    if state.get("dec_key") != key:
        state["dec_key"] = key
        state["dec_shown"] = PAGE_SIZE
    shown = state["dec_shown"]

    everything = run(
        queries.search, text, mode=mode, embedding=embedding, limit=cap, snippets=False,
        **filters,
    )
    if not everything:
        st.info(t("decisions.none"))
        return
    rows = (
        run(queries.search, text, mode=mode, embedding=embedding, limit=shown, **filters)
        if text else everything[:shown]
    )

    head, download = st.columns([2, 1], vertical_alignment="center")
    if text:
        count = t("search.results_capped" if len(everything) >= cap else "search.results",
                  n=len(everything))
    else:
        count = t("decisions.count_one" if len(everything) == 1 else "decisions.count",
                  n=f"{len(everything):,}")
    head.markdown(f"**{count}**")
    download.download_button(
        t("search.csv"), _csv(everything), file_name="council-decisions.csv", mime="text/csv",
    )
    for row in rows[:shown]:
        _card(row)
    if len(everything) > shown:
        if st.button(t("search.more"), key="dec_more"):
            state["dec_shown"] = shown + PAGE_SIZE
            st.rerun()
