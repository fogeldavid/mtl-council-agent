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

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mtl_council_agent.agent.loop import ask  # noqa: E402
from mtl_council_agent.db import client as db  # noqa: E402

EVAL_SET = Path(__file__).parent / "qa_eval_set.jsonl"
_CITATION_RE = re.compile(r"(\d{4}-\d{2}-\d{2}) item (\S+)")


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


def _check_answer(case: dict, answer_text: str) -> tuple[bool, str]:
    lowered = answer_text.lower()

    if case.get("should_refuse"):
        # The agent should decline rather than fabricate. Accept any of the
        # honest-failure phrasings the system prompt licenses.
        refused = any(
            phrase in lowered
            for phrase in ("don't have", "do not have", "no record", "not find", "outside")
        )
        return refused, "" if refused else "answered instead of declining"

    missing = [
        term for term in case.get("must_include", []) if term.lower() not in lowered
    ]
    forbidden = [
        term for term in case.get("must_not_include", []) if term.lower() in lowered
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
        meeting_date, item_number = match.groups()
        row = conn.execute(
            """
            select 1 from agenda_items ai
            join meetings m on m.id = ai.meeting_id
            where m.meeting_date = %s and ai.item_number = %s
            """,
            (meeting_date, item_number),
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
            answer = ask(conn, case["question"])
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
