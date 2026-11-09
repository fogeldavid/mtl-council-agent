# The Montréal Record (mtl-council-agent)

A public site for what Montreal's city council decided and how each councillor voted, in English and French. Every answer and page links back to the city's own records. Montreal publishes its council proceedings only as French PDFs, up to 4,467 pages and 515 MB per meeting. This project scrapes them, parses them into one record per agenda item, loads them into Postgres, and puts a search site and a retrieval agent on top.

Live at **[mtl-council-agent.streamlit.app](https://mtl-council-agent.streamlit.app)**.

<img src="images/app-landing.png" width="800" alt="The Montréal Record's front page: a headline over a photo of City Hall, and four sections to find your representative, search decisions, ask a question, and read the latest meeting">

> Unofficial project, not affiliated with the Ville de Montréal.

---

## The web app

A Streamlit site over the same database, with the interface in English and French. It has three tabs, plus an About page in the header.

| Tab | What it's for |
|---|---|
| Ask the council | Ask a question in English or French and get an answer that cites the council's records. |
| District explorer | Find who represents you, and see how they voted. |
| Council updates | Browse and search every decision and meeting. |

<img src="images/app-chat-answer.png" width="800" alt="The Ask page answering what item 15.02 of the September 21, 2026 meeting was: a declaration for the National Day of Truth and Reconciliation, with its five commitments, the debate, a citation, and links to the minutes and agenda">

Each item page shows:
- the outcome and resolution number;
- a short English context from the city's decision summary;
- **what council adopted**, taken from the minutes;
- how council voted.

Declarations and councillors' motions have no decision summary, so their page shows the full minutes text instead, including the debate summary. Sources sit in their own panel, and the minutes link opens the PDF at the item's page. A switch shows the French original in place.

<img src="images/app-item-motion.png" width="800" alt="Item page for the opposition's September 2026 democracy motion: rejected by roll call, 24 for and 36 against with every name, and the motion's fourteen clauses under What council voted down">

<img src="images/app-decisions.png" width="800" alt="Decisions page searching &quot;snow removal&quot;: six matching decisions, led by the ProQuip snow removal contract for Plateau-Mont-Royal">

<img src="images/app-districts.png" width="800" alt="District explorer with Mile-End selected on the map, showing city councillor Marie Plourde and borough mayor Cathy Wong">

**What visitors' questions cost.** Chat uses a server-side `WEB_ANTHROPIC_API_KEY`. Visitors get five shared questions a day, counted in memory by IP address. If the key is missing or the allowance or credit runs out, chat shows a message and stops. Visitors are never asked for a key. The in-memory counts reset on restart, so they are not a hard spending cap. Browsing, search and translations need no Anthropic key.

**What the app can touch.** It connects as `web_reader`, a Postgres role that can only read, so a bug in the app can't change the data.

**Hosting.** Streamlit Community Cloud's free tier, deployed from `main`. The related-by-meaning results use the same multilingual-e5 model the pipeline uses. The first search after the site wakes takes about 15 seconds while it loads, and later ones take a few. Setting `SEMANTIC_SEARCH=off` drops it, which leaves exact and English-title matches and the agent's other tools.

## What makes the data hard

There is no API. The open data portal publishes a meeting calendar and a video index, but nothing with agenda items, decisions, or votes. Those exist only as PDFs on a legacy portal, three per meeting, and each carries different information.

| Document | Size | What it contains |
|---|---|---|
| Agenda (*ordre du jour*) | ~28 pages | One dense paragraph per item. What is proposed, no context. |
| Minutes (*procès-verbal*) | ~100-120 pages | The wording council adopted, who moved and seconded it, the outcome, who attended each sitting, and, for contested items, how each member voted. |
| Bundle (*documents décisionnels*) | 70-515 MB, up to 5,900 pages | A decision summary per item: project history, prior resolutions, cost tables, justification, and budget. |

Answering "why did this cost go up?" needs the bundle. Answering "did it pass, and what exactly was adopted?" needs the minutes. The pipeline ingests all three and joins them into one record per agenda item. Agenda and minutes join on section, item number and dossier number together. The bundle joins on dossier number alone.

### Parsing traps in the source documents

Each of these came up while testing against real documents, and each has a regression test.

- **The item marker in the minutes is a footer, not a header.** A line like `20.01 1264139001` stamps the resolution above it. Reading it as a header shifts every item's vote and mover onto the wrong decision, and nothing fails loudly.
- **An entry holds several proposals, and only one is the item's.** Council first groups items "for study" under their own proposer, and a motion is often followed by procedural ones: a roll-call request, an amendment, extending the sitting. Taking the last "Il est proposé par" credited the opposition leader, who requests most roll calls, with moving 11 items she didn't. The parser now takes the proposal just before the last "Et résolu :", or the first one in a motion, which has no "Et résolu".
- **"Adopted" can describe a different vote.** On 2026-05-11, council sent an opposition motion to a committee, and the minutes record that referral as adopted unanimously. The parser recognizes a motion being referred and marks it `referred`, so the site never lists the motion's demands as adopted.
- **Headings change between meetings.** The 2026-09-21 minutes print the attendance heading as "PRÉSENCES" where earlier ones print "PRÉSENCES :". That meeting silently lost its attendance until the parser accepted both. The weekly check now fails when any meeting with minutes yields no attendance.
- **Two independent numbering series collide.** Items nested as `80.01 (20.01)` are the city council's position on files going to the agglomeration council. They use a two-line footer, and they share item numbers with the council's own items. Keying items on their number would overwrite 735 of 2,536 rows across 20 meetings, so items are keyed on their position in the agenda.
- **Page breaks hide items from anchored patterns.** `pdftotext` emits a form feed at every page break, so an item starting a new page reads as `"\f20.05  Service ..."`. A bare `^` anchor missed 550 agenda items, 22% of the corpus. The same form feeds are what give each item its page number.
- **Two items can share a dossier.** Joining minutes to agenda on dossier alone gave a June 2026 filing the vote of a different item from the same file.
- **Revised agendas keep the same URL.** Every 2025-26 agenda reached a second or third version at its original address. Each document now keeps the `ETag` the server returns to a header-only request, and a changed `ETag` reloads the meeting.
- **Roll calls name members by surname.** "Pinard", "V. Doyon", and "Hénault", who is a different person from "Hénault-Ratelle". The pipeline resolves each surname against the City's roster.
- **The minutes contradict themselves.** On 2026-03-23, item 44.01 went to a 38-24 roll call that the chair declared adopted by majority, and the minutes then stamp it "Adopté à l'unanimité". When a roll call exists, the outcome comes from the chair's declaration.

## Architecture

```
 Legacy portal (HTML)          Three PDFs per meeting
        │                               │
        ▼                               ▼
  portal_client.py  ──────────▶  pdf_extract.py  (pdftotext, text layer, no OCR)
  (HEAD: ETag per PDF)                  │
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
                                        │
                                        ▼
                        streamlit_app.py  (web app, read-only role)
```

The schema nests `meetings`, `documents`, `agenda_items` and `item_chunks`, beside an `officials` roster loaded from the City's open data. Structured fields (motion number, mover, seconder, outcome, section, sitting) sit next to the text, so the agent has an exact answer for "did it pass?" instead of inferring one from prose. Each item also keeps its own entry from the minutes and the PDF page it starts on. `meeting_attendance` records each sitting's roll, and `item_votes` holds the individual positions the minutes record. `documents` keeps the extracted text of every agenda and set of minutes, so a parser fix can re-read old meetings without the city's PDFs.

### Design decisions

**Embeddings run locally, generation runs on the API.** Embedding scales with corpus size and runs once per document, while generation scales with usage. A local multilingual-e5 model means growing the corpus costs compute, not API spend.

**One embedding space, two languages.** The records are French-only. An English question and a French passage share one multilingual space, so search works in both languages without translating anything at ingestion time.

**Vectors live on chunks, not items.** A decision summary runs about 26,000 characters against a 512-token embedding window. Search hits chunks and joins back up to the item for citation.

**Attachments are trimmed before anything is stored.** Each decision summary is kept up to its sign-off block, where financial spreadsheet attachments begin. The trim removes 75% of the text, keeps every substantive section, and is what lets the corpus fit a free Postgres tier.

**The minutes are the record of what was adopted.** The decision summary is written before the meeting, and the minutes record what council actually adopted, amendments included. Every item keeps its minutes entry. Declarations and councillors' motions have no summary, so the site searches and shows their minutes entry instead. The agent is told that when the two disagree, the minutes wording wins.

**Votes are recorded, or they are labelled as inferred.** The minutes name individual positions three ways: a roll call, a dissent list, and a declared conflict of interest. The pipeline stores only those. For a unanimous vote, the site lists who was present at that sitting and labels it as inferred from attendance, never as a recorded vote. A majority vote with no names attributes nothing to anyone.

**Orientation votes are attached and labelled.** The city council's positions on files going to the agglomeration council are 49% of recorded votes in 2026. They are real votes by city councillors, so the pipeline keeps them. Every result carries its section, and the agent reports these votes as positions, not final decisions.

**Hybrid retrieval.** Council text is dense with exact tokens that embeddings blur, such as `CM26 0677` and `4 118 154,43 $`. Postgres full-text search handles those, pgvector handles topics, and the agent chooses between them. At this size, a separate vector database would only add a second system to keep in sync.

**One councillor, one row.** The minutes spell the same person several ways (`M. Claude Pinard`, `Ericka Alnéus`, a transposed-letter typo). Keyed on the raw string, 25 rows represented 19 people and split their voting records. Identity is now a normalized name matched to the City's roster, with a 0.95 similarity fallback. The threshold is high on purpose. A wrong merge is a silent error in someone's record, while a missed one leaves a visible duplicate. `official_aliases` keeps every spelling and how it resolved.

**Accountability search covers elected officials only.** How a councillor votes is public business. Residents, staff and contractors named inside documents are reachable only through general text search, so the site can't be used as a people-search tool.

## Results

### Data quality

`quality-report --check` computes these from the database and fails the weekly job when one regresses. Measured on the 2026 corpus: 12 meetings, 10 with published minutes, 1,339 agenda items and 16,634 embedded chunks.

| Metric | Definition | Measured |
|---|---|---|
| Decision linkage | Items with a dossier that got their decision summary | 99.9% (1,123/1,124) |
| Embedded text | Items with searchable text | 100% (1,339/1,339) |
| Outcome coverage | Council items at meetings with minutes that carry an outcome | 86.1% (545/633) |
| Minutes text | Items with their own entry from the minutes and a page number | 1,028 |
| Attendance | Meetings with minutes whose roll was read | 10/10 |
| Roster match | Officials named in the minutes who are on the City's roster | 65/65 |

The one unlinked item is a filing with no decision summary in the bundle. Items without an outcome are ones council doesn't decide, such as question periods and announcements, plus withdrawn items. The database holds 1,060 recorded individual positions: 983 from roll calls, 72 from dissent lists, and 5 conflict-of-interest abstentions. Checked against the PDF text, 1,027 of the 1,028 page numbers point to the page holding the item's resolution number.

### Agent eval

`eval/run_eval.py` grades a hand-labelled set of 85 questions on two checks that fail independently. The answer has to contain what it should, and every citation it prints has to match a real item at a meeting it names. The set includes refusal cases (borough questions, future budgets, private information, prompt injection), because declining is the right answer often enough to measure, and reworded variants of the same questions.

| Run | Questions | Both checks pass |
|---|---|---|
| Latest, `claude-haiku-4-5` | 85 | 82 (96.5%) |
| Previous | 83 | 81 (97.6%) |

The three misses in the latest run:
- One is a grader gap, now fixed: the agent declined a question about live stock prices with "I can't answer that", a phrase the grader didn't recognize as a refusal.
- Two are real over-caution. The agent said the records don't mention a land purchase that they do contain. Asked to summarize an agenda whose minutes aren't out yet, it listed nothing instead of listing the items as proposals.

A full run costs about $2-3, roughly $0.03 a question. Scores move between runs, because the agent chooses its own tool calls and wording, so one run is a sample.

The eval has found bugs in itself as often as in the agent. The first grader checked the records the tools returned instead of the citations in the answer, so an answer citing nothing still passed. Other cases expected French number formatting in English answers, or assumed a topic was absent from council records when it wasn't.

## Getting started

Requires Python 3.11+, `poppler-utils` (for `pdftotext`), and Postgres with `pgvector`. Neon and Supabase both work on their free tiers.

```bash
pip install -e ".[dev]"

export DATABASE_URL="postgresql://..."
export ANTHROPIC_API_KEY="sk-ant-..."

mtl-council-agent init-db
mtl-council-agent load-roster                    # 65 council members, from open data
mtl-council-agent -v ingest --since 2026-01-01   # backfill, several GB of PDFs
mtl-council-agent quality-report
```

Ask questions from the command line:

```bash
mtl-council-agent ask "Why did the Guy-Lafleur bridge contract go over budget?"
mtl-council-agent ask "Combien la Ville a-t-elle dépensé pour des pistes cyclables?"
mtl-council-agent ask "Did Marie Plourde vote for or against the 2026 budget?"
```

Or run the web app:

```bash
pip install -r requirements.txt
export WEB_DATABASE_URL="postgresql://web_reader:..."   # a read-only login
export WEB_ANTHROPIC_API_KEY="sk-ant-..."               # shared chat; without it, chat is off
streamlit run streamlit_app.py
```

`MTL_AGENT_MODEL` selects the generation model. It defaults to `claude-haiku-4-5`, cheap enough to rerun the eval on every prompt change.

### Tests

```bash
pytest -q                                   # 216 tests, no network or database
ruff check src tests eval scripts streamlit_app.py
python eval/run_eval.py -v                  # needs an ingested database and an API key
python eval/run_eval.py -v --start 34       # resume a run that stopped after 34 questions
```

64 more tests cover the web app's queries and pages against a small seeded database. They run when `TEST_DATABASE_URL` points at a Postgres with pgvector, which CI starts as a service:

```bash
docker run -d --name mtl-test-pg -e POSTGRES_PASSWORD=test -p 55432:5432 pgvector/pgvector:pg16
TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/postgres pytest -q   # 280 tests
```

Most parser tests run on real fixtures: a saved portal page, one meeting's agenda, minutes and bundle, and excerpts of other 2026 minutes chosen for their edge cases. A change in the city's document format fails a test instead of corrupting data quietly. The chat tests stub the model, so no test calls the Anthropic API.

## Automation

Two GitHub Actions workflows keep the site current without manual steps.

- **Weekly ingestion** (Mondays, 06:00 UTC):
  - reloads the council roster, and marks anyone who has left as a former member;
  - ingests any meeting whose documents are new or revised;
  - runs `quality-report --check`, which fails the run (and GitHub emails the owner) if a metric regresses, an official is missing from the roster, or a meeting's minutes yield no attendance.
- **Prepare English translations** runs after each successful ingestion. They translate new titles, context excerpts, department names and minutes wording with [Helsinki-NLP/opus-mt-fr-en](https://huggingface.co/Helsinki-NLP/opus-mt-fr-en), a free model run on the CPU. When anything changes, the workflow commits `english-translations.json` to `main` as `github-actions[bot]`, and the site redeploys with it.

A translation whose amounts or resolution numbers don't survive stays in French. A half-converted number such as "$8,999 704.92" is repaired to "$8,999,704.92", while cadastre lot numbers keep their spaces ("lot 1 336 164"). The site labels all of it as machine translation, with the French original a click away. A large first batch runs faster locally:

```bash
.venv/bin/python scripts/refresh_translations.py
```

One-off scripts in `scripts/` apply a parser fix to meetings already in the database without re-downloading them. `backfill_minutes_text.py` added the minutes text and page numbers, and `reparse_attendance.py` re-reads attendance. Each supports `--dry-run`.

## Scope

City council (*conseil municipal*) only, not the 19 borough councils or the agglomeration council, which publish separately. The agent says so when asked about them.

The corpus covers 2026: 12 meetings, in a 128 MB database. Extending the backfill through 2025 would still fit a free Postgres tier. Meetings before November 2025 belong to the previous council term, whose roster file has different columns.

The City's roster is a snapshot taken at the start of each term. A councillor elected in a by-election shows up as unknown and fails the weekly check, but someone who resigns mid-term stays listed until the City updates the file.

## Repository structure

```
src/mtl_council_agent/
  scraper/          portal client: meeting list, PDF links, ETag checks
  ingestion/        PDF text, agenda/minutes/bundle parsers, linker, chunker, embeddings
  db/               schema.sql and the database client
  agent/            tools, prompts and the hand-written agent loop
  app/              the web app: queries, chat limits, EN/FR strings, translations, pages
  minutes_text.py   the parts of a minutes entry shown and searched
  names.py          name normalization and matching across spellings
  roster.py         loads the City's council roster from open data
  quality.py        the metrics behind quality-report
  cli.py            init-db, load-roster, ingest, quality-report, ask
streamlit_app.py    web app entry point
scripts/            translations, map boundaries, one-off backfills
eval/               hand-labelled question set and grader
tests/              parser tests on real fixtures; tests/app for the web app
.github/workflows/  tests, weekly ingestion, translations
images/             screenshots of the live app
```

## Data sources

City data is © Ville de Montréal, used under [CC-BY 4.0](https://donnees.montreal.ca/licence-d-utilisation).

- Council documents: the City's legacy council portal (agendas, minutes, decision bundles), © Ville de Montréal.
- Council roster: [Liste des élu-es de la Ville de Montréal](https://donnees.montreal.ca/), Montreal open data, CC-BY 4.0.
- District boundaries: the City's 2025 electoral districts, simplified for display by `scripts/simplify_boundaries.py`. Sources and licence in `src/mtl_council_agent/app/data/README.md`.
- Address lookup: Québec's official [AQ Adresses service](https://servicescarto.mrnf.gouv.qc.ca/pes/rest/services/Territoire/AQ_ADRESSES_WMS/MapServer) (Ministère des Ressources naturelles et des Forêts). Addresses typed into the site are sent to that service only, and nothing is stored.
- City Hall photo: credited on the site's About page.
