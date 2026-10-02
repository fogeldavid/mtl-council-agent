"""Scores the agent against a hand-labeled question set.

Two things are measured, because they fail independently:

  answer correctness -- does the response contain what it should, and (for
                        refusal cases) does it correctly decline instead of
                        inventing something
  citation validity  -- does the answer print citations, and does every one
                        correspond to a record that actually exists in the
                        database

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
    # Scope refusals for borough and agglomeration questions. The agent words
    # them many ways ("I cover the central city council only"), and a run that
    # declined correctly was scored as answering because none matched.
    "don't cover", "do not cover", "city council only", "not the borough",
    "not the 19 borough", "not in my database",
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


_MONTHS = {
    name: number
    for number, names in enumerate(
        [("january", "janvier"), ("february", "février"), ("march", "mars"),
         ("april", "avril"), ("may", "mai"), ("june", "juin"), ("july", "juillet"),
         ("august", "août"), ("september", "septembre"), ("october", "octobre"),
         ("november", "novembre"), ("december", "décembre")],
        start=1,
    )
    for name in names
}
_MONTH = "|".join(_MONTHS)
_DATE_RES = (
    re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b"),
    re.compile(rf"\b(?P<mon>{_MONTH})\s+(?P<d>\d{{1,2}}),?\s+(?P<y>\d{{4}})", re.IGNORECASE),
    re.compile(rf"\b(?P<d>\d{{1,2}})(?:er)?\s+(?P<mon>{_MONTH})\s+(?P<y>\d{{4}})", re.IGNORECASE),
)
# "item 20.01", "items 20.01", "point 20.01", and orientation items written as
# "80.01 (20.01)": the inner number and the section identify them, since a
# council item can share the inner number.
_NUMBER = r"(?:80\.01\s*\(\d{2}\.\d{2}\)|\d{2}\.\d{2})"
# A keyword followed by one number or a list: "items 20.01, 20.02 and 20.05".
_ITEM_REF_RE = re.compile(
    rf"\b(?:items?|points?|section)\s+{_NUMBER}(?:\s*(?:,|and|et|–|-|to|à)\s*{_NUMBER})*"
    r"|\b80\.01\b(?:\s*\(\d{2}\.\d{2}\))?",
    re.IGNORECASE,
)
_ORIENTATION_RE = re.compile(r"80\.01\s*\((\d{2}\.\d{2})\)")


def _dates_in(answer_text: str) -> set[str]:
    dates = set()
    for pattern in _DATE_RES:
        for m in pattern.finditer(answer_text):
            month = int(m.group("m")) if "m" in m.groupdict() and m.group("m") else (
                _MONTHS[m.group("mon").lower()]
            )
            dates.add(f"{int(m.group('y')):04d}-{month:02d}-{int(m.group('d')):02d}")
    return dates


def _item_refs(answer_text: str) -> set[tuple[str, str]]:
    """(section, item number) for every item the answer names."""
    refs = set()
    for match in _ITEM_REF_RE.finditer(answer_text):
        span = match.group(0)
        inner = _ORIENTATION_RE.findall(span)
        refs.update(("agglomeration_orientation", n) for n in inner)
        plain = re.findall(r"\d{2}\.\d{2}", _ORIENTATION_RE.sub("", span))
        # A bare "80.01" names the orientation section as a whole.
        refs.update(
            ("agglomeration_orientation", None) if n == "80.01" else ("council", n) for n in plain
        )
    return refs


def _check_citations(
    conn, answer_text: str, meeting_date: str | None = None, minimum: int = 1
) -> tuple[bool, str]:
    """Every item the answer names must exist at a meeting the answer names.

    Reads what the answer prints, not what the tools returned, so an answer
    that cites nothing fails. Readers see "June 15, 2026 (item 20.01)" and
    "2026-06-15 item 20.01" as the same citation, so both forms count.
    """
    refs = _item_refs(answer_text)
    if len(refs) < minimum:
        return False, "no citations" if not refs else (
            f"only {len(refs)} item numbers given, expected {minimum}+"
        )
    dates = {meeting_date} if meeting_date else _dates_in(answer_text)
    if not dates:
        return False, "item numbers given without a meeting date"
    unknown = []
    for section, number in sorted(refs, key=lambda ref: (ref[0], ref[1] or "")):
        row = conn.execute(
            """
            select 1 from agenda_items ai join meetings m on m.id = ai.meeting_id
            where m.meeting_date = any(%s::date[]) and ai.section = %s
              and (%s::text is null or ai.item_number = %s)
            """,
            (sorted(dates), section, number, number),
        ).fetchone()
        if row is None:
            unknown.append(number if section == "council" else f"80.01 ({number or ''})")
    if unknown:
        return False, f"items not found at {sorted(dates)}: {unknown}"
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
                citations_ok, citation_notes = _check_citations(
                    conn, answer.text, case.get("meeting_date"), case.get("min_item_refs", 1)
                )

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
                if status == "FAIL":
                    # Without the answer, a failure can't be told apart from a
                    # grader that doesn't recognize a correct phrasing.
                    print("        answer: " + " ".join(answer.text.split())[:600])

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
