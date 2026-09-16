# mtl-council-agent

An AI agent that answers questions about what Montreal's city council actually decided — in English or French — grounded in the city's own published records, with a citation for every claim.

Montreal publishes its council proceedings, but not in a form anyone can practically use: the substance lives in French-only PDF bundles that run to **4,467 pages and 515 MB per meeting**. This project builds the missing pipeline — scraping, parsing, and structuring those documents into Postgres — and puts a retrieval agent on top of it.

> **Unofficial project.** Not affiliated with the Ville de Montréal, and not legal advice. Always confirm against the source document cited in any answer. Data © Ville de Montréal, used under [CC-BY 4.0](https://donnees.montreal.ca/licence-d-utilisation).

## What makes the data hard

There is **no API**. The open data portal publishes a meeting calendar and a video index, but nothing containing agenda items, decisions, or votes. Those exist only as PDFs on a legacy portal, and each meeting publishes three of them that each hold a different piece of the picture:

| Document | Size | What it actually contains |
|---|---|---|
| **Agenda** (*ordre du jour*) | ~28 pages | One dense paragraph per item. What's proposed, no context. |
| **Minutes** (*procès-verbal*) | ~100–120 pages | Who moved and seconded it, and the outcome — almost always "adopted unanimously", with no debate recorded. |
| **Bundle** (*ordre du jour et documents décisionnels*) | 70–515 MB, up to 5,900 pages | The real substance: a per-item decision summary with project history, prior related resolutions, cost tables, justification, and year-by-year budget. |

Answering "why did this cost go up?" needs the bundle. Answering "did it pass?" needs the minutes. Answering "what was considered?" needs the agenda. So the pipeline ingests **all three** and joins them into one record per agenda item, keyed on the dossier number — the only identifier stable across all three documents.

### Parsing gotchas found the hard way

These were discovered by testing against real documents, and each is covered by a regression test:

- **The item marker in the minutes is a footer, not a header.** A line like `20.01 1264139001` stamps the resolution *above* it. Reading it as a header shifts every item's vote and mover onto the wrong decision — the kind of bug that produces confident, well-formatted, completely wrong answers.
- **Each block can contain a procedural motion before the real one.** Council groups items "for study" with its own proposer and seconder, so naively taking the first `Il est proposé par` in a block attributes the vote to the wrong councillor. The parser takes the last.
- **Two independent numbering series collide.** Items nested as `80.01 (20.01)` are the city council's non-binding *orientation* vote on agglomeration council business — a different body, out of scope — and use a two-line footer format. They still have to be recognized as boundaries, or the real council items on either side of them merge into one block.
- **Item numbers are not unique.** They reset per section. The dossier number is the real key.

## Architecture

```
 Legacy portal (HTML)          Three PDFs per meeting
        │                               │
        ▼                               ▼
  portal_client.py  ──────────▶  pdf_extract.py  (pdftotext; no OCR needed —
        │                               │         these are text-layer PDFs)
        │                               ▼
        │                 agenda_parser · minutes_parser · bundle_parser
        │                               │
        │                               ▼
        │                          linker.py  (join on dossier number)
        │                               │
        │                   chunker.py ─┴─ embed.py  (multilingual-e5, local)
        │                               │
        └──────────────────────▶  Postgres + pgvector
                                        │
                        ┌───────────────┴───────────────┐
                    tsvector FTS                  HNSW vector index
                        └───────────────┬───────────────┘
                                        ▼
                             agent/loop.py  (5 tools, hand-written loop)
```

**Schema:** `meetings` → `documents` → `agenda_items` → `item_chunks`, plus an `officials` roster. Structured fields (motion number, mover, seconder, vote outcome) sit alongside the narrative text, so the agent has an exact answer for "did it pass?" instead of inferring it from prose.

### Design decisions worth explaining

**Embeddings run locally, generation runs on the API.** Embedding is a fixed cost that scales with corpus size and runs once per document; generation scales with usage. Putting embeddings on a local multilingual-e5 model means growing the corpus costs compute, not API spend.

**One embedding space, two languages.** The records are French-only. Rather than translating at ingestion time — which would double storage and bake translation errors into the data permanently — queries and passages share a multilingual space, so an English question retrieves French records and translation happens once, at answer time, where it's visible and checkable.

**Vectors live on chunks, not items.** A decision summary runs ~26,000 characters against a 512-token embedding window. Search hits chunks and joins back up to the item for citation.

**Hybrid retrieval.** Council text is dense with exact tokens — `CM26 0677`, `1264139001`, `4 118 154,43 $` — that embeddings blur. Postgres full-text search handles those; pgvector handles "what's happening with bike paths". The agent picks.

**Postgres does both jobs.** At this corpus size a dedicated vector database would add a second system to keep in sync for no measurable gain.

**Accountability search is scoped to elected officials.** `get_official_record` covers the officials roster, because how a councillor votes is public business. Names of residents, staff, and contractors appear inside documents and are reachable only through general full-text search — there's deliberately no "search by person" feature that would turn public records into a people-search tool.

## Success metrics

The pipeline's metrics are computed from the database, not eyeballed. `quality-report --check` runs in CI after every ingestion and fails the job on regression:

| Metric | Definition | Threshold |
|---|---|---|
| Completeness | Meetings held ÷ meetings published on the portal | ≥ 95% |
| Decision linkage | Items with a dossier that got their decision summary | ≥ 90% |
| Text quality | Items with non-empty embedded text | reported |
| Reliability | Weekly ingestion job success rate | GitHub Actions history |

The agent has its own scores, since a clean pipeline and a trustworthy answer fail independently — `eval/run_eval.py` grades a hand-labeled question set on **answer correctness** and **citation validity** (does every citation printed correspond to a record that actually exists). The set includes deliberate refusal cases — borough questions, future budgets, a Champlain Bridge trap — because declining is the correct answer often enough that it has to be measured.

## Setup

Requires Python 3.11+, `poppler-utils` (for `pdftotext`), and a Postgres database with `pgvector` (Supabase and Neon both work on their free tiers).

```bash
pip install -e ".[dev]"

export DATABASE_URL="postgresql://..."
export ANTHROPIC_API_KEY="sk-ant-..."

mtl-council-agent init-db
mtl-council-agent -v ingest --since 2025-01-01   # backfill; several GB of PDFs
mtl-council-agent quality-report
```

Then ask it things:

```bash
mtl-council-agent ask "Why did the Guy-Lafleur bridge contract go over budget?"
mtl-council-agent ask "Combien la Ville a-t-elle dépensé pour des pistes cyclables?"
mtl-council-agent ask "What has Julien Hénault-Ratelle moved at council?"
```

`MTL_AGENT_MODEL` selects the generation model (defaults to `claude-opus-5`; set `claude-haiku-4-5` to cut cost). Per-question token use and estimated cost print to stderr.

## Development

```bash
pytest -q                       # 21 tests, no network or database needed
ruff check src tests
python eval/run_eval.py -v      # requires an ingested database + API key
```

Tests run against real fixtures — an actual portal page and a real agenda/minutes/bundle trio — rather than synthetic samples, so a change in the city's document format fails a test instead of silently corrupting data.

## Scope

City council (*conseil municipal*) only. Not the 19 borough councils, and not the agglomeration council — both publish separately and use different document conventions. The agent is told to say so rather than guess when asked about them.
