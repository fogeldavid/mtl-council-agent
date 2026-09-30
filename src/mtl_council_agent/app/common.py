"""Pieces every page shares: the database connection, masthead, badges, dates."""

from __future__ import annotations

import os
from datetime import date
from html import escape
from pathlib import Path

import psycopg
import streamlit as st
from dotenv import load_dotenv

from mtl_council_agent.app.i18n import lang, t

load_dotenv()

# Filled in by streamlit_app.py, so pages can link to one another.
PAGES: dict = {}

MONTHS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]

BADGE_CLASS = {
    "adopted_unanimous": "b-u",
    "adopted": "b-u",
    "adopted_majority": "b-m",
    "rejected": "b-r",
    "withdrawn": "b-w",
    "noted": "b-n",
    "unknown": "b-n",
    "no_decision": "b-n",
}



def database_url() -> str:
    try:
        url = st.secrets.get("WEB_DATABASE_URL")
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        url = None
    url = url or os.environ.get("WEB_DATABASE_URL")
    if not url:
        raise RuntimeError("WEB_DATABASE_URL is not set")
    return url


@st.cache_resource
def _connection():
    return psycopg.connect(database_url(), autocommit=True)


def run(query, *args, **kwargs):
    """Run one query function, reconnecting once if the connection dropped.

    Neon suspends an idle database after a few minutes, which closes the
    cached connection; the next visitor would otherwise see an error.
    """
    conn = _connection()
    try:
        if conn.closed:
            raise psycopg.OperationalError("connection closed")
        return query(conn, *args, **kwargs)
    except psycopg.OperationalError:
        _connection.clear()
        return query(_connection(), *args, **kwargs)


THEME_CSS = Path(__file__).with_name("theme.css")


def setup_page() -> None:
    st.markdown(f"<style>{THEME_CSS.read_text()}</style>", unsafe_allow_html=True)


def masthead() -> None:
    left, right = st.columns([6, 1], vertical_alignment="center")
    left.markdown(f'<div class="banner">{t("banner")}</div>', unsafe_allow_html=True)
    right.segmented_control(
        "Language", ["EN", "FR"], default="EN", label_visibility="collapsed", key="lang"
    )


def md_text(text: str) -> str:
    """Record text safe for st.markdown / st.caption.

    Streamlit reads text between two dollar signs as a formula, and council
    records are full of amounts like "711 280 $"; unescaped, a title with two
    amounts renders half of itself as math.
    """
    return text.replace("$", "\\$")


def html_text(text: str) -> str:
    """Record text safe inside an HTML snippet passed to st.markdown."""
    return escape(text).replace("$", "&#36;")


def _outcome_key(outcome: str | None, has_minutes: bool) -> str:
    outcome = outcome or "unknown"
    return "no_decision" if outcome == "unknown" and has_minutes else outcome


def badge(outcome: str | None, has_minutes: bool = False) -> str:
    outcome = _outcome_key(outcome, has_minutes)
    return (
        f'<span class="badge {BADGE_CLASS.get(outcome, "b-n")}">'
        f"{escape(t('outcome.' + outcome))}</span>"
    )


def outcome_label(outcome: str | None, has_minutes: bool = False) -> str:
    """The outcome in words. "unknown" means no minutes yet, unless the
    meeting's minutes are in, in which case they simply record no decision."""
    return t("outcome." + _outcome_key(outcome, has_minutes))


def fmt_date(d: date) -> str:
    if lang() == "fr":
        return f"{d.day} {MONTHS_FR[d.month - 1]} {d.year}"
    return f"{d:%B} {d.day}, {d.year}"


def display_number(item_number: str, section: str) -> str:
    """Orientation items are printed "80.01 (20.01)" in the minutes."""
    return f"80.01 ({item_number})" if section == "agglomeration_orientation" else item_number


def go(**params) -> None:
    """Move to another view of the current page via its query parameters."""
    st.query_params.clear()
    for key, value in params.items():
        st.query_params[key] = str(value)
    st.rerun()
