"""Meetings: the list, one meeting's agenda, and one item with its votes.

Which of the three shows is set by the page's query parameters, so every
view has its own shareable address (?meeting=12, ?item=345).
"""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from mtl_council_agent import minutes_text
from mtl_council_agent.agent.tools import get_vote_detail
from mtl_council_agent.app import queries, translations
from mtl_council_agent.app.common import (
    badge,
    display_number,
    fmt_date,
    go,
    html_text,
    md_text,
    open_page,
    outcome_label,
    record_title,
    run,
)
from mtl_council_agent.app.i18n import lang, t


def render() -> None:
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
    rows = run(queries.meetings)
    st.caption(t("meetings.count", n=len(rows)))
    for r in rows:
        status = "ok" if r["has_minutes"] else "wait"
        with st.container(key=f"list-row-meeting-{r['id']}"):
            when, about, count = st.columns([2.2, 3.4, 1])
            with when:
                open_page(fmt_date(r["meeting_date"]), "meetings", f"open_meeting_{r['id']}",
                          meeting=r["id"])
            about.markdown(
                f'<div class="row-main">{t("meeting." + r["meeting_type"]).capitalize()}</div>'
                f'<div class="row-status {status}">'
                f'{t("meetings.minutes" if r["has_minutes"] else "meetings.agenda_only")}</div>',
                unsafe_allow_html=True,
            )
            count.markdown(
                f'<div class="row-count">{t("meetings.items", n=r["items"])}</div>',
                unsafe_allow_html=True,
            )


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
            t("col.title"): [record_title(i["title"]) for i in items],
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


# English pages can show the French original in place, for comparing a line.
ORIGINAL_KEY = "item_show_original"


def _showing_original() -> bool:
    return lang() == "en" and st.session_state.get(ORIGINAL_KEY, False)


def _item_view(item_id: int, from_feed: bool = False) -> None:
    it = run(queries.item, item_id)
    if it is None:
        st.warning("Item not found.")
        return
    back_label = t("feed.back") if from_feed else t("back.meeting")
    if st.button(f"← {back_label}"):
        if from_feed:
            go()
        else:
            go(meeting=it["meeting_id"])

    original = _showing_original()
    number = display_number(it["item_number"], it["section"])
    st.caption(f"{fmt_date(it['meeting_date'])} · {number}")
    tags = [badge(it["vote_outcome"], it["has_minutes"])]
    dossier = it["dossier_number"] and f"dossier {it['dossier_number']}"
    tags += [
        f'<span class="cite">{html_text(x)}</span>' for x in (it["motion_number"], dossier) if x
    ]
    st.markdown(" ".join(tags), unsafe_allow_html=True)
    title = it["title"] if original else record_title(it["title"])
    st.markdown(f"### {md_text(title)}")

    if it["department"]:
        department = translations.department_name(it["department"])
        if lang() == "en" and not original:
            department = translations.english(department) or department
        st.caption(md_text(department))

    excerpt = translations.context_excerpt(it["decision_summary"])
    english_context = translations.english(excerpt)
    left, right = st.columns([1.6, 1], gap="large")
    with left:
        if lang() == "en":
            translated = translations.english(it["title"]) or english_context
            _translation_note(original, bool(translated))
        if lang() == "en" and not original:
            if it["decision_summary"]:
                st.markdown(f"#### {t('translation.context')}")
                if english_context:
                    st.write(md_text(english_context))
                else:
                    st.caption(t("translation.context_missing"))
        elif it["decision_summary"]:
            st.markdown(f"#### {t('item.summary')}")
            st.markdown(
                f'<div class="summary" lang="fr">{html_text(it["decision_summary"])}</div>',
                unsafe_allow_html=True,
            )
        _minutes(it, original)
        with st.container(key="item-ask"):
            open_page(t("item.ask"), "ask", "ask_about", about=it["id"])

    with right:
        _votes(it)
        _sources(it)


def _translation_note(original: bool, translated: bool) -> None:
    """One note for the whole page, and the switch to the French original. A
    page with nothing translated yet says so rather than claim a translation."""
    with st.container(key="translation-note", horizontal=True, gap="small"):
        st.caption(t("translation.note" if translated or original else "translation.pending"))
        label = "translation.show_english" if original else "translation.show_original"
        if st.button(t(label), key="toggle_original", type="tertiary"):
            st.session_state[ORIGINAL_KEY] = not original
            st.rerun()


def _sources(it: dict) -> None:
    docs = run(queries.meeting_documents, it["meeting_id"])
    links = []
    if "minutes" in docs:
        page = it["minutes_page"]
        links.append((
            t("item.src_minutes_page", page=page) if page else t("item.src_minutes"),
            f'{docs["minutes"]}#page={page}' if page else docs["minutes"],
        ))
    if "agenda" in docs:
        links.append((t("item.src_agenda"), docs["agenda"]))
    if "bundle" in docs:
        links.append((t("item.src_bundle"), docs["bundle"]))
    if not links:
        return
    st.markdown(
        f'<div class="sources-label">{t("item.sources")}</div>'
        f'<div class="sources-note">{t("item.sources_note")}</div>',
        unsafe_allow_html=True,
    )
    with st.container(key="item-sources"):
        for label, url in links:
            st.link_button(label, url)


def _in_reading_language(parts: list[str], original: bool) -> tuple[list[str], str]:
    """The paragraphs in English when every one has a saved translation, else
    in French: a half-translated resolution would read as one text in two
    languages."""
    if lang() == "en" and not original and parts:
        english = [translations.english(p) for p in parts]
        if all(english):
            return english, "en"
    return parts, "fr"


def _paragraphs(parts: list[str], original: bool) -> None:
    shown, language = _in_reading_language(parts, original)
    # One <div> per paragraph on a single line: a blank line inside the HTML
    # would end it as far as markdown is concerned, and the renderer drops a
    # leading <p>, which left the first paragraph as bare text.
    text = "".join(f"<div>{html_text(p)}</div>" for p in shown)
    st.markdown(
        f'<div class="summary minutes" lang="{language}">{text}</div>',
        unsafe_allow_html=True,
    )
    if lang() == "en" and not original and language == "fr":
        st.caption(t("minutes.untranslated"))


def _minutes(it: dict, original: bool) -> None:
    """What the minutes record council adopted, and for items without a
    decision summary (declarations, councillors' motions), the full entry."""
    if not it["minutes_text"]:
        if not it["decision_summary"]:
            st.caption(t("item.no_summary"))
        return
    clauses = minutes_text.resolved(it["minutes_text"])
    entry = minutes_text.body(it["minutes_text"])
    if clauses:
        outcome = it["vote_outcome"] or ""
        heading = (
            "minutes.adopted" if outcome.startswith("adopted")
            else "minutes.rejected" if outcome == "rejected"
            else "minutes.proposed" if outcome == "referred" else "minutes.voted_on"
        )
        st.markdown(f"#### {t(heading)}")
        _paragraphs(clauses, original)
    if it["decision_summary"] or not entry or not minutes_text.adds_to_resolved(it["minutes_text"]):
        return
    if clauses:
        with st.expander(t("minutes.full")):
            _paragraphs(entry, original)
    else:
        st.markdown(f"#### {t('minutes.entry')}")
        _paragraphs(entry, original)


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
    elif it["vote_outcome"] == "adopted_unanimous":
        note = t("item.note.unanimous_unnamed")
    elif it["vote_outcome"] == "adopted_majority":
        note = t("item.note.majority_named" if n_against else "item.note.majority_unnamed")
    elif it["vote_outcome"] == "referred":
        note = t("item.note.referred")
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

    with st.container(key="item-people"):
        for label, name, official_id in (
            ("item.moved_by", it["mover"], it["mover_id"]),
            ("item.seconded_by", it["seconder"], it["seconder_id"]),
        ):
            if official_id:
                open_page(t(label, name=name), "councillors", f"{label}_{official_id}",
                          id=official_id)
