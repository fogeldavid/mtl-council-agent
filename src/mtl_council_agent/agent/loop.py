"""The agent loop: a hand-written request -> tool -> loop cycle.

Written out rather than delegated to a framework because the loop is the part
worth showing: five tools, an explicit turn cap, and tool results fed back in
one user message per turn (splitting them across messages teaches the model to
stop making parallel calls).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime

import anthropic

from mtl_council_agent.agent import tools as council_tools
from mtl_council_agent.agent.prompts import SYSTEM_PROMPT, TOOL_SCHEMAS

logger = logging.getLogger(__name__)

# Haiku by default: this runs on a free tier and the eval sweeps every question
# on each prompt change, where a 5x cost difference per run decides how often
# the eval actually gets run. Set MTL_AGENT_MODEL=claude-opus-5 for harder
# multi-step questions.
DEFAULT_MODEL = os.environ.get("MTL_AGENT_MODEL", "claude-haiku-4-5")
MAX_TURNS = 8
MAX_TOKENS = 16000


@dataclass
class AgentAnswer:
    text: str
    citations: list[str] = field(default_factory=list)
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def estimated_cost_usd(self, model: str = DEFAULT_MODEL) -> float:
        rates = {
            "claude-opus-5": (5.00, 25.00),
            "claude-sonnet-5": (2.00, 10.00),
            "claude-haiku-4-5": (1.00, 5.00),
        }
        input_rate, output_rate = rates.get(model, rates["claude-opus-5"])
        return (
            self.input_tokens * input_rate + self.output_tokens * output_rate
        ) / 1_000_000


def _serialize_items(items: list[council_tools.ItemResult]) -> str:
    if not items:
        return "No matching records found."
    return json.dumps(
        [
            {
                "item_id": item.item_id,
                "citation": item.citation(),
                "meeting_date": item.meeting_date.isoformat(),
                "item_number": item.item_number,
                "title": item.title,
                "vote_outcome": item.vote_outcome,
                "mover": item.mover,
                "seconder": item.seconder,
                "excerpt": item.excerpt,
            }
            for item in items
        ],
        ensure_ascii=False,
        indent=2,
    )


def _serialize_agenda(items: list[council_tools.ItemResult]) -> str:
    """Compact form for whole-agenda listings.

    A meeting runs to 249 items. Serializing each with its excerpt and vote
    detail would spend tens of thousands of tokens restating a table of
    contents, so a listing carries only what it takes to summarize the agenda
    or pick an item to open with get_item_detail.
    """
    if not items:
        return "No meeting on that date."
    return json.dumps(
        {
            "meeting_date": items[0].meeting_date.isoformat(),
            "item_count": len(items),
            "items": [
                {
                    "item_id": item.item_id,
                    "item_number": item.item_number,
                    "title": item.title,
                    "vote_outcome": item.vote_outcome,
                }
                for item in items
            ],
        },
        ensure_ascii=False,
    )


def _run_tool(conn, name: str, tool_input: dict) -> tuple[str, list[str]]:
    """Execute one tool call; returns (result text, citations seen)."""
    if name == "semantic_search":
        items = council_tools.semantic_search(
            conn, tool_input["query"], tool_input.get("limit", 8)
        )
    elif name == "full_text_search":
        items = council_tools.full_text_search(
            conn, tool_input["query"], tool_input.get("limit", 8)
        )
    elif name == "get_meeting_items":
        meeting_date = datetime.strptime(tool_input["meeting_date"], "%Y-%m-%d").date()
        items = council_tools.get_meeting_items(conn, meeting_date)
        return _serialize_agenda(items), [item.citation() for item in items]
    elif name == "get_official_record":
        items = council_tools.get_official_record(conn, tool_input["name"])
    elif name == "get_item_detail":
        detail = council_tools.get_item_detail(conn, tool_input["item_id"])
        if detail is None:
            return "No item with that id.", []
        item, summary = detail
        payload = {
            "citation": item.citation(),
            "title": item.title,
            "vote_outcome": item.vote_outcome,
            "mover": item.mover,
            "seconder": item.seconder,
            "decision_summary": summary or "(no decision summary on file)",
        }
        return json.dumps(payload, ensure_ascii=False, indent=2), [item.citation()]
    else:
        return f"Unknown tool: {name}", []

    return _serialize_items(items), [item.citation() for item in items]


def ask(
    conn,
    question: str,
    client: anthropic.Anthropic | None = None,
    model: str = DEFAULT_MODEL,
    max_turns: int = MAX_TURNS,
) -> AgentAnswer:
    client = client or anthropic.Anthropic()
    messages: list[dict] = [{"role": "user", "content": question}]
    answer = AgentAnswer(text="")
    seen_citations: list[str] = []

    for turn in range(max_turns):
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        answer.turns = turn + 1
        answer.input_tokens += response.usage.input_tokens
        answer.output_tokens += response.usage.output_tokens

        if response.stop_reason == "refusal":
            answer.text = "The model declined to answer this request."
            return answer

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            answer.text = "".join(
                block.text for block in response.content if block.type == "text"
            )
            answer.citations = list(dict.fromkeys(seen_citations))
            return answer

        # All tool results for one assistant turn go back in ONE user message.
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                result_text, citations = _run_tool(conn, block.name, dict(block.input))
                seen_citations.extend(citations)
                is_error = False
            except Exception as exc:
                logger.exception("tool %s failed", block.name)
                result_text, is_error = f"Tool error: {exc}", True

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                    "is_error": is_error,
                }
            )

        messages.append({"role": "user", "content": tool_results})

    answer.text = (
        "I wasn't able to settle this within the search budget for one question. "
        "Try narrowing it -- a specific date, resolution number, or topic."
    )
    answer.citations = list(dict.fromkeys(seen_citations))
    return answer
