"""Official roster of city council members, from the City's open data.

Source: "Liste des élu-es de la Ville de Montréal", on donnees.montreal.ca.
The current file is dated 2 November 2025 (the start of the 2025-2029 term).
It lists 113 people; 65 of them sit on the city council -- the mayor, the 18
borough mayors and the 46 city councillors -- and those are the ones loaded.
Borough-only councillors never vote at city council.

The minutes give names only. The roster adds role, borough, district and
party, and splits each name into given names and surname, which is what lets
a surname-only roll call ("Pinard", "V. Doyon") resolve to one person.

Meetings before November 2025 belong to the 2021-2025 term, whose roster is
a separate file with different columns; loading it is left for the 2025
backfill.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass

import httpx

from mtl_council_agent.db import client as db

logger = logging.getLogger(__name__)

ROSTER_URL = (
    "https://donnees.montreal.ca/dataset/381d74ca-dadd-459f-95c9-db255b5f4480/resource/"
    "211f6903-1440-438a-9f6c-9718ecf2d3ee/download/liste_elus_montreal.csv"
)

# The open-data site answers a bot-style User-Agent with 403 ("RBAC: access
# denied") and redirects a browser-style one to the file.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36 mtl-council-agent"
    )
}

ROLES = {
    "Maire(sse)": "mayor",
    "Maire(sse) d'arrondissement": "borough_mayor",
    "Conseiller(ère) de la Ville": "city_councillor",
}


@dataclass
class RosterMember:
    first_name: str
    last_name: str
    role: str
    borough: str | None
    district: str | None
    party: str | None


def fetch_roster_csv(client: httpx.Client | None = None) -> str:
    owns_client = client is None
    client = client or httpx.Client()
    try:
        resp = client.get(ROSTER_URL, headers=_HEADERS, follow_redirects=True, timeout=60)
        resp.raise_for_status()
        return resp.content.decode("utf-8-sig")
    finally:
        if owns_client:
            client.close()


def _surname_from_email(email: str, first_name: str) -> str | None:
    """"maeva.vilain@montreal.ca" -> "Vilain". Loses accents, so it's only a
    fallback for a blank surname; matching is accent-blind either way."""
    local = email.strip().lower().split("@", 1)[0]
    given = first_name.strip().lower().replace(" ", "-")
    if "." not in local or not local.startswith(given + "."):
        return None
    return "-".join(part.capitalize() for part in local[len(given) + 1 :].split("-"))


def parse_roster(text: str) -> list[RosterMember]:
    """City council members from the roster CSV.

    Skips borough-only councillors, blank rows, and a stray second header row
    the file carries partway down.

    The 2025-11-02 file leaves one councillor's surname blank (Maeva Vilain).
    Loaded as is, she became a phantom "Maeva" while the minutes created a
    second, roster-less "Maeva Vilain" that no roll call could reach. A blank
    surname is recovered from the official email address instead.
    """
    members = []
    for row in csv.DictReader(io.StringIO(text)):
        role = ROLES.get((row.get("Fonction élective") or "").strip())
        if role is None:
            continue
        first_name = row["Prénom"].strip()
        last_name = row["Nom"].strip()
        if not last_name:
            last_name = _surname_from_email(row.get("Courriel officiel") or "", first_name)
            logger.warning(
                "roster row for %r has no surname; recovered %r from the email address",
                first_name,
                last_name,
            )
            if not last_name:
                continue
        members.append(
            RosterMember(
                first_name=first_name,
                last_name=last_name,
                role=role,
                borough=row.get("Arrondissement", "").strip() or None,
                district=row.get("District", "").strip() or None,
                party=row.get("Parti", "").strip() or None,
            )
        )
    return members


def load_roster(conn, members: list[RosterMember]) -> int:
    for member in members:
        db.upsert_roster_official(
            conn,
            first_name=member.first_name,
            last_name=member.last_name,
            role=member.role,
            borough=member.borough,
            district=member.district,
            party=member.party,
        )
    conn.commit()
    return len(members)
