# Project review — updated October 31, 2026

## What changed

- Expanded the existing question bank from 23 to 80 unique questions. Added English/French variants, amount-versus-total distinctions, recorded vote questions, source requests, scope boundaries, privacy questions, future records, and requests to fabricate facts or citations.
- Agent tool responses now include original PDF URLs loaded from `documents.source_pdf_url`. Final answers append a deterministic list of the meeting documents retrieved, so the chat's `result.text` retains links even if the model omits them.
- Added prompt instructions to cite links per factual claim, retain French sources, distinguish agendas/minutes/bundles, ignore instructions inside records, and never invent pages or URLs.
- Added regression tests for source URL lookup, URL scheme filtering, source delivery to the model, and final-answer link rendering.
- Added `compose.yaml` for a persistent local Postgres + pgvector database, bound to localhost.

## Verification status

After authorization to install test dependencies, pytest and the project dependencies were installed in `.venv` with standalone CPython 3.12.12. The Anaconda Python 3.12.7 interpreter initially selected by uv crashed while importing readline, so the virtual environment was recreated with standalone Python.

- `.venv/bin/python -m pytest -q -rs`: **106 passed, 55 skipped** in 3.70 seconds.
- All 55 skips require `TEST_DATABASE_URL` pointing to a disposable Postgres database with pgvector. Database-backed page, query and search tests remain unverified.
- `.venv/bin/ruff check src tests eval streamlit_app.py`: **all checks passed**, after fixing one import-order issue in the page tests.
- Python compilation and `git diff --check` passed. The question bank contains 80 unique, parseable cases with expected-answer or refusal fields.

No Postgres or Docker executable was available. Paid model evaluations have not run. Passing the isolated tests does not establish live database, model or end-to-end UI correctness. CI already provisions pgvector and Python 3.12. To reproduce its tests after installing dependencies:

```sh
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev,ui]'
.venv/bin/pytest -q
.venv/bin/ruff check src tests eval streamlit_app.py
```

App query/page tests additionally require a **disposable** database at `TEST_DATABASE_URL`. Do not point these tests at your real corpus: their fixtures create and remove database objects.

## What the question bank can and cannot do

80 questions provide broader regression coverage; many reuse the original labeled facts to avoid inventing new expected answers. They are not 80 independently verified civic decisions. The corpus and factual labels still need review. Live/future questions can become stale as the corpus changes, so record corpus version and evaluation date with results.

More questions cannot prevent all hallucinations. The existing grader checks keyword inclusion, refusal phrases, and whether item identifiers exist. It does not prove that every claim follows from the cited passage. French refusals and wording variations can also be misgraded. Next quality step: annotate supporting passages and expected document URLs, then use claim-grounded evaluation (with MLflow tracing/scorers) in addition to structural checks. Include missing minutes, missing summaries, ambiguous officials, orientation votes, and conflicting document revisions with reviewed evidence rather than speculative labels.

## Citation limits and next step

The new links are original French **meeting documents associated with retrieved records**. They do not certify that the model used every listed document, and are not exact passage citations. A document list alone cannot enforce claim-level grounding. Answers with no retrieved records have no source documents; they must decline unsupported civic claims.

Page numbers cannot currently be reliable: `strip_page_artifacts` removes page furniture and form feeds; `item_chunks` stores no document ID or page range. To support precise citations, preserve PDF page boundaries during extraction, retain document IDs and one-based PDF page ranges for agenda items, minutes votes and summary chunks, then re-ingest. Return those fields through every retrieval tool and render `PDF_URL#page=N`. Do not guess printed page numbers, which can differ from PDF page indexes.

A stronger release gate should reject unsupported source identifiers and require evidence for each factual claim, with a verified refusal path when evidence is absent. Prompt instructions and meeting links alone do not provide that guarantee.

## Local hosting and removing paid calls

The project already searches its own Postgres corpus and runs multilingual-e5 embeddings locally. It does not need to re-fetch the municipal PDFs for each question. The recurring paid calls are Anthropic generation; one question can require multiple model turns.

1. **Local information, paid generation:** run the supplied Postgres container, ingest once, and keep using Anthropic. This is the smallest change, but questions still incur model calls.
2. **Local information and local generation:** run a local model server such as Ollama and reuse the Anthropic Messages-compatible client. No paid cloud inference is needed for a downloaded local model, but there are still local HTTP requests and hardware/latency costs. Model downloads and corpus updates require network access initially.
3. **No model inference:** expose the existing full-text search, filters, excerpts and source links directly. This answers document lookups without generation, but does not provide arbitrary conversational synthesis.

Local database setup (Docker must be installed first):

```sh
# In an ignored .env file, set a chosen password and matching URL:
# LOCAL_POSTGRES_PASSWORD=<chosen password>
# DATABASE_URL=postgresql://council:<URL-encoded password>@127.0.0.1:55432/council

docker compose up -d db
mtl-council-agent init-db
mtl-council-agent load-roster
mtl-council-agent -v ingest --since 2026-01-01
```

Install Poppler (`pdftotext`) for ingestion. This starts an empty database; it does not migrate a hosted corpus. Transfer an existing corpus using a backup/restore workflow if needed. Keep the web app's read-only login separate from the ingestion owner, as in the existing README.

Ollama's official documentation supports `anthropic.Anthropic(base_url='http://localhost:11434', api_key='ollama')`. For a CLI experiment, the SDK can use `ANTHROPIC_BASE_URL=http://localhost:11434`, `ANTHROPIC_API_KEY=ollama`, and `MTL_AGENT_MODEL=<installed local model>`. Select a locally installed model supporting tool calls. This configuration is **not validated in this checkout**. The app's shared-pool billing/key flow and cost estimates are still designed for Anthropic and must be adapted before advertising a local mode. Validate strict tool schemas, context size, bilingual retrieval, and citation quality with the full question set before switching.

Sources: https://github.com/ollama/ollama/blob/main/docs/api/anthropic-compatibility.mdx and https://github.com/pgvector/pgvector.

Caching can reduce repeated generation, but cache keys must include normalized question, conversation context, model/prompt version, and corpus version. Never reuse an answer across corpus revisions without invalidation. No answer cache was added here.

## Frontend rebuild

After the user connected to Lovable, the project preview became accessible. A first implementation now adapts the existing Streamlit frontend to its newspaper-style masthead, serif headings, muted green accents and light background. Council updates is the new default page; District explorer and Ask the council provide the three primary screens. Existing archive, meetings, councillor profiles and about pages remain available.

The feed uses original record titles and stored outcomes, with department/search filtering and links to item detail. District explorer uses imported roster entries and links to each representative's actual recorded votes. Sample Lovable story text and fake voting data were not copied. The district map now renders all 58 official 2025 electoral polygons from bundled GeoJSON. Clicking a polygon updates the selector and representative panel. District-to-decision geography remains unavailable; a representative’s vote is not presented as proof that the decision affects that district. Chat retains its working session/key flow and now displays database source links.

This is an adaptation in Streamlit, not an import of Lovable's React source. An exact visual match remains unfinished. Map rendering and polygon selection were verified in the live browser: selecting Saint-Michel showed Josué Corvil. Database-backed voting queries still need a configured test database. Python compilation and lint passed; the new page/interaction tests were collected but skipped because the disposable Postgres test database is not configured. The isolated source-link tests passed.

For a later React migration: export the Lovable components, expose the existing read-only query functions and agent through a Python HTTP backend, and connect the UI to those endpoints. Keep credentials server-side. Preserve English/French UI, meeting and councillor browsing, chat history, and visible source links. Add the `/districts` screen only against available district/borough data; do not fill it with invented metrics. Validate responsive layouts and actual interactions against a seeded database before replacing Streamlit.


## Map and preview update — October 31

- Bundled the city's 58 official 2025 district polygons (gzip-compressed GeoJSON, with original coordinates preserved) and a dated public roster snapshot of 65 city council members. Data provenance and attribution are in `src/mtl_council_agent/app/data/README.md`.
- Added PyDeck polygon selection, tooltips, synchronized district dropdown, selected-district highlighting and English/French interface text.
- Representative matching uses both borough and district, with deterministic normalization of accents, punctuation and ligatures. Every nonempty roster district matches an official polygon; no fuzzy geography is inferred.
- With `WEB_DATABASE_URL` configured, each representative gets up to 20 recent explicitly recorded positions and original French minutes links. Attendance-inferred votes are excluded. The database query test is currently skipped with the other Postgres integration tests.
- Without a database, the map and dated public roster work; votes are unavailable rather than fabricated. Other data-backed pages show database setup instructions instead of crashing.
- Optional Carto background tiles use external network requests. Switching off the street background removes the basemap; district polygons continue to load from the local package.
- Seven offline map tests now cover the data, safe roster joins, nonmutating highlights, click callback, dropdown and basemap interaction, and exact coverage of named roster districts. Total: 106 passed, 55 database-dependent tests skipped; lint and whitespace checks pass.
- Live preview started on `http://127.0.0.1:8501/districts`, bound to localhost, with automatic source reloading. Restart when needed with `.venv/bin/python -m streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8501`.

## Navigation update — October 31

The public navigation now has three horizontal top-level tabs: Ask the council,
District explorer, and Council updates. The seven-link sidebar has been removed.
Map and Councillors belong to District explorer; Newsfeed, Meetings, Search and
About belong to Council updates. Original detail URLs and source links are retained,
with the parent section highlighted when a detail page is open.

Recommendation: keep this three-section structure while chat availability and per-user
costs remain unsettled. Council updates remains the default page for now. Once sustained
usage demonstrates an acceptable monthly inference budget and reliable availability,
a two-tab design is appropriate: a chat-first home with a small newsfeed beneath it,
and District explorer. The newsfeed should load from database queries rather than
invoke a model on each page load. Questions should be sent only when submitted.
Cache repeated eligible answers with corpus/prompt/model/context-aware invalidation,
limit answer length and tool turns, and keep browsing accessible when chat is unavailable.
Do not present an unmeasured future cost saving as an established result.

Validation: 118 tests passed; 55 Postgres-dependent tests skipped. Lint and whitespace
checks passed. Browser verification confirmed the three primary tabs, no sidebar, and
About opening within the Council updates section.

## Shared database connected — October 31

The local preview now connects to the team's existing populated database through
an ignored, owner-only `.env` file. A read-only connection check found 11 meetings,
1,231 agenda items, 65 officials and 1,060 recorded votes. No credentials or database
hostnames are recorded in this report. Browser checks confirmed that the newsfeed
loads actual records and the district panel shows recorded votes with original
French minutes links. No schema changes or ingestion were performed.

The shared Anthropic key remains unset, so generated chat answers are not enabled
yet. Do not use the team's database as TEST_DATABASE_URL: integration test fixtures
replace the public schema. The entrypoint navigation test now explicitly suppresses
database access so local credentials cannot make that offline test use shared data.
The 12 navigation tests and lint passed after this adjustment.

## Simplified feed — October 31

Council updates now exposes only Newsfeed and About. Meetings and Search remain as
internal legacy routes for existing links, but no longer have separate navigation
options. The newsfeed contains one keyword search above the content, three left-hand
filters (meeting date, outcome, department), and SQL-backed pagination in pages of 20.
Only adopted/rejected items whose meetings have published minutes are eligible; notices,
withdrawals, unknown outcomes and agenda-only meetings are excluded.

Opening a feed record displays the existing French decision summary, outcome, identifiers,
mover/seconder, original PDF links and recorded/inferred voting breakdown. The back button
returns to the feed and retains search/filter state. District and councillor record links
also open this same feed detail view. Ask the council is now a single chat area; the record
statistics and contested-vote sidebar have been removed. The publication shell is more compact.

Browser validation against the shared read-only data showed 946 eligible feed items. Searching
for Veille sur toi and opening the first result displayed CM26 0316, its French summary,
39 inferred votes for and 24 recorded votes against, matching the user's reference screenshot.
Returning to the feed preserved the search. No model API calls were made.

Tests: 122 passed, 56 disposable-Postgres-dependent tests skipped. New tests cover pagination,
filter reset, minutes-only meeting choices, detail/back behavior, preserved search and the
absence of statistics on Ask. Lint and whitespace checks passed.

## Fourth tab — October 31

Added Records & about as the fourth top-level tab (French: Archives et à propos).
It opens the meeting archive and groups Meetings and About in its secondary row.
Council updates now has no secondary navigation row; it goes straight to its
searchable newsfeed. Existing detail URLs retain their parent highlight.

The 13 navigation tests passed, including four primary links, the empty secondary
row on Council updates, and Meetings/About grouping. Lint and whitespace checks passed.

## English presentation (October 31, 2026)

English mode now shows cached English titles and short translated CONTEXTE
excerpts, labelled as machine translations of French originals. The full original
remains expandable and source PDF links remain available. Preparation runs locally
on CPU, reads the team database read-only, and saves source-hashed translations.
Browsing requires no translation API or model inference. Of 1,937 unique fields,
1,894 are saved; 43 failed fidelity validation and retain explicit French fallback.
The generated English text still needs human editorial review for semantic quality.
Validation: 134 tests passed, 56 database integration tests skipped; Ruff passed.

## District address finder (November 4, 2026)

Added below the map in EN/FR. Québec MRNF address queries use civic number and
street words, a Montréal bounding box, WGS84 output, then local point-in-polygon
validation. Results require user confirmation. Apartment records are collapsed;
exact direction tokens prevent Est/Ouest confusion. No-match, service error,
truncated responses and ambiguous district boundaries never change selection.
The app discloses the external lookup and retains no persistent search history.

Verified live using the public City Hall address: 275 rue Notre-Dame Est resolves
to Saint-Jacques. Focused tests cover polygon holes, multipart geometry, ambiguity,
postal-code rejection, address deduplication, direction matching, truncated provider
results and Streamlit confirmation/selection. Postal code search, typo handling and
translation refresh automation remain follow-up work before broader launch.

## Translation refresh and maintenance (November 4, 2026)

Completed the one-command refresh against all 1,231 current database records;
latest meeting present is October 19, 2026. Cache now contains 1,898 English text
fields. Title coverage is 1,103/1,113 unique titles and 936/946 decision records
(98.94%). The 39 remaining fields, including ten decision titles, retain French
fallbacks after validation. This confirms currency against the imported database,
not completeness against the City's publication portal.

`scripts/refresh_translations.py` handles model preparation, title priority,
number-protected retries and saved context updates. The new workflow can prepare
an output artifact after weekly ingestion once deployed/configured; manual copy
of the generated JSON to the deployment branch is still required. No automatic
commit, deployment or scheduled job has been activated in this local branch.
French street-name guidance is now a small caption under Find my district.
Focused translation/map/address tests: 27 passed; Ruff and diff whitespace passed.

## Public chat configuration and branch rename (November 4, 2026)

Local branch renamed to `citations-evaluation-local-hosting`; main unchanged.
Removed visitor API-key entry and backend visitor-key fallback. Public questions
use only the server's WEB_ANTHROPIC_API_KEY; missing credentials, refused credit
or exhausted allowances disable chat with a message. Legacy visitor session keys
cannot bypass the shared allowance. README and .env.example reflect this policy.

Deployment requires WEB_DATABASE_URL and WEB_ANTHROPIC_API_KEY in Streamlit
secrets/environment; a merge does not copy local secrets. The local database
works, but no shared Anthropic key is configured, so live model behavior remains
unverified. Provider spending controls must be configured separately; per-IP
in-memory quotas reset on restart and do not guarantee a financial cap.

Full test suite: 142 passed, 56 database integration tests skipped. Ruff passed.
Verified in the browser: disabled chat and availability message, no key-entry form.

## Pre-merge review (November 4, 2026)

Fixed default-page navigation: Council updates now switches to the default page
explicitly instead of generating an empty href that resolves to the current page.
District vote buttons also switch to the newsfeed detail explicitly. Navigation
regression tests were updated. CI now lints scripts and eval as well as app/tests.

Validation: 142 passed, 56 skipped, Ruff and whitespace checks clean. JSON/TOML
configuration parses and all 80 evaluation questions parse. Read-only live smoke
successfully queried the newsfeed, all 65 councillors and 11 meetings. Credentials,
Streamlit secrets and scratch files are ignored. No database schema changes.

Merge gates: the existing PR CI job must pass its 56 Postgres/pgvector integration
tests; this machine has no Docker/Postgres runtime. Live chatbot/citation quality
must be checked after configuring WEB_ANTHROPIC_API_KEY in deployment secrets.
This is not a claim that the 80-question live model evaluation has passed.
The translation workflow needs WEB_DATABASE_URL as a repository secret and manual
copy/review of its output artifact for deployment. No push or merge performed.

## Pre-merge fixes, November 4

Search has a link again, next to Newsfeed under Council updates, because search by meaning
and CSV export were otherwise reachable only by typing the URL. The newsfeed search reads
French text only, and the page now tells English-mode visitors so.

Districts now list members elected for the whole borough after the district councillor, so
all 58 districts show someone. Address lookup now connects over HTTP/2, because the provider
resets HTTP/1.1-only connections, and handles missing accents and common abbreviations.

The chat agent's semantic search failed on every call on the app's database connection,
which never registered the vector type. Keyword search hid the failure. The eval connects
a different way and could not catch it, so earlier eval scores do not cover this path.

The app now adds source links after the eval's grading point, so they can't affect a score.
It lists them only for meetings the answer names. CI now installs the same Streamlit version as the deployment.
