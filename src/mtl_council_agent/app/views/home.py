"""Home: the question box, the record at a glance, and recent contested votes."""

from __future__ import annotations

import streamlit as st

from mtl_council_agent.app import chat
from mtl_council_agent.app.common import md_text
from mtl_council_agent.app.i18n import t


def render() -> None:
    st.markdown(f"## {t('home.title')}")
    _chat()


EXAMPLES = ("chat.example_1", "chat.example_2", "chat.example_3")


def _chat() -> None:
    log: list[tuple[str, str]] = st.session_state.setdefault("chat", [])
    picked = None
    # Messages go in a box above the input, including ones answered this run.
    box = st.container()
    with box:
        if not log and chat.can_ask():
            st.caption(t("chat.try"))
            with st.container(key="chat-examples"):
                for key in EXAMPLES:
                    if st.button(t(key), key=key):
                        picked = t(key)
        for question, reply in log:
            st.chat_message("user").markdown(md_text(question))
            st.chat_message("assistant").markdown(md_text(reply))

    question = st.chat_input(t("chat.placeholder"), disabled=not chat.can_ask()) or picked
    if question:
        with box:
            st.chat_message("user").markdown(md_text(question))
            with st.chat_message("assistant"), st.spinner(t("chat.thinking")):
                try:
                    reply = chat.answer(question, log[-chat.HISTORY:])
                except (chat.PoolUnavailable, chat.Busy) as exc:
                    st.warning(chat.error_message(exc))
                else:
                    st.markdown(md_text(reply))
                    log.append((question, reply))
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
