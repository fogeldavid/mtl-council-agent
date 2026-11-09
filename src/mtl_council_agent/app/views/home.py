"""Home: the question box, the record at a glance, and recent contested votes."""

from __future__ import annotations

import streamlit as st

from mtl_council_agent.app import chat, queries
from mtl_council_agent.app.common import display_number, fmt_date, md_text, record_title, run
from mtl_council_agent.app.i18n import t


def render() -> None:
    st.markdown(f"## {t('home.title')}")
    _chat()


EXAMPLES = ("chat.example_1", "chat.example_2", "chat.example_3")


def _about_item() -> list[tuple[str, str, str]]:
    """Starter questions for the item an item page's "Ask" link came from:
    (chip label, question sent, question shown). The question sent carries the
    item_id so the agent can open the item directly; the conversation shows
    the chip's wording and which item it was about."""
    try:
        item = run(queries.item, int(st.query_params.get("about", "")))
    except ValueError:
        return []
    if item is None:
        return []
    values = {
        "number": display_number(item["item_number"], item["section"]),
        "date": fmt_date(item["meeting_date"]),
        "item_id": item["id"],
        "title": item["title"],
    }
    st.caption(t("ask.about", **{**values, "title": record_title(item["title"])}))
    shown = f"({values['number']}, {values['date']})"
    return [
        (t("ask.explain"), t("explain.question", **values), f"{t('ask.explain')} {shown}"),
        (t("ask.related"), t("ask.related_question", **values), f"{t('ask.related')} {shown}"),
    ]


def _chat() -> None:
    log: list[tuple[str, str]] = st.session_state.setdefault("chat", [])
    picked = shown = None
    # Messages go in a box above the input, including ones answered this run.
    box = st.container()
    with box:
        if not log and chat.can_ask():
            starters = _about_item()
            if not starters:
                st.caption(t("chat.try"))
                starters = [(t(key), t(key), t(key)) for key in EXAMPLES]
            with st.container(key="chat-examples"):
                for index, (label, question, display) in enumerate(starters):
                    if st.button(label, key=f"starter_{index}"):
                        picked, shown = question, display
        for question, reply in log:
            st.chat_message("user").markdown(md_text(question))
            st.chat_message("assistant").markdown(md_text(reply))

    question = st.chat_input(t("chat.placeholder"), disabled=not chat.can_ask()) or picked
    if question:
        shown = shown if question == picked else question
        with box:
            st.chat_message("user").markdown(md_text(shown))
            with st.chat_message("assistant"), st.spinner(t("chat.thinking")):
                try:
                    reply = chat.answer(question, log[-chat.HISTORY:])
                except (chat.PoolUnavailable, chat.Busy) as exc:
                    st.warning(chat.error_message(exc))
                else:
                    st.markdown(md_text(reply))
                    log.append((shown, reply))
        # Redraw after the last shared question so the input becomes disabled, and
        # after an example question so the examples make way for the conversation.
        if not chat.can_ask() or picked:
            st.rerun()

    st.caption(t("chat.notice"))
    if chat.can_ask():
        st.caption(t("chat.free_left", n=chat.free_left(), total=chat.FREE_PER_DAY))
    elif not chat.pool_key():
        st.info(t("chat.unavailable"))
    else:
        st.info(t("chat.pool_out"))
    if log and st.button(t("chat.clear")):
        log.clear()
        st.rerun()
