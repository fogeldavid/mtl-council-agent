"""Councillors: the roster, and one member's attendance and recorded votes.

Facts only. Roll-call votes sit beside the member's party majority for
context; nothing is scored or ranked.
"""

from __future__ import annotations

import unicodedata
from html import escape

import pandas as pd
import streamlit as st

from mtl_council_agent.app import queries
from mtl_council_agent.app.common import (
    PAGES,
    display_number,
    fmt_date,
    go,
    open_page,
    outcome_label,
    record_title,
    run,
)
from mtl_council_agent.app.i18n import t

# The mayor's "borough" in the roster is the whole city.
CITY_WIDE = "Ville de Montréal"


def render() -> None:
    if "id" in st.query_params:
        _profile(int(st.query_params["id"]))
    else:
        _list()


def _fold(text: str) -> str:
    """Lowercase without accents, so "helene" finds "Hélène"."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


def _matches(row: dict, name: str, borough: str | None, district: str | None,
             district_borough: str | None) -> bool:
    if name and _fold(name) not in _fold(row["name"]):
        return False
    if borough and row["borough"] != borough:
        return False
    # A district is represented by its councillor and by members elected for its whole borough.
    return not district or row["district"] == district or (
        not row["district"] and row["borough"] == district_borough
    )


def _list() -> None:
    st.markdown(f"## {t('councillors.title')}")
    rows = run(queries.councillors)
    st.caption(t("councillors.hint", n=len(rows)))
    boroughs = sorted({r["borough"] for r in rows if r["borough"] != CITY_WIDE})
    name_col, borough_col, district_col = st.columns([1.3, 1, 1])
    name = name_col.text_input(
        t("councillors.filter"), placeholder=t("councillors.filter_hint"), key="cl_name",
    )
    borough = borough_col.selectbox(
        t("col.borough"), [None, *boroughs], key="cl_borough",
        format_func=lambda b: t("filter.any") if b is None else b,
    )
    district_boroughs = {
        r["district"]: r["borough"] for r in rows
        if r["district"] and (borough is None or r["borough"] == borough)
    }
    districts = [None, *sorted(district_boroughs)]
    # A district from another borough can't stay chosen once the borough changes.
    if st.session_state.get("cl_district") not in districts:
        st.session_state["cl_district"] = None
    district = district_col.selectbox(
        t("col.district"), districts, key="cl_district",
        format_func=lambda d: t("filter.any") if d is None else d,
    )
    shown = [
        r for r in rows
        if _matches(r, name.strip(), borough, district, district_boroughs.get(district))
    ]
    if not shown:
        st.info(t("councillors.none"))
        return
    st.markdown(
        '<div class="list-head people"><span>{}</span><span>{}</span><span>{}</span>'
        "<span>{}</span></div>".format(
            t("col.name"), t("col.role"), t("col.district"), t("col.party"),
        ),
        unsafe_allow_html=True,
    )
    order = sorted({r["borough"] for r in shown}, key=lambda b: (b == CITY_WIDE, b or ""))
    for group in order:
        st.markdown(f'<div class="list-group">{escape(group or "")}</div>',
                    unsafe_allow_html=True)
        for r in sorted((r for r in shown if r["borough"] == group),
                        key=lambda r: (r["district"] is None, r["district"] or "", r["name"])):
            with st.container(key=f"list-row-person-{r['id']}"):
                who, role, where, party = st.columns([1.3, 1, 1.6, 1])
                with who:
                    open_page(r["name"], "councillors", f"open_member_{r['id']}", id=r["id"])
                whole = ("councillors.whole_city" if r["role"] == "mayor"
                         else "councillors.whole_borough")
                where_text = escape(r["district"]) if r["district"] else f"<i>{t(whole)}</i>"
                role.markdown(f'<div class="row-main">{t("role." + r["role"])}</div>',
                              unsafe_allow_html=True)
                where.markdown(f'<div class="row-main">{where_text}</div>',
                               unsafe_allow_html=True)
                party.markdown(f'<div class="row-main">{escape(r["party"] or "—")}</div>',
                               unsafe_allow_html=True)


def _item_table(rows: list[dict], columns: dict[str, callable], key: str) -> None:
    """A table of items; selecting a row opens the item on the Meetings page."""
    if not rows:
        st.caption(t("profile.none"))
        return
    table = pd.DataFrame({name: [fn(r) for r in rows] for name, fn in columns.items()})
    event = st.dataframe(
        table, hide_index=True, width="stretch", on_select="rerun",
        selection_mode="single-row", key=key,
    )
    picked = event.selection.rows if event and event.selection else []
    if picked:
        st.switch_page(PAGES["decisions"], query_params={"item": rows[picked[0]]["id"]})


def _profile(official_id: int) -> None:
    p = run(queries.councillor, official_id)
    if p is None:
        st.warning("Councillor not found.")
        return
    if st.button(f"← {t('back.councillors')}"):
        go()

    st.markdown(f"## {p['name']}")
    st.markdown(" · ".join(x for x in (t("role." + p["role"]) if p["role"] else None,
                                         p["borough"], p["district"], p["party"]) if x))
    a, b, c = st.columns(3)
    attended = f"{p['sittings_present']} {t('profile.of')} {p['sittings_total']}"
    a.metric(t("profile.attended"), attended)
    b.metric(t("profile.moved"), p["moved"])
    c.metric(t("profile.seconded"), p["seconded"])
    absences = p["absent_excused"] + p["absent_unexcused"] + p["absent_barred"]
    if absences:
        st.caption(t("profile.absences", excused=p["absent_excused"],
                     unexcused=p["absent_unexcused"], barred=p["absent_barred"]))

    common = {
        t("col.date"): lambda r: fmt_date(r["meeting_date"]),
        t("col.item"): lambda r: display_number(r["item_number"], r["section"]),
        t("col.title"): lambda r: record_title(r["title"]),
    }

    st.markdown(f"### {t('profile.roll_calls')}")
    st.caption(t("profile.roll_calls_note"))
    _item_table(
        run(queries.councillor_roll_calls, official_id),
        {
            **common,
            t("col.vote"): lambda r: t("pos." + r["position"]),
            t("col.party_vote"): lambda r: (
                t("pos." + r["party_position"]) if r["party_position"] else "—"
            ),
            t("col.outcome"): lambda r: outcome_label(r["vote_outcome"]),
        },
        key=f"roll_{official_id}",
    )

    st.markdown(f"### {t('profile.other')}")
    _item_table(
        run(queries.councillor_other_positions, official_id),
        {**common, t("col.vote"): lambda r: t("pos." + r["position"]),
         t("col.outcome"): lambda r: outcome_label(r["vote_outcome"])},
        key=f"other_{official_id}",
    )

    st.markdown(f"### {t('profile.motions')}")
    _item_table(
        run(queries.councillor_motions, official_id),
        {**common, t("col.how"): lambda r: t("how." + r["role"]),
         t("col.outcome"): lambda r: outcome_label(r["vote_outcome"])},
        key=f"motions_{official_id}",
    )
