# mtl-council-agent

Ask what Montreal's city council decided, in English or French, and get an answer with a citation for every claim, drawn from the city's own published records.

Montreal publishes its council proceedings, but not in a form anyone can use. The records are French-only PDF bundles reaching 4,467 pages and 515 MB per meeting. This project scrapes those documents, parses them, loads them into Postgres, and runs a retrieval agent over the result.

> **Unofficial project.** Not affiliated with the Ville de Montréal, and not legal advice. Confirm against the source document cited in any answer. Data © Ville de Montréal, used under [CC-BY 4.0](https://donnees.montreal.ca/licence-d-utilisation).

## What makes the data hard

There is no API. The open data portal publishes a meeting calendar and a video index, but nothing with agenda items, decisions, or votes. Those exist only as PDFs on a legacy portal. Each meeting publishes three, and each one carries different information.

| Document | Size | What it contains |
|---|---|---|
| Agenda (*ordre du jour*) | ~28 pages | One dense paragraph per item. What is proposed, no context. |
| Minutes (*procès-verbal*) | ~100-120 pages | Who moved and seconded it, and the outcome. Almost always "adopted unanimously", with no debate recorded. |
| Bundle (*ordre du jour et documents décisionnels*) | 70-515 MB, up to 5,900 pages | A decision summary per item, carrying project history, prior related resolutions, cost tables, justification, and year-by-year budget. |

Answering "why did this cost go up?" needs the bundle. Answering "did it pass?" needs the minutes. Answering "what was considered?" needs the agenda. The pipeline ingests all three and joins them into one record per agenda item, keyed on the dossier number, the only identifier stable across all three documents.

### Parsing traps in the source documents

Testing against real documents surfaced each of these. All are covered by a regression test.

- **The item marker in the minutes is a footer, not a header.** A line like `20.01 1264139001` stamps the resolution above it. Reading it as a header shifts every item's vote and mover onto the wrong decision, and nothing fails loudly to signal it.
- **A block can open with a procedural motion before the real one.** Council groups items "for study" under its own proposer and seconder. Taking the first `Il est proposé par` in a block attributes the vote to the wrong councillor, so the parser takes the last.
- **Two independent numbering series collide.** Items nested as `80.01 (20.01)` are the city council's non-binding *orientation* vote on agglomeration council business, a different body that is out of scope, and they use a two-line footer format. The parser still has to recognize them as boundaries, or the real council items on either side merge into one block.
- **Item numbers are not unique.** They reset per section. The dossier number is the real key.

## Architecture

```
 Legacy portal (HTML)          Three PDFs per meeting
        │                               │
        ▼                               ▼
  portal_client.py  ──────────▶  pdf_extract.py  (pdftotext, no OCR needed,
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

The schema nests `meetings`, then `documents`, then `agenda_items`, then `item_chunks`, alongside an `officials` roster. Structured fields (motion number, mover, seconder, vote outcome) sit next to the narrative text, so the agent has an exact answer for "did it pass?" instead of inferring one from prose.

### Design decisions

**Embeddings run locally, generation runs on the API.** Embedding is a fixed cost that scales with corpus size and runs once per document. Generation scales with usage. Running a local multilingual-e5 model means growing the corpus costs compute, not API spend.

**One embedding space, two languages.** The records are French-only. Translating at ingestion time would double storage and store translation errors permanently. Instead, queries and passages share one multilingual space, so an English question retrieves French records and translation happens once, at answer time, where a reader can check it.

**Vectors live on chunks, not items.** A decision summary runs about 26,000 characters against a 512-token embedding window. Search hits chunks and joins back up to the item for citation.

**Hybrid retrieval.** Council text is dense with exact tokens that embeddings blur, such as `CM26 0677`, `1264139001`, and `4 118 154,43 $`. Postgres full-text search handles those. pgvector handles "what's happening with bike paths". The agent chooses between them.

**Postgres does both jobs.** At this corpus size, a dedicated vector database would add a second system to keep in sync for no measurable gain.

**Accountability search is scoped to elected officials.** `get_official_record` covers the officials roster, because how a councillor votes is public business. Names of residents, staff, and contractors appear inside documents, and only general full-text search reaches them. There is no "search by person" feature, which would turn public records into a people-search tool.

## Success metrics

`quality-report --check` computes these from the database and fails CI after any ingestion that regresses.

| Metric | Definition | Threshold |
|---|---|---|
| Completeness | Meetings ingested, divided by meetings published on the portal | at least 95% |
| Decision linkage | Items with a dossier that got their decision summary | at least 90% |
| Text quality | Items with non-empty embedded text | reported |
| Reliability | Weekly ingestion job success rate | GitHub Actions history |

The agent has its own scores, since a clean pipeline and a trustworthy answer fail independently. `eval/run_eval.py` grades a hand-labeled question set on answer correctness and citation validity, meaning every citation printed corresponds to a record that exists. The set includes refusal cases such as borough questions, future budgets, and a Champlain Bridge trap, because declining is the correct answer often enough to measure.

## Setup

Requires Python 3.11+, `poppler-utils` (for `pdftotext`), and a Postgres database with `pgvector`. Supabase and Neon both work on their free tiers.

```bash
pip install -e ".[dev]"

export DATABASE_URL="postgresql://..."
export ANTHROPIC_API_KEY="sk-ant-..."

mtl-council-agent init-db
mtl-council-agent -v ingest --since 2025-01-01   # backfill, several GB of PDFs
mtl-council-agent quality-report
```

Then ask it questions:

```bash
mtl-council-agent ask "Why did the Guy-Lafleur bridge contract go over budget?"
mtl-council-agent ask "Combien la Ville a-t-elle dépensé pour des pistes cyclables?"
mtl-council-agent ask "What has Julien Hénault-Ratelle moved at council?"
```

`MTL_AGENT_MODEL` selects the generation model. It defaults to `claude-opus-5`, and `claude-haiku-4-5` cuts the cost. Token use and estimated cost per question print to stderr.

## Development

```bash
pytest -q                       # 21 tests, no network or database needed
ruff check src tests
python eval/run_eval.py -v      # requires an ingested database and API key
```

Tests run against real fixtures, a live portal page and one real agenda, minutes, and bundle set, rather than synthetic samples. A change in the city's document format fails a test instead of corrupting data unnoticed.

## Scope

City council (*conseil municipal*) only. Not the 19 borough councils, and not the agglomeration council. Both publish separately and follow different document conventions. The agent says so rather than guessing when asked about them.
