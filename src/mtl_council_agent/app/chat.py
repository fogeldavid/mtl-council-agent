"""Ask questions using the team key configured on the server.

Each visitor receives a daily in-memory allowance. A missing/refused shared key
or exhausted allowance disables chat; visitors never supply credentials.
Configure spending controls in the provider account separately.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import anthropic
import streamlit as st

from mtl_council_agent.agent.dates import dates_in
from mtl_council_agent.agent.loop import ask
from mtl_council_agent.agent.prompts import TOOL_SCHEMAS
from mtl_council_agent.app.common import fmt_date, run
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


def can_ask(today: date | None = None, now: datetime | None = None) -> bool:
    """Whether the shared service has capacity for this visitor."""
    return _pool_turn(today or date.today(), now or datetime.now())


def free_left(today: date | None = None) -> int:
    return ledger().remaining(visitor_id(), today or date.today())


def _pool_turn(today: date, now: datetime) -> bool:
    book = ledger()
    return bool(pool_key()) and book.pool_up(now) and book.remaining(visitor_id(), today) > 0


def with_sources(text: str, documents: list[dict]) -> str:
    """Add database-owned links for the meetings the answer names, so an answer
    that found nothing doesn't list everything its searches touched. These cover
    a whole meeting, not one claim, and the heading says so. A document the
    answer already links to (the model sometimes puts the minutes link on its
    citation) isn't listed again."""
    named = dates_in(text)
    lines = [
        f"- [{fmt_date(date.fromisoformat(d['meeting_date']))} · {t('doc.' + d['doc_type'])}]"
        f"(<{d['url']}>)"  # Angle brackets keep query strings inside the URL.
        for d in documents if d["meeting_date"] in named and d["url"] not in text
    ]
    return f"{text}\n\n{t('chat.sources')}\n\n" + "\n".join(lines) if lines else text


def answer(question: str, history: list[tuple[str, str]] | None = None) -> str:
    """Ask with the server's shared key; never fall back to visitor credentials."""
    today, now = date.today(), datetime.now()
    if not _pool_turn(today, now):
        raise PoolUnavailable
    key = pool_key()
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
        ledger().mark_pool_down(now)
        raise PoolUnavailable from exc
    ledger().record(visitor_id(), today)
    return with_sources(result.text, result.source_documents)


def error_message(exc: Exception) -> str:
    if isinstance(exc, PoolUnavailable):
        return t("chat.pool_out")
    return t("chat.busy")
