-- mtl-council-agent database schema
-- Postgres + pgvector. Run once against a fresh database (Supabase/Neon free tier).

create extension if not exists vector;

-- Identity is (date, time, type), not source_url. The legacy portal has no
-- per-meeting page: source_url is the year listing, identical for every
-- meeting in that year, so a unique constraint on it collapses all ~10
-- meetings of a year into one row and their agenda items overwrite each
-- other by position. Time is part of the key because a single day can hold
-- both an ordinary sitting and an extraordinary one at different hours.
create table if not exists meetings (
    id serial primary key,
    meeting_date date not null,
    meeting_time time not null,
    meeting_type text not null check (meeting_type in ('ordinaire', 'extraordinaire')),
    source_url text not null,
    created_at timestamptz not null default now(),
    unique (meeting_date, meeting_time, meeting_type)
);

-- The city republishes a revised agenda at the SAME URL: every 2025-26
-- agenda reached version 2 or 3. Knowing the URL isn't knowing the content,
-- so each document keeps the fingerprint the server returned when it was
-- ingested (a HEAD request, no download), and a changed ETag triggers a
-- re-ingest. The 2026-09-21 agenda went from 92 items to 122 this way
-- without the URL changing.
create table if not exists documents (
    id serial primary key,
    meeting_id integer not null references meetings(id) on delete cascade,
    doc_type text not null check (doc_type in ('agenda', 'minutes', 'bundle')),
    source_pdf_url text not null unique,
    etag text,
    last_modified text,
    content_length bigint,
    ingested_at timestamptz not null default now()
);

-- Elected officials, used for accountability search ("how did X vote").
-- Role, borough, district and party come from the City's open-data roster
-- (roster.py). An official with a null role was named in the minutes but not
-- found on the roster, which the quality report surfaces for review.
-- first_name/last_name are the roster's own split: roll-call votes name
-- members by surname alone ("Pinard", "V. Doyon"), so resolving them needs
-- the surname as the roster records it, not a guess at where it starts.
-- Identity is normalized_name, not name. The minutes spell one person several
-- ways -- "M. Claude Pinard" and "Claude Pinard", "Ericka Alneus" and "Ericka
-- Alnéus" -- and keying on the raw string filed them as separate councillors,
-- which quietly splits their voting record in accountability searches. `name`
-- keeps the display spelling, accents and all. See names.py.
create table if not exists officials (
    id serial primary key,
    name text not null,
    normalized_name text not null unique,
    first_name text,
    last_name text,
    role text check (role in ('mayor', 'borough_mayor', 'city_councillor')),
    borough text,
    district text,
    party text
);

-- Every spelling the minutes have used for an official, and how it was
-- resolved. Without this a fuzzy merge is invisible: you cannot tell whether
-- a councillor's record was assembled from one spelling or four, nor check
-- that a similarity match was right. `matched_by` and `similarity` make each
-- decision auditable after the fact.
create table if not exists official_aliases (
    id serial primary key,
    official_id integer not null references officials(id) on delete cascade,
    raw_name text not null unique,
    normalized_name text not null,
    matched_by text not null check (matched_by in ('new', 'normalized', 'similarity', 'roster')),
    similarity real,
    times_seen integer not null default 1,
    first_seen timestamptz not null default now()
);

create index if not exists official_aliases_official_idx on official_aliases (official_id);

-- One row per agenda item per meeting, joined across all three document
-- types: agenda -> title/department, minutes -> mover/seconder/outcome,
-- bundle -> decision_summary. Item numbers repeat across sections, so
-- dossier_number is the real cross-document key (nullable: procedural items
-- like "Période de questions du public" have no dossier).
-- Keyed on (meeting_id, position), not item number. Item numbers repeat within
-- a single agenda -- the council section and the agglomeration-orientation
-- section run independent series that both use "20.01", "20.02" and so on.
-- Measured across 20 real meetings, a unique constraint on item_number would
-- silently overwrite 29% of items (735 of 2,536). Dossier numbers come close
-- to unique but still collide a few times per meeting, so position within the
-- agenda is the only safe key, and it preserves running order for free.
create table if not exists agenda_items (
    id serial primary key,
    meeting_id integer not null references meetings(id) on delete cascade,
    position integer not null,
    item_number text not null,
    title text not null,
    department text,
    decision_summary text,
    motion_number text,
    mover_id integer references officials(id),
    seconder_id integer references officials(id),
    -- 'adopted' is an adoption the minutes don't qualify as unanimous or by
    -- majority; 'noted' is a filing or notice of motion, recorded but not
    -- voted on.
    vote_outcome text check (vote_outcome in (
        'adopted_unanimous', 'adopted_majority', 'adopted', 'rejected',
        'withdrawn', 'noted', 'unknown'
    )),
    dossier_number text,
    -- The agenda's closing section ("80 – Conseil d'agglomération - Dossiers
    -- pour orientation") restarts item numbering, so an item is identified by
    -- section and number together.
    section text not null default 'council'
        check (section in ('council', 'agglomeration_orientation')),
    -- Which sitting (0 = first) the item was voted in. A meeting runs over two
    -- sittings with different attendance, so "who was present for this vote"
    -- depends on it. Null when the minutes don't cover the item.
    sitting smallint,
    -- Resolution and dossier numbers belong in here, not just the prose.
    -- "What is CM26 0677 about" is the plainest exact-token lookup there is,
    -- and indexing only title and summary made it return nothing: the number
    -- lives in its own column, and dossier numbers matched only by accident
    -- when they happened to be quoted inside the summary text.
    search_vector tsvector generated always as (
        to_tsvector(
            'french',
            coalesce(title, '') || ' ' || coalesce(decision_summary, '') || ' '
            || coalesce(motion_number, '') || ' ' || coalesce(dossier_number, '')
        )
    ) stored,
    unique (meeting_id, position)
);

-- Decision summaries run to ~26,000 characters, far past the embedding
-- model's 512-token window, so vectors live per chunk rather than per item.
-- Semantic search hits chunks and joins back up to the item for citation.
-- Embeddings are halfvec, not vector. At full precision a 768-dim vector is
-- 3KB, which overflows the inline row limit into TOAST and builds a large HNSW
-- index: measured on real data, 5,592 chunks cost 36.7MB of TOAST plus a
-- 35.3MB index, projecting to 557MB for the corpus against a 500MB free tier.
-- Half precision halves both. The vectors are L2-normalized, so the precision
-- loss is far below the noise floor of the retrieval itself.
create table if not exists item_chunks (
    id serial primary key,
    agenda_item_id integer not null references agenda_items(id) on delete cascade,
    chunk_index integer not null,
    content text not null,
    embedding halfvec(768),
    unique (agenda_item_id, chunk_index)
);

-- Who attended each sitting, from its "PRÉSENCES" roll. The minutes
-- distinguish excused, unexcused, and barred absences (a member who lost the
-- right to sit under article 502 of the municipal elections act), and so
-- does this table.
create table if not exists meeting_attendance (
    meeting_id integer not null references meetings(id) on delete cascade,
    sitting smallint not null,
    official_id integer not null references officials(id),
    status text not null check (status in (
        'present', 'absent_excused', 'absent_unexcused', 'absent_barred'
    )),
    primary key (meeting_id, sitting, official_id)
);

-- Individual positions the minutes RECORD, and nothing else. A roll call
-- names everyone for and against; a dissent list names who voted against a
-- majority vote; a conflict-of-interest declaration records an abstention.
-- A "for" position that isn't in a roll call is never stored: it is derived
-- at query time from attendance and labelled as inferred, and a majority
-- vote with no named dissenters attributes nobody.
create table if not exists item_votes (
    agenda_item_id integer not null references agenda_items(id) on delete cascade,
    official_id integer not null references officials(id),
    position text not null check (position in ('for', 'against', 'abstained')),
    source text not null check (source in ('roll_call', 'dissent_list', 'interest_declaration')),
    primary key (agenda_item_id, official_id)
);

create index if not exists agenda_items_search_idx on agenda_items using gin (search_vector);
create index if not exists agenda_items_mover_idx on agenda_items (mover_id);
create index if not exists agenda_items_seconder_idx on agenda_items (seconder_id);
create index if not exists agenda_items_dossier_idx on agenda_items (dossier_number);
create index if not exists item_chunks_embedding_idx on item_chunks using hnsw (embedding halfvec_cosine_ops);
create index if not exists item_chunks_item_idx on item_chunks (agenda_item_id);
create index if not exists item_votes_official_idx on item_votes (official_id);
create index if not exists meeting_attendance_official_idx on meeting_attendance (official_id);
