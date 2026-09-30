"""Councillors: the roster, and one member's attendance and recorded votes.

Facts only. Roll-call votes sit beside the member's party majority for
context; nothing is scored or ranked.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from mtl_council_agent.app import queries
from mtl_council_agent.app.common import (
    PAGES,
    display_number,
    fmt_date,
    go,
    masthead,
    outcome_label,
    run,
)
from mtl_council_agent.app.i18n import t


def render() -> None:
    masthead()
    if "id" in st.query_params:
        _profile(int(st.query_params["id"]))
    else:
        _list()


def _list() -> None:
    st.markdown(f"## {t('councillors.title')}")
    st.caption(t("councillors.hint"))
    rows = run(queries.councillors)
    table = pd.DataFrame(
        {
            t("col.name"): [r["name"] for r in rows],
            t("col.role"): [t("role." + r["role"]) for r in rows],
            t("col.borough"): [r["borough"] or "" for r in rows],
            t("col.party"): [r["party"] or "" for r in rows],
        }
    )
    event = st.dataframe(
        table, hide_index=True, width="stretch", height=720, on_select="rerun",
        selection_mode="single-row", key="councillor_list",
    )
    picked = event.selection.rows if event and event.selection else []
    if picked:
        go(id=rows[picked[0]]["id"])


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
        st.switch_page(PAGES["meetings"], query_params={"item": rows[picked[0]]["id"]})


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
        t("col.title"): lambda r: r["title"],
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
