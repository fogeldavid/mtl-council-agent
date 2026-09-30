"""A small, real-shaped database for the app's query and page tests.

The rows are taken from real 2026 records (the Veille sur toi dissent, a
rejected opposition motion decided by roll call, a conflict-of-interest
abstention, an orientation item), trimmed to a handful of members so the
expected numbers can be counted by hand.

Needs a Postgres with pgvector at TEST_DATABASE_URL; the tests skip without
one. Locally:
    docker run -d --name mtl-test-pg -e POSTGRES_PASSWORD=test -p 55432:5432 \\
        pgvector/pgvector:pg16
    export TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/postgres
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

SCHEMA = Path(__file__).parents[2] / "src" / "mtl_council_agent" / "db" / "schema.sql"

SEED = """
insert into meetings (id, meeting_date, meeting_time, meeting_type, source_url) values
  (1, '2026-03-23', '13:00', 'ordinaire', 'https://example.test/2026'),
  (2, '2026-09-21', '13:00', 'ordinaire', 'https://example.test/2026');

insert into documents (meeting_id, doc_type, source_pdf_url) values
  (1, 'agenda', 'https://example.test/odj-17122.pdf'),
  (1, 'minutes', 'https://example.test/pv-8354.pdf'),
  (2, 'agenda', 'https://example.test/odj-17519.pdf');

insert into officials
  (id, name, normalized_name, first_name, last_name, role, borough, district, party) values
  (1, 'Soraya Martinez Ferrada', 'soraya martinez ferrada', 'Soraya', 'Martinez Ferrada',
      'mayor', 'Ville de Montréal', null, 'Ensemble Montréal'),
  (2, 'Julien Hénault-Ratelle', 'julien henault-ratelle', 'Julien', 'Hénault-Ratelle',
      'city_councillor', 'Mercier–Hochelaga-Maisonneuve', 'Tétreaultville', 'Ensemble Montréal'),
  (3, 'Marie Plourde', 'marie plourde', 'Marie', 'Plourde',
      'city_councillor', 'Le Plateau-Mont-Royal', 'Mile-End', 'Projet Montréal'),
  (4, 'Ericka Alneus', 'ericka alneus', 'Ericka', 'Alneus',
      'city_councillor', 'Rosemont–La Petite-Patrie', 'Étienne-Desmarteau', 'Projet Montréal'),
  (5, 'Christopher McCray', 'christopher mccray', 'Christopher', 'McCray',
      'borough_mayor', 'Saint-Laurent', null, 'Projet Montréal');

insert into agenda_items
  (id, meeting_id, position, item_number, title, department, decision_summary, motion_number,
   mover_id, seconder_id, vote_outcome, dossier_number, section, sitting) values
  (10, 1, 0, '20.06', 'Résilier le contrat accordé à Veille sur toi inc.',
      'Service des ressources humaines et des communications', 'Il est recommandé de résilier.',
      'CM26 0316', 2, 1, 'adopted_majority', '1259722003', 'council', 0),
  (11, 1, 1, '65.02',
      'Motion de l''Opposition officielle - Pour le maintien de l''accès public aux berges',
      'Service du greffe', null, 'CM26 0387', 3, 4, 'rejected', null, 'council', 1),
  (12, 1, 2, '20.29', 'Approuver le projet d''entente de collaboration avec Ouranos inc.',
      'Direction générale', 'Entente de trois ans.', 'CM26 0469', 2, 1, 'adopted_unanimous',
      '1269320001', 'council', 0),
  (13, 1, 3, '20.01', 'Conclure une entente-cadre avec Agence Gravel inc.',
      'Service de police de Montréal', null, 'CM26 0599', 2, 1, 'adopted_unanimous',
      '1267026001', 'agglomeration_orientation', 0),
  (20, 2, 0, '20.01', 'Accorder un contrat de réfection de conduites', 'Service de l''eau',
      null, null, null, null, 'unknown', '1266000001', 'council', null);

insert into meeting_attendance (meeting_id, sitting, official_id, status) values
  (1, 0, 1, 'present'), (1, 0, 2, 'present'), (1, 0, 3, 'present'), (1, 0, 4, 'present'),
  (1, 0, 5, 'present'),
  (1, 1, 1, 'present'), (1, 1, 2, 'present'), (1, 1, 3, 'present'), (1, 1, 4, 'present'),
  (1, 1, 5, 'absent_excused');

insert into item_votes (agenda_item_id, official_id, position, source) values
  (10, 3, 'against', 'dissent_list'), (10, 4, 'against', 'dissent_list'),
  (11, 3, 'for', 'roll_call'), (11, 4, 'for', 'roll_call'),
  (11, 1, 'against', 'roll_call'), (11, 2, 'against', 'roll_call'),
  (12, 5, 'abstained', 'interest_declaration');
"""


CHUNKS = [
    (10, "Résiliation du contrat Veille sur toi pour le projet Bienvenue bébé."),
    (11, "Motion pour l'accès public aux berges du lac Saint-Louis à Lachine."),
    (12, "Entente de collaboration avec Ouranos sur l'adaptation aux changements climatiques."),
]


@pytest.fixture(scope="session")
def db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; app query tests need a Postgres with pgvector")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("drop schema if exists public cascade")
        conn.execute("create schema public")
        conn.execute(SCHEMA.read_text())
        conn.execute(SEED)
        # One chunk per item, each pointing along its own axis, so a query
        # vector along axis k has a known nearest item.
        for axis, (item_id, content) in enumerate(CHUNKS):
            vector = [0.0] * 768
            vector[axis] = 1.0
            conn.execute(
                "insert into item_chunks (agenda_item_id, chunk_index, content, embedding) "
                "values (%s, 0, %s, %s::halfvec)",
                (item_id, content, str(vector)),
            )
    return url



@pytest.fixture
def conn(db_url):
    with psycopg.connect(db_url, autocommit=True) as connection:
        yield connection
