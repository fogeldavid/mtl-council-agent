"""Council decisions: the latest first, or searched.

One search box. Matches come first: the French text by Postgres full-text
search (which also catches resolution and dossier numbers and company
names), then English titles from the saved translations, since the records
are French. Items related by meaning follow under their own heading.
"""

from __future__ import annotations

import os
import re
import unicodedata

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


def _fold(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c)
    )


def _english_matches(text: str, rows: list[dict]) -> list[dict]:
    """Rows whose saved English title contains every word typed, so "snow
    removal" finds "Grant a contract ... for snow removal services"."""
    words = [w for w in re.findall(r"\w+", _fold(text)) if len(w) > 1]
    if not words:
        return []
    matched = []
    for row in rows:
        english = translations.english(row["title"])
        if english and all(re.search(rf"\b{re.escape(w)}", _fold(english)) for w in words):
            matched.append(row)
    return matched


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
        "dec_text": "", "dec_decided": True,
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


def _filters(options: dict[str, list], labels: dict) -> None:
    st.text_input(
        t("decisions.search"), key="dec_text", placeholder=t("feed.search_hint"),
        label_visibility="collapsed",
    )
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
            "dec_text", "dec_decided", "dec_meeting", "dec_outcomes",
            "dec_section", "dec_person", "dec_department",
        )
    }


def _card(row: dict) -> None:
    """One decision as a row whose whole area opens it, like the meetings and
    councillors lists. The title is the link."""
    number = display_number(row["item_number"], row["section"])
    snippet = _marked(row.get("snippet"))
    with st.container(key=f"list-row-decision-{row['id']}"):
        st.markdown(
            f'<div class="row-meta">{fmt_date(row["meeting_date"])} · {html_text(number)}'
            f' {badge(row["vote_outcome"], row["has_minutes"])}</div>',
            unsafe_allow_html=True,
        )
        if st.button(record_title(row["title"]), key=f"open_decision_{row['id']}",
                     type="tertiary"):
            go(item=row["id"])
        if snippet:
            st.markdown(f'<div class="record-snippet" lang="fr">{snippet}</div>',
                        unsafe_allow_html=True)
        if lang() == "en" and not translations.english(row["title"]):
            st.caption(t("translation.pending"))
        if row["section"] == "agglomeration_orientation":
            st.caption(t("orientation"))


def render() -> None:
    if "item" in st.query_params:
        meetings._item_view(int(st.query_params["item"]), from_feed=True)
        return
    st.title(t("decisions.title"))
    st.caption(
        t("decisions.subtitle") + (f" {t('translation.note')}" if lang() == "en" else "")
    )

    meeting_rows = run(queries.meetings)
    people = run(queries.councillors, True)
    options = {
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
    filters = {
        "meeting_id": state["dec_meeting"], "outcomes": state["dec_outcomes"] or None,
        "section": state["dec_section"], "official_id": state["dec_person"],
        "department": state["dec_department"], "decided": state["dec_decided"],
    }
    key = (text, tuple(sorted(str(v) for v in filters.items())))
    if state.get("dec_key") != key:
        state["dec_key"] = key
        state["dec_shown"] = PAGE_SIZE
    shown = state["dec_shown"]

    if not text:
        everything = run(queries.search, "", limit=CSV_LIMIT, snippets=False, **filters)
        if not everything:
            st.info(t("decisions.none"))
            return
        n = len(everything)
        count = t("decisions.count_one" if n == 1 else "decisions.count", n=f"{n:,}")
        _results(count, everything, everything[:shown], related_from=None, shown=shown)
        return

    # Exact matches with their highlighted snippets, then English title
    # matches, then related items by meaning, each without repeats.
    exact = run(queries.search, text, mode="exact", limit=CSV_LIMIT, **filters)
    seen = {r["id"] for r in exact}
    english = [
        r for r in _english_matches(
            text, run(queries.search, "", limit=CSV_LIMIT, snippets=False, **filters)
        )
        if r["id"] not in seen
    ]
    seen |= {r["id"] for r in english}
    related: list[dict] = []
    if MEANING_ENABLED:
        try:
            with st.spinner(t("search.loading_model")):
                embedding = _query_vector(text)
        except Exception:  # the model can't load on this host; matches still work
            embedding = None
        if embedding is not None:
            related = [
                r for r in run(
                    queries.search, text, mode="meaning", embedding=embedding,
                    limit=MEANING_LIMIT, **filters,
                )
                if r["id"] not in seen
            ]
    matches = exact + english
    if not matches and not related:
        st.info(t("decisions.none"))
        return
    everything = matches + related
    if not matches:
        count = t("search.no_matches")
    else:
        n = len(matches)
        count = t("search.matches_one") if n == 1 else t("search.matches", n=n)
    _results(count, everything, everything[:shown], related_from=len(matches), shown=shown)


def _results(count: str, everything: list[dict], rows: list[dict],
             related_from: int | None, shown: int) -> None:
    """The count, the CSV of everything, the rows shown, and "Show more".
    `related_from` is where the items related by meaning start, if any."""
    state = st.session_state
    head, download = st.columns([2, 1], vertical_alignment="center")
    head.markdown(f"**{count}**")
    download.download_button(
        t("search.csv"), _csv(everything), file_name="council-decisions.csv", mime="text/csv",
    )
    for index, row in enumerate(rows):
        if related_from is not None and index == related_from:
            st.markdown(
                f'<div class="related-head">{t("search.related")}</div>', unsafe_allow_html=True
            )
        _card(row)
    if len(everything) > shown:
        if st.button(t("search.more"), key="dec_more"):
            state["dec_shown"] = shown + PAGE_SIZE
            st.rerun()
