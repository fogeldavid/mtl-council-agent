"""Home: the question box, the record at a glance, and recent contested votes."""

from __future__ import annotations

import streamlit as st

from mtl_council_agent.app import chat, queries
from mtl_council_agent.app.common import (
    PAGES,
    badge,
    fmt_date,
    html_text,
    masthead,
    md_text,
    run,
)
from mtl_council_agent.app.i18n import t


def render() -> None:
    masthead()
    left, right = st.columns([1.6, 1], gap="large")

    with left:
        st.markdown(f"## {t('home.title')}")
        _chat()

    with right:
        s = run(queries.stats)
        st.markdown(f"### {t('home.record')}")
        a, b = st.columns(2)
        a.metric(t("stat.meetings"), s["meetings"])
        b.metric(t("stat.items"), f"{s['items']:,}")
        a.metric(t("stat.votes"), f"{s['recorded_votes']:,}")
        b.metric(t("stat.members"), s["members"])
        updated = run(queries.latest_update)
        if updated:
            st.caption(t("updated", date=fmt_date(updated)))

        st.markdown(f"### {t('home.contested')}")
        for vote in run(queries.contested_votes, 3):
            how = (
                f"{vote['votes_for']}–{vote['votes_against']} {t('roll_call')}"
                if vote["roll_call"]
                else f"{vote['votes_against']} {t('dissent')}"
            )
            st.markdown(
                f'<div class="card"><div class="title">{html_text(vote["title"][:140])}</div>'
                f'<div class="meta">{fmt_date(vote["meeting_date"])} · '
                f'{badge(vote["vote_outcome"])} {how}</div></div>',
                unsafe_allow_html=True,
            )
            st.page_link(
                PAGES["meetings"],
                label=t("search.open", number=vote["item_number"]),
                query_params={"item": vote["id"]},
            )


def _chat() -> None:
    log: list[tuple[str, str]] = st.session_state.setdefault("chat", [])
    # Messages go in a box above the input, including ones answered this run.
    box = st.container()
    with box:
        if not log:
            st.caption(t("chat.examples"))
        for question, reply in log:
            st.chat_message("user").markdown(md_text(question))
            st.chat_message("assistant").markdown(md_text(reply))

    question = st.chat_input(t("chat.placeholder"), disabled=not chat.can_ask())
    if question:
        with box:
            st.chat_message("user").markdown(md_text(question))
            with st.chat_message("assistant"), st.spinner(t("chat.thinking")):
                try:
                    reply = chat.answer(question, log[-chat.HISTORY:])
                except (chat.PoolUnavailable, chat.KeyRejected, chat.Busy) as exc:
                    st.warning(chat.error_message(exc))
                else:
                    st.markdown(md_text(reply))
                    log.append((question, reply))
        # The input above was drawn before this answer used the last free
        # question; redraw so it shows as closed and the key box appears.
        if not chat.can_ask():
            st.rerun()

    st.caption(t("chat.notice"))
    if chat.own_key():
        st.caption(t("chat.using_own_key"))
    elif chat.can_ask():
        st.caption(t("chat.free_left", n=chat.free_left(), total=chat.FREE_PER_DAY))
    if log and st.button(t("chat.clear")):
        log.clear()
        st.rerun()
    if not chat.can_ask() or chat.own_key():
        _own_key()


def _keep_key() -> None:
    # A widget's value is dropped once the widget stops rendering, so the key
    # is copied to a plain session entry that outlives the form.
    st.session_state["own_key"] = st.session_state.pop("own_key_field", "").strip()


def _own_key() -> None:
    if chat.own_key():
        if st.button(t("chat.forget_key")):
            st.session_state.pop("own_key", None)
            st.rerun()
        return
    st.info(t("chat.out_of_free"))
    st.text_input(
        t("chat.key_label"), type="password", key="own_key_field", on_change=_keep_key,
    )
    st.caption(t("chat.key_help"))
