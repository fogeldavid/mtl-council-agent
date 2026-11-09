"""Prepare saved title/context translations using local CPU inference only.

Install .[translation], prepare the CTranslate2 Marian model once, then run:
python scripts/translate_records.py --model-dir scratch/translation-fr-en
The team database is read in a read-only transaction; no schema/data is changed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mtl_council_agent import minutes_text  # noqa: E402
from mtl_council_agent.app.translations import (  # noqa: E402
    MODEL_NAME,
    TRANSLATIONS_PATH,
    context_excerpt,
    numbers_preserved,
    protect_numbers,
    restore_references,
    source_key,
    unprotect_numbers,
)


def save(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def split_source(text, tokenizer, maximum=440):
    """Split long fields on word boundaries instead of silently truncating them."""
    if len(tokenizer.encode(text)) <= maximum:
        return [text]
    words = text.split()
    middle = len(words) // 2
    if not middle:
        raise ValueError("A source token exceeds the translation model context")
    return (split_source(" ".join(words[:middle]), tokenizer, maximum)
            + split_source(" ".join(words[middle:]), tokenizer, maximum))


def main():
    import psycopg
    from dotenv import dotenv_values

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", default="scratch/translation-fr-en")
    parser.add_argument("--tokenizer-dir", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--titles-only", action="store_true")
    parser.add_argument("--check", action="store_true", help="Report coverage without inference")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--protect-numbers", action="store_true")
    args = parser.parse_args()
    # The environment first, so a run can point at a copy of the database.
    url = os.environ.get("WEB_DATABASE_URL") or dotenv_values(".env").get("WEB_DATABASE_URL")
    if not url:
        raise SystemExit("WEB_DATABASE_URL is not configured")
    try:
        with psycopg.connect(url, connect_timeout=15,
                             options="-c default_transaction_read_only=on") as conn:
            rows = conn.execute("""
                select ai.title, ai.decision_summary, m.meeting_date, ai.vote_outcome,
                       ai.minutes_text
                from agenda_items ai
                join meetings m on m.id = ai.meeting_id
                order by m.meeting_date desc, ai.position
            """).fetchall()
    except psycopg.Error:
        raise SystemExit(
            "Could not read council records; check the local database configuration."
        ) from None
    titles = list(dict.fromkeys(row[0] for row in rows if row[0]))
    contexts = list(dict.fromkeys(context_excerpt(row[1]) for row in rows if row[1]))
    # The minutes, a paragraph at a time, as the item page shows them: the
    # adopted wording for every item, the full entry where there's no summary.
    minutes = list(dict.fromkeys(
        paragraph
        for row in rows if row[4]
        for paragraph in minutes_text.resolved(row[4])
        + ([] if row[1] else minutes_text.body(row[4]))
    ))
    texts = list(dict.fromkeys(
        titles + ([] if args.titles_only else [t for t in contexts if t] + minutes)
    ))
    path = TRANSLATIONS_PATH
    data = json.loads(path.read_text()) if path.exists() else {
        "model": MODEL_NAME, "source_language": "fr", "target_language": "en", "entries": {},
    }
    pending = [text for text in texts if source_key(text) not in data["entries"]]
    if args.limit:
        pending = pending[:args.limit]
    def report():
        entries = data["entries"]
        title_count = sum(source_key(title) in entries for title in titles)
        outcomes = {"adopted", "adopted_unanimous", "adopted_majority", "rejected"}
        decisions = [r for r in rows if r[3] in outcomes and r[0]]
        covered = sum(source_key(r[0]) in entries for r in decisions)
        print(f"Title coverage: {title_count}/{len(titles)} unique titles; "
              f"decision records: {covered}/{len(decisions)}; "
              f"latest meeting: {max(r[2] for r in rows) if rows else 'none'}", flush=True)
        data["coverage"] = {
            "checked_at": datetime.now(UTC).isoformat(), "records": len(rows),
            "latest_meeting": str(max(r[2] for r in rows)) if rows else None,
            "unique_titles": len(titles), "translated_titles": title_count,
            "decision_records": len(decisions), "translated_decision_titles": covered,
        }
    report()
    if args.check:
        return
    if not pending:
        save(path, data)
        print("No new text to translate.", flush=True)
        return
    print(f"{len(rows)} records; {len(pending)} unique text fields to translate.", flush=True)
    import ctranslate2
    from transformers import MarianTokenizer

    tokenizer = MarianTokenizer.from_pretrained(args.tokenizer_dir, local_files_only=True)
    translator = ctranslate2.Translator(
        args.model_dir, device="cpu", compute_type="int8", intra_threads=4,
    )
    rejected = []
    for start in range(0, len(pending), args.batch_size):
        batch = pending[start:start + args.batch_size]
        protected = [protect_numbers(text) if args.protect_numbers else (text, {})
                     for text in batch]
        parts = [split_source(text, tokenizer) for text, _ in protected]
        sources = [tokenizer.convert_ids_to_tokens(tokenizer.encode(part))
                   for pieces in parts for part in pieces]
        results = translator.translate_batch(
            sources, beam_size=4, max_decoding_length=512, max_batch_size=args.batch_size,
            repetition_penalty=1.1,
        ) if sources else []
        decoded = [tokenizer.decode(tokenizer.convert_tokens_to_ids(result.hypotheses[0]),
                                    skip_special_tokens=True).strip() for result in results]
        cursor = 0
        for source, pieces, (_, mapping) in zip(batch, parts, protected, strict=True):
            translated = restore_references(
                source, " ".join(decoded[cursor:cursor + len(pieces)]),
            )
            cursor += len(pieces)
            restored = unprotect_numbers(translated, mapping)
            translated = restored or ""
            if translated and numbers_preserved(source, translated):
                data["entries"][source_key(source)] = translated
            else:
                rejected.append({"source": source, "translation": translated,
                                 "reason": "Numeric fidelity requires review"})
        save(path, data)
        print(f"Processed {min(start + len(batch), len(pending))}/{len(pending)}; "
              f"saved {len(data['entries'])}; needs review {len(rejected)}", flush=True)
    Path("scratch").mkdir(exist_ok=True)
    Path("scratch/translation-review.json").write_text(
        json.dumps(rejected, ensure_ascii=False, indent=2) + "\n",
    )
    report()
    save(path, data)
    print("Finished. Unapproved fields remain French; originals are always available.", flush=True)


if __name__ == "__main__":
    main()
