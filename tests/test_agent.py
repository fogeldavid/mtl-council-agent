"""Agent loop tests, with the model and database stubbed out.

These cover the loop mechanics that are easy to get subtly wrong -- feeding
parallel tool results back as one message, surfacing tool errors to the model
instead of crashing, and stopping at the turn cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from mtl_council_agent.agent import loop
from mtl_council_agent.agent.tools import ItemResult


@dataclass
class FakeBlock:
    type: str
    text: str = ""
    name: str = ""
    id: str = ""
    input: dict = None


@dataclass
class FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50


@dataclass
class FakeResponse:
    content: list
    stop_reason: str
    usage: FakeUsage = None

    def __post_init__(self):
        if self.usage is None:
            self.usage = FakeUsage()


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        # Snapshot messages: the loop mutates one list across turns, so storing
        # the reference would make every recorded call show the final state.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


@pytest.fixture
def stub_search(monkeypatch):
    item = ItemResult(
        item_id=1,
        meeting_date=date(2026, 6, 15),
        item_number="20.01",
        title="Pont Guy-Lafleur",
        dossier_number="1264139001",
        motion_number="CM26 0677",
        vote_outcome="adopted",
        mover="Julien Hénault-Ratelle",
        seconder="Alan DeSousa",
    )
    monkeypatch.setattr(
        loop.council_tools, "semantic_search", lambda conn, q, limit=8: [item]
    )
    monkeypatch.setattr(
        loop.council_tools, "full_text_search", lambda conn, q, limit=8: [item]
    )
    return item


def test_answers_directly_when_no_tool_needed():
    client = FakeClient([FakeResponse([FakeBlock("text", text="Hello.")], "end_turn")])
    answer = loop.ask(conn=None, question="hi", client=client)
    assert answer.text == "Hello."
    assert answer.turns == 1


def test_parallel_tool_calls_return_in_one_user_message(stub_search):
    client = FakeClient(
        [
            FakeResponse(
                [
                    FakeBlock("tool_use", name="semantic_search", id="a", input={"query": "pont"}),
                    FakeBlock("tool_use", name="full_text_search", id="b", input={"query": "CM26 0677"}),
                ],
                "tool_use",
            ),
            FakeResponse([FakeBlock("text", text="The bridge cost rose.")], "end_turn"),
        ]
    )

    answer = loop.ask(conn=None, question="bridge?", client=client)

    second_request_messages = client.messages.calls[1]["messages"]
    tool_result_messages = [
        m
        for m in second_request_messages
        if m["role"] == "user" and isinstance(m["content"], list)
    ]
    assert len(tool_result_messages) == 1
    assert len(tool_result_messages[0]["content"]) == 2
    assert answer.text == "The bridge cost rose."


def test_citations_are_collected_and_deduplicated(stub_search):
    client = FakeClient(
        [
            FakeResponse(
                [
                    FakeBlock("tool_use", name="semantic_search", id="a", input={"query": "x"}),
                    FakeBlock("tool_use", name="full_text_search", id="b", input={"query": "x"}),
                ],
                "tool_use",
            ),
            FakeResponse([FakeBlock("text", text="Answer.")], "end_turn"),
        ]
    )
    answer = loop.ask(conn=None, question="q", client=client)
    assert answer.citations == ["2026-06-15 item 20.01 / CM26 0677 / dossier 1264139001"]


def test_tool_failure_is_reported_to_the_model_not_raised(monkeypatch):
    def boom(conn, query, limit=8):
        raise RuntimeError("database gone")

    monkeypatch.setattr(loop.council_tools, "semantic_search", boom)
    client = FakeClient(
        [
            FakeResponse(
                [FakeBlock("tool_use", name="semantic_search", id="a", input={"query": "x"})],
                "tool_use",
            ),
            FakeResponse([FakeBlock("text", text="I hit an error.")], "end_turn"),
        ]
    )

    answer = loop.ask(conn=None, question="q", client=client)

    tool_result = client.messages.calls[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert "database gone" in tool_result["content"]
    assert answer.text == "I hit an error."


def test_turn_cap_stops_a_looping_model(stub_search):
    endless = [
        FakeResponse(
            [FakeBlock("tool_use", name="semantic_search", id=str(i), input={"query": "x"})],
            "tool_use",
        )
        for i in range(10)
    ]
    client = FakeClient(endless)

    answer = loop.ask(conn=None, question="q", client=client, max_turns=3)

    assert answer.turns == 3
    assert "search budget" in answer.text


def test_refusal_stop_reason_is_handled():
    client = FakeClient([FakeResponse([], "refusal")])
    answer = loop.ask(conn=None, question="q", client=client)
    assert "declined" in answer.text


def test_cost_estimate_uses_model_rates():
    answer = loop.AgentAnswer(text="", input_tokens=1_000_000, output_tokens=1_000_000)
    assert answer.estimated_cost_usd("claude-opus-5") == pytest.approx(30.0)
    assert answer.estimated_cost_usd("claude-haiku-4-5") == pytest.approx(6.0)
