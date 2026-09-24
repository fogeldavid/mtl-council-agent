# mtl-council-agent

Ask what Montreal's city council decided, in English or French, and get an answer with a citation for every claim, drawn from the city's own published records.

Montreal publishes its council proceedings only as PDFs. The records are French-only PDF bundles reaching 4,467 pages and 515 MB per meeting. This project scrapes those documents, parses them, loads them into Postgres, and runs a retrieval agent over the result.

> **Unofficial project.** Not affiliated with the Ville de Montréal, and not legal advice. Confirm against the source document cited in any answer. Data © Ville de Montréal, used under [CC-BY 4.0](https://donnees.montreal.ca/licence-d-utilisation).

## What makes the data hard

There is no API. The open data portal publishes a meeting calendar and a video index, but nothing with agenda items, decisions, or votes. Those exist only as PDFs on a legacy portal. Each meeting publishes three, and each one carries different information.

| Document | Size | What it contains |
|---|---|---|
| Agenda (*ordre du jour*) | ~28 pages | One dense paragraph per item. What is proposed, no context. |
| Minutes (*procès-verbal*) | ~100-120 pages | Who moved and seconded it, the outcome, who attended each sitting, and, for contested items, how each member voted. Almost always "adopted unanimously". |
| Bundle (*ordre du jour et documents décisionnels*) | 70-515 MB, up to 5,900 pages | A decision summary per item, with project history, prior related resolutions, cost tables, justification, and year-by-year budget. |

Answering "why did this cost go up?" needs the bundle. Answering "did it pass?" needs the minutes. Answering "what was considered?" needs the agenda. The pipeline ingests all three and joins them into one record per agenda item. Agenda and minutes join on section, item number and dossier number together. The bundle joins on dossier number alone.

### Parsing traps in the source documents

Each of these came up while testing against real documents, and each has a regression test.

- **The item marker in the minutes is a footer, not a header.** A line like `20.01 1264139001` stamps the resolution above it. Reading it as a header shifts every item's vote and mover onto the wrong decision, and nothing fails loudly to signal it.
- **A block can open with a procedural motion before the real one.** Council groups items "for study" under its own proposer and seconder. Taking the first `Il est proposé par` in a block attributes the vote to the wrong councillor, so the parser takes the last.
- **Two independent numbering series collide.** Items nested as `80.01 (20.01)` are the city council's position on files going to the agglomeration council, a different body, and they use a two-line footer format. The parser tags them with their section and inner number. It also has to treat them as boundaries, or the council items on either side merge into one block.
- **Page breaks hide items from anchored patterns.** `pdftotext` emits a form feed at every page break, so an item starting a new page reads as `"\f20.05  Service ..."` and a bare `^` anchor misses it. Across 20 meetings this silently dropped 550 agenda items, 22% of the corpus, along with 179 recorded votes.
- **Item numbers repeat within a single meeting.** The council section and the agglomeration-orientation section run separate series that both count `20.01`, `20.02`, and so on. Measured across 20 meetings, keying items on their number would overwrite 735 of 2,536 rows, so `agenda_items` is keyed on position in the agenda instead.
- **Two items can share a dossier.** Joining minutes to agenda on dossier alone gave a June 2026 filing (07.07) the resolution number and vote of a different item (30.19) from the same file. The join now requires section, item number and dossier to agree.
- **Revised agendas keep the same URL.** Every 2025-26 agenda reached a second or third version before its meeting, published at the original address. Checking for new URLs missed all of them, so the 2026-09-21 agenda stayed at 92 items after the portal's copy grew to 122. Each document now keeps the `ETag` the server returns to a header-only request, and a changed `ETag` makes the pipeline delete and reload the meeting.
- **Items without a dossier have a bare footer.** Councillors' motions end with `65.01` alone on a line. Those motions are where most roll-call votes happen, and ignoring bare footers attached them to the next item.
- **Roll calls name members by surname.** The lists read "Pinard", "V. Doyon", and "Hénault", who is a different person from "Hénault-Ratelle". The pipeline resolves each surname against the City's roster, which stores given names and surnames in separate columns.
- **The minutes contradict themselves.** On 2026-03-23, item 44.01 went to a 38-24 roll call that the chair declared adopted by majority, and the minutes then stamp it "Adopté à l'unanimité". When a roll call exists, the parser takes the outcome from the chair's declaration.

## Architecture

```
 Legacy portal (HTML)          Three PDFs per meeting
        │                               │
        ▼                               ▼
  portal_client.py  ──────────▶  pdf_extract.py  (pdftotext, no OCR needed,
  (HEAD: ETag per PDF)                  │         these are text-layer PDFs)
        │                               ▼
        │                 agenda_parser · minutes_parser · bundle_parser
        │                               │
        │                               ▼
        │                          linker.py  (join on section + item + dossier)
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

The schema nests `meetings`, then `documents`, then `agenda_items`, then `item_chunks`, alongside an `officials` roster loaded from the City's open data (`roster.py`). Structured fields (motion number, mover, seconder, outcome, section) sit next to the narrative text, so the agent has an exact answer for "did it pass?" instead of inferring one from prose. `meeting_attendance` records each sitting's roll, and `item_votes` holds the individual positions the minutes record.

### Design decisions

**Embeddings run locally, generation runs on the API.** Embedding is a fixed cost that scales with corpus size and runs once per document. Generation scales with usage. Running a local multilingual-e5 model means growing the corpus costs compute, not API spend.

**One embedding space, two languages.** The records are French-only. Translating at ingestion time would double storage and store translation errors permanently. Instead, queries and passages share one multilingual space, so an English question retrieves French records and translation happens once, at answer time, where a reader can check it.

**Vectors live on chunks, not items.** A decision summary runs about 26,000 characters against a 512-token embedding window. Search hits chunks and joins back up to the item for citation.

**Attachments are trimmed before anything is stored.** Each bundle slice keeps its cover sheet and each decision summary up to that summary's sign-off block, where the attachments begin. Untrimmed, the median item carries 38 KB and the worst carries 634 KB, most of it financial spreadsheets whose `0.00$` padding embeds to nothing useful. The trim removes 75% of the text, keeps every substantive section, and brings the projected corpus from roughly 716 MB to 231 MB, which is what lets it fit a free Postgres tier. Not every summary ends with the directors' approval. Bylaws and filings stop at the file officer's endorsement, and an item with an addendum carries two summaries with a whole contract between them. Handling both cut the items that hit the 40,000-character cap from 23 to 3.

**Votes are recorded, or they are labelled as inferred.** The minutes name individual positions in three ways: a roll call lists everyone for and against, a dissent list names who opposed a majority vote, and a member with a conflict of interest declares it and abstains. Only those are stored. For a unanimous vote the agent can say who was present at that sitting, and it labels that as inferred from attendance, never as a recorded vote. A majority vote with no names attributes nothing to anyone. Attendance is kept per sitting because a meeting's 13 h and 19 h sittings have different rolls.

**Orientation votes are parsed but not attached.** The city council's positions on agglomeration files are 49% of recorded votes. Whether they belong in a city-council tool is still open, so the pipeline tags them and leaves them off the items. Turning them on takes one flag in `linker.py` and a re-ingest.

**Hybrid retrieval.** Council text is dense with exact tokens that embeddings blur, such as `CM26 0677`, `1264139001`, and `4 118 154,43 $`. Postgres full-text search handles those. pgvector handles "what's happening with bike paths". The agent chooses between them.

**Postgres does both jobs.** At this corpus size, a dedicated vector database would add a second system to keep in sync for no measurable gain.

**One councillor, one row, matched to the roster.** The minutes spell the same person several ways: `M. Claude Pinard` and `Claude Pinard`, `Ericka Alneus` and `Ericka Alnéus`, and one transposed-letter typo. Keyed on the raw string, 25 rows represented 19 people, which silently split their voting records. The majority leader's 289 items were spread across three identities. Identity is now a normalized key with honorifics, accents and case removed, plus a similarity fallback for source typos.

The 0.95 threshold comes from measurement, and it is high on purpose. Merging two people is a silent error in the accountability search, while failing to merge leaves a visible duplicate, so the asymmetry favours caution: `Marie Plourd` (0.960) merges as an obvious truncation, but `Maria Plourde` (0.923) is a different given name and gets flagged for review instead. `official_aliases` keeps every spelling ever seen, how it resolved, and the score for fuzzy matches, so every merge can be audited. `quality-report` lists names that nearly matched but didn't.

The roster adds role, borough, district and party, and a second way to match. The roster records full given names that the minutes shorten. "Alba Stella Zuniga Ramos" appears as "Alba Zuniga Ramos", and "Dimitrios (Jim) Beis" moves items as "Jim Beis". Those score far below the similarity threshold, so a name also matches a roster member when it ends in their surname and starts with one of their given names. The roster file leaves one councillor's surname blank, and the loader recovers it from her official email address. Anyone named in the minutes but missing from the roster fails `quality-report --check`.

**Accountability search is scoped to elected officials.** `get_official_record` covers the officials roster, because how a councillor votes is public business. Names of residents, staff, and contractors appear inside documents, and only general full-text search reaches them. There is no "search by person" feature, which would turn public records into a people-search tool.

## Success metrics

`quality-report --check` computes these from the database and fails CI after any ingestion that regresses. The measured column is the 2026 corpus of 10 meetings, 1,129 agenda items and 13,570 embedded chunks.

| Metric | Definition | Threshold | Measured |
|---|---|---|---|
| Completeness | Meetings ingested, divided by meetings published on the portal | at least 95% | 100% (10/10) |
| Decision linkage | Items with a dossier that got their decision summary | at least 90% | 99.9% (946/947) |
| Text quality | Items with non-empty embedded text | reported | 100% (1,129/1,129) |
| Outcome coverage | Council items in meetings with published minutes that carry an outcome | reported | 86.7% (411/474) |
| Roster match | Officials named in the minutes who are on the City's roster | all | 65/65 |
| Reliability | Weekly ingestion job success rate | GitHub Actions history | no failures in backfill |

The single unlinked item is a filing of the mayor's report, which has no decision summary in the bundle, so 99.9% is the real ceiling. The items without an outcome are ones the council doesn't decide, such as question periods, announcements and deposited documents, plus one motion deferred to a later meeting. The database also holds 766 recorded individual positions: 740 from roll calls, 24 from a dissent list, and 2 conflict-of-interest abstentions.

The agent has its own scores, since a clean pipeline and a trustworthy answer fail independently. `eval/run_eval.py` grades a hand-labeled question set on answer correctness and citation validity, meaning every citation printed corresponds to a record that exists. The set includes refusal cases, because declining is the correct answer often enough to measure: borough questions, a future budget, a pre-corpus date, and facts that simply aren't municipal records.

The set has 22 cases, including four on recorded votes. On `claude-haiku-4-5` against the 2026 corpus, citation validity was 100% in both full runs and answer correctness was 21 and then 20 of 22, at roughly $0.03 per question. The first run after adding vote data failed one case, and the failure was real. The agent could not find a conflict-of-interest declaration without opening all 121 items of a meeting, so meeting listings now carry a note on items with recorded votes. The next run flagged two refusal cases that pass when asked alone, likely because the grader matches a fixed list of refusal phrases. Scores move between runs because the agent chooses its own tool calls and phrasing, so a single run is a sample, and a one-case drop means little until it repeats. And the eval found more bugs in itself than in the agent: early cases asserted French number formatting against English answers, and one "trap" assumed the Champlain Bridge was absent from council records when council had in fact granted a sewer servitude in the bridge corridor. Cases written before the corpus existed encode assumptions about data nobody had looked at yet.

## Setup

Requires Python 3.11+, `poppler-utils` (for `pdftotext`), and a Postgres database with `pgvector`. Supabase and Neon both work on their free tiers.

```bash
pip install -e ".[dev]"

export DATABASE_URL="postgresql://..."
export ANTHROPIC_API_KEY="sk-ant-..."

mtl-council-agent init-db
mtl-council-agent load-roster                    # 65 council members, from open data
mtl-council-agent -v ingest --since 2026-01-01   # backfill, several GB of PDFs
mtl-council-agent quality-report
```

Then ask it questions:

```bash
mtl-council-agent ask "Why did the Guy-Lafleur bridge contract go over budget?"
mtl-council-agent ask "Combien la Ville a-t-elle dépensé pour des pistes cyclables?"
mtl-council-agent ask "What has Julien Hénault-Ratelle moved at council?"
mtl-council-agent ask "Did Marie Plourde vote for or against the 2026 budget?"
```

`MTL_AGENT_MODEL` selects the generation model. It defaults to `claude-haiku-4-5` at roughly $0.03 a question, since the eval sweeps every question on each prompt change and a five-fold cost difference decides how often that actually gets run. Set `claude-opus-5` for harder multi-step questions. Token use and estimated cost print to stderr after each answer.

## Development

```bash
pytest -q                       # 79 tests, no network or database needed
ruff check src tests
python eval/run_eval.py -v      # requires an ingested database and API key
```

Most tests run against real fixtures: a saved portal page, one meeting's agenda, minutes and bundle, and excerpts of other 2026 minutes chosen for their edge cases. A change in the city's document format fails a test instead of corrupting data unnoticed.

## Scope

City council (*conseil municipal*) only. Not the 19 borough councils, and not the agglomeration council. Both publish separately and follow different document conventions. The agent says so rather than guessing when asked about them.

The ingested corpus covers 2026, ten meetings, in 88 MB. Storage runs at about 6.5 KB per chunk, down from 17.6 KB before embeddings moved to half precision, so extending the backfill through 2025 would land near 260 MB and still fit a free Postgres tier. Meetings before November 2025 belong to the previous council term, whose roster is a separate file with different columns.
