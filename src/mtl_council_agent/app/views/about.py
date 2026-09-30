"""About: where the data comes from, what the labels mean, and the limits."""

from __future__ import annotations

import streamlit as st

from mtl_council_agent.app.common import masthead
from mtl_council_agent.app.i18n import lang

ABOUT = {
    "en": """
## About this site

Council Record Montreal is an unofficial project that makes Montreal city council's
decisions searchable. It is not affiliated with the Ville de Montréal and is not legal
advice. Every page links to the city's original documents: check them before relying on
anything here.

### Where the data comes from
Each council meeting publishes three PDFs on the city's website: the agenda, the minutes,
and a bundle of decision summaries. A weekly job downloads them, reads them, and links
each agenda item to its outcome and summary. The list of council members, with their role,
borough and party, comes from the City's open data portal. Data © Ville de Montréal,
[CC BY 4.0](https://donnees.montreal.ca/licence-d-utilisation).

### Recorded and inferred votes
The minutes record individual votes in three situations: a roll-call vote lists everyone
for and against, a dissent list names who opposed a majority vote, and a member with a
conflict of interest declares it and abstains. Those are shown as **recorded**.

Most items pass unanimously, and the minutes don't name anyone. For those, the site shows
who was present at that sitting as voting for, and labels it **inferred from attendance**.
When an item passes by majority and the minutes don't name the opponents, nobody is
attributed a position.

### Orientation votes
Near the end of each meeting, city council votes on files going to the agglomeration
council, which runs services Montreal shares with the island's other municipalities. Those
are the city council's position, not the final decision.

### Coverage
City council meetings from January 2026 onward. Borough councils and the agglomeration
council are not included.
""",
    "fr": """
## À propos

Council Record Montreal est un projet non officiel qui rend les décisions du conseil
municipal de Montréal faciles à consulter. Il n'a aucun lien avec la Ville de Montréal et
ne constitue pas un avis juridique. Chaque page renvoie aux documents originaux de la
Ville : vérifiez-les avant de vous fier à quoi que ce soit ici.

### Provenance des données
Chaque séance du conseil publie trois PDF sur le site de la Ville : l'ordre du jour, le
procès-verbal et les sommaires décisionnels. Une tâche hebdomadaire les télécharge, les
lit et relie chaque point à son résultat et à son sommaire. La liste des élus, avec leur
fonction, leur arrondissement et leur parti, vient du portail de données ouvertes de la
Ville. Données © Ville de Montréal,
[CC BY 4.0](https://donnees.montreal.ca/licence-d-utilisation).

### Votes consignés et votes déduits
Le procès-verbal consigne des votes individuels dans trois cas : un vote enregistré nomme
tous les membres pour et contre, une liste de dissidences nomme les opposants à un vote
majoritaire, et un membre en conflit d'intérêts le déclare et s'abstient. Ces votes sont
indiqués comme **consignés**.

La plupart des points sont adoptés à l'unanimité sans nommer personne. Pour ceux-là, le
site indique les membres présents à la séance comme ayant voté pour, avec la mention
**déduit des présences**. Quand un point est adopté à la majorité sans que les opposants
soient nommés, aucune position n'est attribuée.

### Votes d'orientation
Vers la fin de chaque séance, le conseil municipal se prononce sur des dossiers destinés
au conseil d'agglomération, qui gère les services partagés avec les autres municipalités
de l'île. Il s'agit de la position du conseil municipal, pas de la décision finale.

### Couverture
Les séances du conseil municipal depuis janvier 2026. Les conseils d'arrondissement et le
conseil d'agglomération ne sont pas inclus.
""",
}


def render() -> None:
    masthead()
    st.markdown(ABOUT[lang()])
