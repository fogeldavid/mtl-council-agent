"""Who pays for a question, and asking it.

Questions are paid from a shared pool first: an Anthropic key in a workspace
capped at $5 a month with auto-reload off, so Anthropic itself stops the
spending. Each visitor gets FREE_PER_DAY pool questions a day, counted in app
memory by IP address; the count resets when the app restarts, which is
accepted for a cap this small. After that, or once the pool's key is refused,
visitors can add their own key. That key lives in their session only.

No question text is stored anywhere, only the per-visitor daily counts.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import anthropic
import streamlit as st

from mtl_council_agent.agent.loop import ask
from mtl_council_agent.agent.prompts import TOOL_SCHEMAS
from mtl_council_agent.app.common import run
from mtl_council_agent.app.i18n import t

FREE_PER_DAY = 5
# Follow-ups carry this many earlier exchanges, so a long conversation's cost
# per question stays flat.
HISTORY = 3
# After the pool's key is refused, stop trying it for a while instead of
# spending every visitor's first click on a request that will fail.
POOL_RETRY_AFTER = timedelta(hours=1)

SEMANTIC_ENABLED = os.environ.get("SEMANTIC_SEARCH", "on").lower() != "off"
CHAT_TOOLS = (
    TOOL_SCHEMAS
    if SEMANTIC_ENABLED
    else [s for s in TOOL_SCHEMAS if s["name"] != "semantic_search"]
)

# How the spend limit and an empty balance come back from the API.
_OUT_OF_FUNDS = re.compile(r"credit|usage limit|spend limit|billing", re.IGNORECASE)


class PoolUnavailable(Exception):
    """The shared key was refused: spend limit reached, no credit, or revoked."""


class KeyRejected(Exception):
    """The visitor's own key was refused."""


class Busy(Exception):
    """Rate-limited or overloaded; worth retrying in a minute."""


@dataclass
class Ledger:
    """Pool questions used per visitor per day, and whether the pool is down."""

    counts: dict
    lock: threading.Lock
    pool_down_until: datetime | None = None

    def used(self, visitor: str, today: date) -> int:
        return self.counts.get((visitor, today), 0)

    def remaining(self, visitor: str, today: date) -> int:
        return max(0, FREE_PER_DAY - self.used(visitor, today))

    def record(self, visitor: str, today: date) -> None:
        with self.lock:
            # Drop earlier days so the dict can't grow without bound.
            for key in [k for k in self.counts if k[1] != today]:
                del self.counts[key]
            self.counts[(visitor, today)] = self.used(visitor, today) + 1

    def pool_up(self, now: datetime) -> bool:
        return self.pool_down_until is None or now >= self.pool_down_until

    def mark_pool_down(self, now: datetime) -> None:
        self.pool_down_until = now + POOL_RETRY_AFTER


@st.cache_resource
def ledger() -> Ledger:
    return Ledger(counts={}, lock=threading.Lock())


def pool_key() -> str | None:
    """The shared pool's key. Deliberately not ANTHROPIC_API_KEY, so a
    developer's personal key in .env is never spent by visitors."""
    try:
        key = st.secrets.get("WEB_ANTHROPIC_API_KEY")
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        key = None
    return key or os.environ.get("WEB_ANTHROPIC_API_KEY")


def visitor_id() -> str:
    # None when running locally or behind a proxy that hides it; everyone in
    # that case shares one allowance, which errs on the side of spending less.
    ip = st.context.ip_address
    return ip if isinstance(ip, str) and ip else "unknown"


def own_key() -> str | None:
    return st.session_state.get("own_key") or None


def can_ask(today: date | None = None, now: datetime | None = None) -> bool:
    """Whether a question can be asked right now, by the pool or the visitor's key."""
    if own_key():
        return True
    return _pool_turn(today or date.today(), now or datetime.now())


def free_left(today: date | None = None) -> int:
    return ledger().remaining(visitor_id(), today or date.today())


def _pool_turn(today: date, now: datetime) -> bool:
    book = ledger()
    return bool(pool_key()) and book.pool_up(now) and book.remaining(visitor_id(), today) > 0


def answer(question: str, history: list[tuple[str, str]] | None = None) -> str:
    """Ask the agent, paying from the pool if this visitor still has free
    questions, otherwise with their own key. Raises PoolUnavailable,
    KeyRejected or Busy for the page to explain."""
    today, now = date.today(), datetime.now()
    use_pool = _pool_turn(today, now)
    key = pool_key() if use_pool else own_key()
    if not key:
        raise PoolUnavailable
    client = anthropic.Anthropic(api_key=key, max_retries=2)
    # Reconnect now if Neon closed the idle connection. Inside the loop a
    # dropped connection would surface as tool errors mid-answer instead.
    run(lambda conn: conn.execute("select 1"))
    try:
        result = run(ask, question, client=client, history=history, tools=CHAT_TOOLS)
    except (anthropic.RateLimitError, anthropic.InternalServerError,
            anthropic.APIConnectionError) as exc:
        raise Busy from exc
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError,
            anthropic.BadRequestError) as exc:
        refused = not isinstance(exc, anthropic.BadRequestError) or _OUT_OF_FUNDS.search(
            str(exc)
        )
        if not refused:
            raise
        if use_pool:
            ledger().mark_pool_down(now)
            raise PoolUnavailable from exc
        raise KeyRejected from exc
    if use_pool:
        ledger().record(visitor_id(), today)
    return result.text


def error_message(exc: Exception) -> str:
    if isinstance(exc, PoolUnavailable):
        return t("chat.pool_out")
    if isinstance(exc, KeyRejected):
        return t("chat.key_rejected")
    return t("chat.busy")
