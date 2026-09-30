"""Who pays for a question: the free pool, its daily allowance, and the
visitor's own key. The model is stubbed; no request leaves the machine."""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta

import anthropic
import httpx
import pytest

from mtl_council_agent.agent.loop import AgentAnswer
from mtl_council_agent.app import chat

TODAY = date(2026, 9, 30)
NOW = datetime(2026, 9, 30, 12, 0)


def _api_error(cls, status: int, message: str):
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.test"))
    return cls(message, response=response, body=None)


@pytest.fixture
def setup(monkeypatch):
    """A fresh ledger, one visitor, a pool key, and a stub agent that records
    which key paid for each question."""
    book = chat.Ledger(counts={}, lock=threading.Lock())
    state = {"own_key": None, "pool_key": "pool-key", "keys_used": [], "raise": None}

    def fake_ask(conn, question, client, history=None, tools=None):
        state["keys_used"].append(client.api_key)
        state["history"] = history
        if state["raise"]:
            raise state["raise"]
        return AgentAnswer(text=f"answer to {question}")

    monkeypatch.setattr(chat, "ledger", lambda: book)
    monkeypatch.setattr(chat, "visitor_id", lambda: "1.2.3.4")
    monkeypatch.setattr(chat, "own_key", lambda: state["own_key"])
    monkeypatch.setattr(chat, "pool_key", lambda: state["pool_key"])
    monkeypatch.setattr(chat, "ask", fake_ask)
    conn = type("Conn", (), {"execute": lambda self, sql: None})()
    monkeypatch.setattr(chat, "run", lambda query, *a, **k: query(conn, *a, **k))
    state["ledger"] = book
    return state


def test_ledger_counts_per_visitor_per_day():
    book = chat.Ledger(counts={}, lock=threading.Lock())
    for _ in range(3):
        book.record("a", TODAY)
    book.record("b", TODAY)
    assert book.remaining("a", TODAY) == chat.FREE_PER_DAY - 3
    assert book.remaining("b", TODAY) == chat.FREE_PER_DAY - 1
    assert book.remaining("a", TODAY + timedelta(days=1)) == chat.FREE_PER_DAY


def test_ledger_forgets_earlier_days():
    book = chat.Ledger(counts={}, lock=threading.Lock())
    book.record("a", TODAY)
    book.record("b", TODAY + timedelta(days=1))
    assert list(book.counts) == [("b", TODAY + timedelta(days=1))]


def test_pool_pays_for_the_first_five_then_stops(setup):
    for _ in range(chat.FREE_PER_DAY):
        assert chat.can_ask()
        chat.answer("q")
    assert setup["keys_used"] == ["pool-key"] * chat.FREE_PER_DAY
    assert not chat.can_ask()
    with pytest.raises(chat.PoolUnavailable):
        chat.answer("q")


def test_own_key_takes_over_after_the_free_questions(setup):
    for _ in range(chat.FREE_PER_DAY):
        chat.answer("q")
    setup["own_key"] = "visitor-key"
    assert chat.can_ask()
    chat.answer("q")
    assert setup["keys_used"][-1] == "visitor-key"


def test_free_questions_are_used_before_the_visitors_key(setup):
    setup["own_key"] = "visitor-key"
    chat.answer("q")
    assert setup["keys_used"] == ["pool-key"]


def test_spend_limit_marks_the_pool_down_for_everyone(setup):
    setup["raise"] = _api_error(
        anthropic.BadRequestError, 400,
        "You have reached your specified workspace API usage limits.",
    )
    with pytest.raises(chat.PoolUnavailable):
        chat.answer("q")
    assert not setup["ledger"].pool_up(datetime.now())
    # A refused request is not counted against the visitor.
    assert setup["ledger"].used("1.2.3.4", date.today()) == 0
    assert not chat.can_ask()


def test_pool_is_retried_after_an_hour():
    book = chat.Ledger(counts={}, lock=threading.Lock())
    book.mark_pool_down(NOW)
    assert not book.pool_up(NOW + timedelta(minutes=59))
    assert book.pool_up(NOW + chat.POOL_RETRY_AFTER)


def test_a_bad_own_key_is_reported_as_such(setup):
    setup["pool_key"] = None
    setup["own_key"] = "bad-key"
    setup["raise"] = _api_error(anthropic.AuthenticationError, 401, "invalid x-api-key")
    with pytest.raises(chat.KeyRejected):
        chat.answer("q")


def test_rate_limit_is_busy_not_a_refusal(setup):
    setup["raise"] = _api_error(anthropic.RateLimitError, 429, "rate limited")
    with pytest.raises(chat.Busy):
        chat.answer("q")
    assert setup["ledger"].pool_up(datetime.now())


def test_other_bad_requests_are_not_mistaken_for_a_spent_pool(setup):
    setup["raise"] = _api_error(anthropic.BadRequestError, 400, "messages: invalid role")
    with pytest.raises(anthropic.BadRequestError):
        chat.answer("q")
    assert setup["ledger"].pool_up(datetime.now())


def test_no_pool_key_and_no_own_key_cannot_ask(setup):
    setup["pool_key"] = None
    assert not chat.can_ask()


def test_history_is_passed_through(setup):
    chat.answer("and who voted against?", [("what was 20.06?", "A cancellation.")])
    assert setup["history"] == [("what was 20.06?", "A cancellation.")]
