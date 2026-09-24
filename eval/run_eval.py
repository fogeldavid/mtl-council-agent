"""Scores the agent against a hand-labeled question set.

Two things are measured, because they fail independently:

  answer correctness -- does the response contain what it should, and (for
                        refusal cases) does it correctly decline instead of
                        inventing something
  citation validity  -- does every citation the agent printed correspond to a
                        record that actually exists in the database

The second matters most. An agent that is right but cites nothing, or cites
something plausible-looking that isn't real, is exactly the failure mode that
makes a civic-information tool untrustworthy.

Usage:  python eval/run_eval.py [--limit N] [--verbose]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import anthropic
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mtl_council_agent.agent.loop import ask  # noqa: E402
from mtl_council_agent.db import client as db  # noqa: E402

EVAL_SET = Path(__file__).parent / "qa_eval_set.jsonl"
# Orientation items cite as "80.01 (20.01)": the inner number and the section
# identify them, since a council item can share the inner number.
_CITATION_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}) item (?:80\.01 \((?P<inner>\d{2}\.\d{2})\)|(?P<plain>[\d.]+))"
)
_NON_DIGITS = re.compile(r"\D+")

# The records are French but answers come back in the user's language, so the
# same figure appears as "66 758,51 $" or "$66,758.51" depending on the
# question. Matching raw substrings tests number formatting, not correctness.
_EQUIVALENT_CHARS = {"’": "'", " ": " ", " ": " ", "‑": "-"}


def _normalize(text: str) -> str:
    for source, target in _EQUIVALENT_CHARS.items():
        text = text.replace(source, target)
    return " ".join(text.lower().split())


def _contains(answer: str, term: str) -> bool:
    if _normalize(term) in _normalize(answer):
        return True
    # Compare figures digit-only, so separators and currency placement don't
    # decide the outcome. Short runs are excluded: "10" would match anything.
    digits = _NON_DIGITS.sub("", term)
    if len(digits) >= 4:
        return digits in _NON_DIGITS.sub("", answer)
    return False


@dataclass
class CaseResult:
    question: str
    passed_answer: bool
    passed_citations: bool
    answer: str
    notes: str = ""


def _load_cases(limit: int | None) -> list[dict]:
    cases = [
        json.loads(line)
        for line in EVAL_SET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return cases[:limit] if limit else cases


_REFUSAL_PHRASES = (
    "don't have", "do not have", "dont have", "no record", "not find", "outside",
    "not in my database", "aren't in my database", "isn't in my database",
    "only have", "only cover", "beyond what", "can't tell you", "cannot tell you",
)


def _check_answer(case: dict, answer_text: str) -> tuple[bool, str]:
    normalized = _normalize(answer_text)

    if case.get("should_refuse"):
        # The agent should decline rather than fabricate. Accept any of the
        # honest-failure phrasings the system prompt licenses.
        refused = any(phrase in normalized for phrase in _REFUSAL_PHRASES)
        return refused, "" if refused else "answered instead of declining"

    missing = [
        term for term in case.get("must_include", []) if not _contains(answer_text, term)
    ]
    forbidden = [
        term for term in case.get("must_not_include", []) if _contains(answer_text, term)
    ]
    notes = []
    if missing:
        notes.append(f"missing: {missing}")
    if forbidden:
        notes.append(f"forbidden present: {forbidden}")
    return not missing and not forbidden, "; ".join(notes)


def _check_citations(conn, citations: list[str]) -> tuple[bool, str]:
    """Every cited record must exist. An unverifiable citation is a failure."""
    if not citations:
        return False, "no citations"

    for citation in citations:
        match = _CITATION_RE.search(citation)
        if not match:
            return False, f"unparseable citation: {citation!r}"
        meeting_date = match.group(1)
        section = "agglomeration_orientation" if match.group("inner") else "council"
        item_number = match.group("inner") or match.group("plain")
        row = conn.execute(
            """
            select 1 from agenda_items ai
            join meetings m on m.id = ai.meeting_id
            where m.meeting_date = %s and ai.item_number = %s and ai.section = %s
            """,
            (meeting_date, item_number, section),
        ).fetchone()
        if row is None:
            return False, f"citation not found in database: {citation}"

    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    cases = _load_cases(args.limit)
    results: list[CaseResult] = []

    with db.connect() as conn:
        for case in cases:
            try:
                answer = ask(conn, case["question"])
            except anthropic.APIStatusError as exc:
                # Stop rather than scoring the remaining cases as failures: an
                # exhausted balance would otherwise look like a quality drop.
                print(f"\nAborted on model API error ({exc.status_code}): {exc.message}")
                print(f"Scored {len(results)} of {len(cases)} cases before stopping.")
                break
            answer_ok, answer_notes = _check_answer(case, answer.text)

            if case.get("should_refuse"):
                citations_ok, citation_notes = True, ""
            else:
                citations_ok, citation_notes = _check_citations(conn, answer.citations)

            results.append(
                CaseResult(
                    question=case["question"],
                    passed_answer=answer_ok,
                    passed_citations=citations_ok,
                    answer=answer.text,
                    notes="; ".join(n for n in (answer_notes, citation_notes) if n),
                )
            )

            if args.verbose:
                status = "PASS" if answer_ok and citations_ok else "FAIL"
                print(f"[{status}] {case['question']}")
                if results[-1].notes:
                    print(f"        {results[-1].notes}")

    total = len(results)
    if not total:
        print("No cases scored.")
        return 1

    answer_score = sum(r.passed_answer for r in results) / total
    citation_score = sum(r.passed_citations for r in results) / total
    both = sum(r.passed_answer and r.passed_citations for r in results) / total

    print(f"\ncases:              {total}")
    print(f"answer correctness: {answer_score:.1%}")
    print(f"citation validity:  {citation_score:.1%}")
    print(f"both:               {both:.1%}")

    failures = [r for r in results if not (r.passed_answer and r.passed_citations)]
    if failures and not args.verbose:
        print("\nfailures:")
        for failure in failures:
            print(f"  - {failure.question}: {failure.notes}")

    return 0 if both == 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
