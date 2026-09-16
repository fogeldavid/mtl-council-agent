-- mtl-council-agent database schema
-- Postgres + pgvector. Run once against a fresh database (Supabase/Neon free tier).

create extension if not exists vector;

create table if not exists meetings (
    id serial primary key,
    meeting_date date not null,
    meeting_type text not null check (meeting_type in ('ordinaire', 'extraordinaire')),
    source_url text not null unique,
    created_at timestamptz not null default now()
);

create table if not exists documents (
    id serial primary key,
    meeting_id integer not null references meetings(id) on delete cascade,
    doc_type text not null check (doc_type in ('agenda', 'minutes', 'bundle')),
    source_pdf_url text not null unique,
    ingested_at timestamptz not null default now()
);

-- Elected officials, used for accountability search ("how did X vote").
-- Role/district are null until backfilled from a maintained roster: the
-- minutes only give us names on mover/seconder lines.
create table if not exists officials (
    id serial primary key,
    name text not null unique,
    role text check (role in ('mayor', 'councillor', 'borough_mayor')),
    district text
);

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
    vote_outcome text check (vote_outcome in ('adopted', 'rejected', 'withdrawn', 'unknown')),
    dossier_number text,
    search_vector tsvector generated always as (
        to_tsvector('french', coalesce(title, '') || ' ' || coalesce(decision_summary, ''))
    ) stored,
    unique (meeting_id, position)
);

-- Decision summaries run to ~26,000 characters, far past the embedding
-- model's 512-token window, so vectors live per chunk rather than per item.
-- Semantic search hits chunks and joins back up to the item for citation.
create table if not exists item_chunks (
    id serial primary key,
    agenda_item_id integer not null references agenda_items(id) on delete cascade,
    chunk_index integer not null,
    content text not null,
    embedding vector(768),
    unique (agenda_item_id, chunk_index)
);

create index if not exists agenda_items_search_idx on agenda_items using gin (search_vector);
create index if not exists agenda_items_mover_idx on agenda_items (mover_id);
create index if not exists agenda_items_seconder_idx on agenda_items (seconder_id);
create index if not exists agenda_items_dossier_idx on agenda_items (dossier_number);
create index if not exists item_chunks_embedding_idx on item_chunks using hnsw (embedding vector_cosine_ops);
create index if not exists item_chunks_item_idx on item_chunks (agenda_item_id);
