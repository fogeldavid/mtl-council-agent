"""Meetings: the list, one meeting's agenda, and one item with its votes.

Which of the three shows is set by the page's query parameters, so every
view has its own shareable address (?meeting=12, ?item=345).
"""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from mtl_council_agent.agent.tools import get_vote_detail
from mtl_council_agent.app import chat, queries
from mtl_council_agent.app.common import (
    PAGES,
    badge,
    display_number,
    fmt_date,
    go,
    html_text,
    masthead,
    md_text,
    outcome_label,
    run,
)
from mtl_council_agent.app.i18n import t


def render() -> None:
    masthead()
    params = st.query_params
    if "item" in params:
        _item_view(int(params["item"]))
    elif "meeting" in params:
        _meeting_view(int(params["meeting"]))
    else:
        _list_view()


def _selected_row(event) -> int | None:
    rows = event.selection.rows if event and event.selection else []
    return rows[0] if rows else None


def _list_view() -> None:
    st.markdown(f"## {t('meetings.title')}")
    st.caption(t("meetings.hint"))
    rows = run(queries.meetings)
    table = pd.DataFrame(
        {
            t("col.date"): [fmt_date(r["meeting_date"]) for r in rows],
            t("col.type"): [t("meeting." + r["meeting_type"]) for r in rows],
            t("col.items"): [r["items"] for r in rows],
            t("col.minutes"): [t("yes") if r["has_minutes"] else t("no") for r in rows],
        }
    )
    event = st.dataframe(
        table, hide_index=True, width="stretch", on_select="rerun",
        selection_mode="single-row", key="meeting_list",
    )
    picked = _selected_row(event)
    if picked is not None:
        go(meeting=rows[picked]["id"])


def _meeting_view(meeting_id: int) -> None:
    info = run(queries.meeting, meeting_id)
    if info is None:
        st.warning("Meeting not found.")
        return
    if st.button(f"← {t('back.meetings')}"):
        go()
    st.markdown(f"## {fmt_date(info['meeting_date'])} · {t('meeting.' + info['meeting_type'])}")

    attendance = run(queries.meeting_attendance, meeting_id)
    if attendance:
        st.caption(" · ".join(
            f"{t('meeting.sitting')} {a['sitting'] + 1}: {a['present']} {t('meeting.present')}, "
            f"{a['absent']} {t('meeting.absent')}"
            for a in attendance
        ))
    if not info["has_minutes"]:
        st.info(t("meeting.no_minutes"))

    items = run(queries.meeting_items, meeting_id)
    st.caption(t("meeting.items_hint"))
    table = pd.DataFrame(
        {
            t("col.item"): [display_number(i["item_number"], i["section"]) for i in items],
            t("col.title"): [i["title"] for i in items],
            t("col.outcome"): [
                outcome_label(i["vote_outcome"], info["has_minutes"]) for i in items
            ],
        }
    )
    event = st.dataframe(
        table, hide_index=True, width="stretch", height=640, on_select="rerun",
        selection_mode="single-row", key=f"items_{meeting_id}",
        column_config={
            t("col.item"): st.column_config.TextColumn(width="small"),
            t("col.title"): st.column_config.TextColumn(width="large"),
            t("col.outcome"): st.column_config.TextColumn(width="small"),
        },
    )
    picked = _selected_row(event)
    if picked is not None:
        go(item=items[picked]["id"])


def _names(names: list[str]) -> str:
    return "".join(f'<span class="chip">{html_text(n)}</span>' for n in names)


def _item_view(item_id: int) -> None:
    it = run(queries.item, item_id)
    if it is None:
        st.warning("Item not found.")
        return
    if st.button(f"← {t('back.meeting')}"):
        go(meeting=it["meeting_id"])

    number = display_number(it["item_number"], it["section"])
    st.caption(f"{fmt_date(it['meeting_date'])} · {number}")
    tags = [badge(it["vote_outcome"], it["has_minutes"])]
    dossier = it["dossier_number"] and f"dossier {it['dossier_number']}"
    tags += [
        f'<span class="cite">{html_text(x)}</span>' for x in (it["motion_number"], dossier) if x
    ]
    st.markdown(" ".join(tags), unsafe_allow_html=True)
    st.markdown(f"### {md_text(it['title'])}")

    byline = []
    if it["department"]:
        byline.append(it["department"])
    if it["mover"]:
        byline.append(t("item.moved_by", mover=it["mover"], seconder=it["seconder"] or "—"))
    if byline:
        st.caption(md_text(" · ".join(byline)))

    left, right = st.columns([1.6, 1], gap="large")
    with left:
        st.markdown(f"#### {t('item.summary')}")
        if it["decision_summary"]:
            st.markdown(
                f'<div class="summary" lang="fr">{html_text(it["decision_summary"])}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.caption(t("item.no_summary"))
        _explain(it, number)
        docs = run(queries.meeting_documents, it["meeting_id"])
        if "agenda" in docs:
            st.link_button(t("item.pdf_agenda"), docs["agenda"])
        if "minutes" in docs:
            st.link_button(t("item.pdf_minutes"), docs["minutes"])

    with right:
        _votes(it)


def _explain(it: dict, number: str) -> None:
    """A plain-language explanation from the chat agent, kept for the session
    so reopening the item doesn't pay for it twice."""
    done: dict = st.session_state.setdefault("explained", {})
    key = (it["id"], t("explain.button"))
    if key in done:
        st.markdown(md_text(done[key]))
        st.caption(t("chat.notice"))
        return
    if not chat.can_ask():
        st.caption(t("explain.needs_key"))
        st.page_link(PAGES["ask"], label=f"{t('nav.ask')} →")
        return
    if st.button(t("explain.button")):
        question = t(
            "explain.question", number=number, date=fmt_date(it["meeting_date"]),
            item_id=it["id"], title=it["title"],
        )
        with st.spinner(t("chat.thinking")):
            try:
                done[key] = chat.answer(question)
            except (chat.PoolUnavailable, chat.KeyRejected, chat.Busy) as exc:
                st.warning(chat.error_message(exc))
                return
        st.markdown(md_text(done[key]))
    st.caption(t("chat.notice"))


def _votes(it: dict) -> None:
    st.markdown(f"#### {t('item.votes')}")
    detail = run(get_vote_detail, it["id"])
    roll_call = "roll_call" in detail.recorded_by
    n_for = len(detail.recorded_for) if roll_call else len(detail.inferred_for or [])
    n_against = len(detail.recorded_against)

    if n_for or n_against:
        total = n_for + n_against
        st.markdown(
            f'<div class="bar">'
            f'<div style="width:{100 * n_for / total:.1f}%;background:#1F4E79"></div>'
            f'<div style="width:{100 * n_against / total:.1f}%;background:#C8281E"></div>'
            f"</div>",
            unsafe_allow_html=True,
        )
        for_how = t("item.recorded") if roll_call else t("item.inferred")
        st.markdown(
            f'<b style="color:#1F4E79">{n_for} {t("item.for")}</b> ({for_how}) · '
            f'<b style="color:#A8231A">{n_against} {t("item.against")}</b> ({t("item.recorded")})',
            unsafe_allow_html=True,
        )

    if roll_call:
        note = t("item.note.roll_call")
    elif it["vote_outcome"] == "adopted_unanimous" and detail.inferred_for is not None:
        note = t("item.note.unanimous")
    elif it["vote_outcome"] == "adopted_majority":
        note = t("item.note.majority_named" if n_against else "item.note.majority_unnamed")
    else:
        note = t("item.note.none")
    if it["section"] == "agglomeration_orientation":
        note = t("item.note.orientation") + " " + note
    st.markdown(f'<div class="note">{escape(note)}</div>', unsafe_allow_html=True)

    if detail.recorded_against:
        st.markdown(f"**{t('item.recorded_against')}**")
        st.markdown(_names(detail.recorded_against), unsafe_allow_html=True)
    if roll_call and detail.recorded_for:
        st.markdown(f"**{t('item.recorded_for')}**")
        st.markdown(_names(detail.recorded_for), unsafe_allow_html=True)
    if detail.recorded_abstained:
        st.markdown(f"**{t('item.abstained')}**")
        st.markdown(_names(detail.recorded_abstained), unsafe_allow_html=True)

    if it["mover_id"]:
        st.page_link(PAGES["councillors"], label=f"{it['mover']} →",
                     query_params={"id": it["mover_id"]})
