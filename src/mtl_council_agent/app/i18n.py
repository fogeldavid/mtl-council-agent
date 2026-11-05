"""Interface text in English and French.

Only the interface is translated. Records stay in the French they were
published in; the chat explains them in English on request.
"""

from __future__ import annotations

import streamlit as st

STRINGS: dict[str, dict[str, str]] = {
    "find.title": {
        "en": "Don't know your district? Enter your address.",
        "fr": 'Vous ne connaissez pas votre district? Entrez votre adresse.',
    },
    'find.address': {
        "en": ('Civic number and street name'),
        "fr": ('Numéro civique et nom de rue'),
    },
    "find.hint": {
        "en": 'Example: 275 Notre-Dame Est',
        "fr": 'Exemple : 275 Notre-Dame Est',
    },
    "find.privacy": {
        "en": "Search sends your street number and name to Québec's official address "
              "service. This app doesn't save them.",
        "fr": "La recherche transmet votre numéro et votre rue au service officiel "
              "d’adresses du Québec. Cette application ne les conserve pas.",
    },
    "find.submit": {
        "en": 'Find',
        "fr": 'Rechercher',
    },
    "find.invalid": {
        "en": "Enter a civic number and a street name, like 275 Notre-Dame Est. A postal "
              "code alone can't identify a district.",
        "fr": "Entrez un numéro civique et un nom de rue, comme 275 Notre-Dame Est. Un code"
              " postal seul ne permet pas d’identifier un district.",
    },
    "find.none": {
        "en": "No address found in Montréal's electoral districts. Check the spelling, or "
              "select your district on the map.",
        "fr": "Aucune adresse trouvée dans les districts de Montréal. Vérifiez "
              "l’orthographe ou sélectionnez votre district sur la carte.",
    },
    "find.error": {
        "en": "The address service is unavailable, or that search matched too many "
              "addresses. Try again, or select your district on the map.",
        "fr": "Le service d’adresses est indisponible, ou la recherche donne trop de "
              "résultats. Réessayez ou sélectionnez votre district sur la carte.",
    },
    'find.confirm': {
        "en": ('Choose your matching address'),
        "fr": ('Choisissez votre adresse'),
    },
    'find.select': {
        "en": ('Show this district'),
        "fr": ('Afficher ce district'),
    },
    "find.success": {
        "en": 'Your district: {district}.',
        "fr": 'Votre district : {district}.',
    },
    'find.source': {
        "en": ('Address source: Québec · Ministère des Ressources naturelles et des '
               'Forêts'),
        "fr": ('Source des adresses : Québec · Ministère des Ressources naturelles et '
               'des Forêts'),
    },
    "feed.back": {"en": "Back to the newsfeed", "fr": "Retour au fil d’actualités"},
    "feed.minutes_only": {
        "en": "Council votes with published minutes. "
              "Open a record for the summary and voting details.",
        "fr": "Votes avec procès-verbal publié. Ouvrez un document pour le résumé et les votes.",
    },
    "feed.search_hint": {
        "en": "Search decisions, a company, or a resolution number…",
        "fr": "Rechercher une décision, une entreprise ou un numéro de résolution…",
    },
    "feed.search_french": {
        "en": "This box searches the French text. To search in English, "
              "open Search and choose By meaning.",
        "fr": "Cette recherche porte sur le texte français.",
    },
    "feed.filters": {"en": "Filter decisions", "fr": "Filtrer les décisions"},
    "feed.count": {
        "en": "{start}–{end} of {total} decisions", "fr": "{start}–{end} sur {total} décisions",
    },
    "feed.previous": {"en": "← Previous", "fr": "← Précédent"},
    "feed.next": {"en": "Next →", "fr": "Suivant →"},
    "translation.label": {
        "en": "Translated from the French original · Machine translation",
        "fr": "Traduction automatique de l’original français",
    },
    "translation.pending": {
        "en": "French original — English translation awaiting review.",
        "fr": "Original français — traduction anglaise en attente de vérification.",
    },
    "translation.context": {"en": "Context (English)", "fr": "Contexte (anglais)"},
    "translation.original": {
        "en": "Read the French original", "fr": "Lire l’original français",
    },
    "translation.context_missing": {
        "en": "An English context excerpt is not available for this record. "
              "Read the French original below.",
        "fr": "Aucun extrait de contexte anglais pour ce document. "
              "Consultez l’original français ci-dessous.",
    },
    "nav.records": {"en": "Records & about", "fr": "Archives et à propos"},
    "nav.feed": {"en": "Newsfeed", "fr": "Fil d’actualités"},
    "nav.map": {
        "en": 'Districts',
        "fr": 'Districts',
    },
    "nav.ask": {"en": "Ask the council", "fr": "Questions au conseil"},
    "nav.updates": {"en": "Council updates", "fr": "Actualités du conseil"},
    "nav.districts": {"en": "District explorer", "fr": "Explorer les districts"},
    "publication.tagline": {
        "en": "Your city. Your council. Your everyday life.",
        "fr": "Votre ville. Votre conseil. Votre quotidien.",
    },
    "updates.title": {
        "en": "Inside your city council.",
        "fr": "Au cœur de votre conseil municipal.",
    },
    "updates.subtitle": {
        "en": "The decisions being made. The neighbourhoods they shape.",
        "fr": "Les décisions qui se prennent. Les quartiers qu’elles façonnent.",
    },
    "updates.kicker": {"en": "THE CITY, IN FOCUS", "fr": "PLEINS FEUX SUR LA VILLE"},
    "updates.read": {"en": "Read the record", "fr": "Lire le document"},
    "updates.empty": {
        "en": "No records match these filters.",
        "fr": "Aucun document ne correspond à ces filtres.",
    },
    "updates.more": {
        "en": "Showing up to 24 records. Search the full archive for more.",
        "fr": "Jusqu’à 24 documents affichés. Consultez les archives pour en voir davantage.",
    },
    "find.searching": {"en": "Searching for your address…", "fr": "Recherche de votre adresse…"},
    "find.no_number": {
        "en": "We found that street, but not that civic number. Check the number, "
              "or select your district on the map.",
        "fr": "Nous avons trouvé cette rue, mais pas ce numéro civique. Vérifiez le "
              "numéro ou sélectionnez votre district sur la carte.",
    },
    "districts.representatives": {
        "en": "Who represents you at city council. Select a name to see their votes.",
        "fr": "Qui vous représente au conseil municipal. Sélectionnez un nom pour voir ses votes.",
    },
    "districts.title": {
        "en": 'District and councillor',
        "fr": 'District et élus',
    },
    "districts.choose": {"en": "Find your district", "fr": "Trouvez votre district"},
    "districts.empty": {
        "en": "No districts are available in the imported roster.",
        "fr": "Aucun district dans le répertoire importé.",
    },
    "districts.preview": {
        "en": "Map preview: official boundaries and a saved public roster. Connect the "
              "council database to see recorded votes and source minutes.",
        "fr": "Aperçu : limites officielles et répertoire public enregistré. Connectez la "
              "base de données pour voir les votes consignés et les procès-verbaux.",
    },
    "districts.no_representative": {
        "en": "No exact district match in the city council roster. Some districts elect "
              "borough-only councillors, whose votes this app does not cover.",
        "fr": "Aucune correspondance exacte dans le répertoire du conseil municipal. "
              "Certains districts élisent des conseillers d’arrondissement dont les votes "
              "ne sont pas couverts ici.",
    },
    "districts.borough_wide": {
        "en": "Elected for the whole borough, not only this district.",
        "fr": "Élu pour tout l’arrondissement, pas seulement ce district.",
    },
    "districts.basemap": {
        "en": "Show street background (loads external map tiles)",
        "fr": "Afficher les rues (charge des tuiles cartographiques externes)",
    },
    "districts.map_help": {
        "en": "Click a district or use the selector above. Boundaries are loaded locally.",
        "fr": "Cliquez sur un district ou utilisez le sélecteur. Les limites sont locales.",
    },
    "districts.attribution": {
        "en": "2025 electoral boundaries · Ville de Montréal · CC BY 4.0. "
              "Map outlines are simplified to about 6 metres. "
              "Address lookup uses the official boundaries.",
        "fr": "Limites électorales de 2025 · Ville de Montréal · CC BY 4.0. "
              "Les contours de la carte sont simplifiés à environ 6 mètres. "
              "La recherche d’adresse utilise les limites officielles.",
    },
    "districts.roster_source": {
        "en": "Official representative roster", "fr": "Répertoire officiel des élus",
    },
    "districts.roster_date": {
        "en": "Public roster downloaded {date}; this preview does not update it live.",
        "fr": "Répertoire public téléchargé le {date}; cet aperçu ne l’actualise pas en direct.",
    },
    "database.title": {"en": "Connect your council records", "fr": "Connectez vos documents"},
    "database.missing": {
        "en": "Add WEB_DATABASE_URL to .env or Streamlit secrets to browse council records. "
              "The district map can already be previewed without a database.",
        "fr": "Ajoutez WEB_DATABASE_URL à .env ou aux secrets Streamlit pour consulter "
              "les documents. La carte des districts est accessible sans base de données.",
    },
    "database.preview": {"en": "Preview the district map", "fr": "Voir la carte des districts"},
    "districts.boundaries": {
        "en": "Official electoral district map data",
        "fr": "Données officielles des districts électoraux",
    },
    "nav.search": {"en": "Search", "fr": "Recherche"},
    "nav.meetings": {"en": "Meetings", "fr": "Séances"},
    "nav.councillors": {"en": "Councillors", "fr": "Élus"},
    "nav.about": {"en": "About", "fr": "À propos"},
    "banner": {
        "en": "<b>UNOFFICIAL</b> · Built on the City of Montreal's public records. Not affiliated "
        "with the Ville de Montréal. Always check the cited source.",
        "fr": "<b>NON OFFICIEL</b> · Construit à partir des documents publics de la Ville de "
        "Montréal. Aucun lien avec la Ville de Montréal. Vérifiez toujours la source citée.",
    },
    "home.title": {
        "en": "What did city council decide, and who voted how?",
        "fr": "Qu'a décidé le conseil municipal, et qui a voté quoi?",
    },
    "home.record": {"en": "The record", "fr": "Le registre"},
    "home.contested": {"en": "Contested votes", "fr": "Votes contestés"},
    "chat.placeholder": {
        "en": "Ask about a decision, a vote or a councillor",
        "fr": "Posez une question sur une décision, un vote ou un élu",
    },
    "chat.examples": {
        "en": "For example: *Who voted against cancelling the Veille sur toi contract?* or "
        "*What did council decide about bike paths this year?*",
        "fr": "Par exemple : *Qui a voté contre la résiliation du contrat de Veille sur toi?* ou "
        "*Qu'a décidé le conseil sur les pistes cyclables cette année?*",
    },
    "chat.thinking": {"en": "Reading the records…", "fr": "Lecture des documents…"},
    "chat.notice": {
        "en": "Answers are generated by Anthropic's Claude from the council records and cite "
        "them; check the cited item before relying on one. Questions are not saved. Don't "
        "include personal information.",
        "fr": "Les réponses sont générées par Claude (Anthropic) à partir des documents du "
        "conseil, qu'elles citent; vérifiez le point cité avant de vous y fier. Les questions "
        "ne sont pas conservées. N'incluez aucun renseignement personnel.",
    },
    "chat.free_left": {
        "en": "{n} of {total} free questions left today.",
        "fr": "{n} questions gratuites sur {total} restantes aujourd'hui.",
    },
    "chat.clear": {"en": "New conversation", "fr": "Nouvelle conversation"},
    "chat.sources": {
        "en": "Documents for the meetings above, in French. "
              "Each covers a whole meeting, not one claim.",
        "fr": "Documents des séances ci-dessus, en français. "
              "Chacun couvre toute une séance, pas une seule affirmation.",
    },
    "doc.agenda": {"en": "Agenda (FR)", "fr": "Ordre du jour"},
    "doc.minutes": {"en": "Minutes (FR)", "fr": "Procès-verbal"},
    "doc.bundle": {"en": "Decision documents (FR)", "fr": "Dossiers décisionnels"},
    "chat.unavailable": {
        "en": "Chat is temporarily unavailable. You can still browse decisions and source records.",
        "fr": "Le clavardage est indisponible. Les décisions et leurs sources restent accessibles.",
    },
    "chat.pool_out": {
        "en": "The free questions are used up for now.",
        "fr": "Les questions gratuites sont épuisées pour le moment.",
    },
    "chat.busy": {
        "en": "The model is busy. Try again in a minute.",
        "fr": "Le modèle est occupé. Réessayez dans une minute.",
    },
    "explain.button": {"en": "Explain this item in English", "fr": "Expliquer ce point"},
    "explain.question": {
        "en": "Explain agenda item {number} of the {date} meeting (item_id {item_id}, "
        "\"{title}\") in plain English: what was decided, why, what it costs, and how "
        "council voted.",
        "fr": "Expliquez en français simple le point {number} de la séance du {date} "
        "(item_id {item_id}, « {title} ») : ce qui a été décidé, pourquoi, ce que ça coûte et "
        "comment le conseil a voté.",
    },
    "stat.meetings": {"en": "Meetings", "fr": "Séances"},
    "stat.items": {"en": "Agenda items", "fr": "Points à l'ordre du jour"},
    "stat.votes": {"en": "Recorded votes", "fr": "Votes consignés"},
    "stat.members": {"en": "Council members", "fr": "Membres du conseil"},
    "roll_call": {"en": "roll call", "fr": "vote enregistré"},
    "dissent": {"en": "recorded dissent", "fr": "dissidence consignée"},
    "outcome.adopted_unanimous": {"en": "Unanimous", "fr": "Unanimité"},
    "outcome.adopted_majority": {"en": "Majority", "fr": "Majorité"},
    "outcome.adopted": {"en": "Adopted", "fr": "Adopté"},
    "outcome.rejected": {"en": "Rejected", "fr": "Rejeté"},
    "outcome.withdrawn": {"en": "Withdrawn", "fr": "Retiré"},
    "outcome.noted": {"en": "Noted", "fr": "Pris acte"},
    "outcome.unknown": {"en": "No minutes yet", "fr": "Procès-verbal à venir"},
    # Minutes are in, but they record no decision (question periods, announcements).
    "outcome.no_decision": {"en": "No decision", "fr": "Aucune décision"},
    "meetings.title": {"en": "Council meetings", "fr": "Séances du conseil"},
    "meetings.hint": {
        "en": "Select a meeting to see its agenda and votes.",
        "fr": "Choisissez une séance pour voir son ordre du jour et ses votes.",
    },
    "meeting.ordinaire": {"en": "ordinary meeting", "fr": "séance ordinaire"},
    "meeting.extraordinaire": {"en": "special meeting", "fr": "séance extraordinaire"},
    "meeting.items_hint": {
        "en": "Select an item to read its summary and votes.",
        "fr": "Choisissez un point pour lire son sommaire et ses votes.",
    },
    "meeting.no_minutes": {
        "en": "Minutes not published yet, so outcomes and votes are not available.",
        "fr": "Procès-verbal pas encore publié : résultats et votes non disponibles.",
    },
    "meeting.sitting": {"en": "Sitting", "fr": "Séance"},
    "meeting.present": {"en": "present", "fr": "présents"},
    "meeting.absent": {"en": "absent", "fr": "absents"},
    "col.date": {"en": "Date", "fr": "Date"},
    "col.item": {"en": "Item", "fr": "Point"},
    "col.title": {"en": "Title", "fr": "Titre"},
    "col.outcome": {"en": "Outcome", "fr": "Résultat"},
    "col.items": {"en": "Items", "fr": "Points"},
    "col.type": {"en": "Type", "fr": "Type"},
    "col.minutes": {"en": "Minutes", "fr": "Procès-verbal"},
    "col.name": {"en": "Name", "fr": "Nom"},
    "col.role": {"en": "Role", "fr": "Fonction"},
    "col.borough": {"en": "Borough", "fr": "Arrondissement"},
    "col.party": {"en": "Party", "fr": "Parti"},
    "col.vote": {"en": "Vote", "fr": "Vote"},
    "col.party_vote": {"en": "Party majority", "fr": "Majorité du parti"},
    "col.how": {"en": "How", "fr": "Comment"},
    "yes": {"en": "Yes", "fr": "Oui"},
    "no": {"en": "No", "fr": "Non"},
    "back.meetings": {"en": "All meetings", "fr": "Toutes les séances"},
    "back.meeting": {"en": "Back to the meeting", "fr": "Retour à la séance"},
    "back.councillors": {"en": "All councillors", "fr": "Tous les élus"},
    "item.moved_by": {
        "en": "Moved by {mover}, seconded by {seconder}",
        "fr": "Proposé par {mover}, appuyé par {seconder}",
    },
    "item.pdf_bundle": {
        "en": "Original decision documents (French PDF)",
        "fr": "Dossiers décisionnels originaux (PDF français)",
    },
    "item.summary": {"en": "Decision summary (French)", "fr": "Sommaire décisionnel"},
    "item.no_summary": {"en": "No decision summary on file.", "fr": "Aucun sommaire décisionnel."},
    "item.pdf_agenda": {
        "en": "Agenda (PDF, city website)",
        "fr": "Ordre du jour (PDF, site de la Ville)",
    },
    "item.pdf_minutes": {
        "en": "Minutes (PDF, city website)",
        "fr": "Procès-verbal (PDF, site de la Ville)",
    },
    "item.votes": {"en": "How council voted", "fr": "Comment le conseil a voté"},
    "item.for": {"en": "for", "fr": "pour"},
    "item.against": {"en": "against", "fr": "contre"},
    "item.recorded": {"en": "recorded", "fr": "consigné"},
    "item.inferred": {"en": "inferred from attendance", "fr": "déduit des présences"},
    "item.recorded_against": {"en": "Recorded against", "fr": "Contre (consigné)"},
    "item.recorded_for": {"en": "Recorded for", "fr": "Pour (consigné)"},
    "item.abstained": {
        "en": "Declared a conflict of interest and abstained",
        "fr": "A déclaré son intérêt et s'est abstenu",
    },
    "item.note.roll_call": {
        "en": "Roll-call vote: every position shown is recorded in the minutes.",
        "fr": "Vote enregistré : chaque position est consignée au procès-verbal.",
    },
    "item.note.unanimous": {
        "en": "Adopted unanimously. The minutes don't name individual votes; \"for\" means every "
        "member recorded present at that sitting, minus declared abstentions.",
        "fr": "Adopté à l'unanimité. Le procès-verbal ne nomme pas les votes; « pour » désigne les "
        "membres présents à cette séance, moins les abstentions déclarées.",
    },
    "item.note.majority_named": {
        "en": "Adopted by majority. The minutes name the dissenters; \"for\" is everyone present "
        "minus them, so it is inferred.",
        "fr": "Adopté à la majorité. Le procès-verbal nomme les dissidents; « pour » est déduit : "
        "les présents, moins eux.",
    },
    "item.note.majority_unnamed": {
        "en": "Adopted by majority, but the minutes don't say who voted against, so no member is "
        "attributed a position.",
        "fr": "Adopté à la majorité, mais le procès-verbal ne nomme pas les opposants : aucune "
        "position n'est attribuée.",
    },
    "item.note.orientation": {
        "en": "Orientation vote: the position city council set for the agglomeration council, "
        "which makes the final decision.",
        "fr": "Vote d'orientation : la position du conseil municipal pour le conseil "
        "d'agglomération, qui prend la décision finale.",
    },
    "item.note.none": {
        "en": "No individual votes are recorded for this item.",
        "fr": "Aucun vote individuel n'est consigné pour ce point.",
    },
    "councillors.title": {"en": "Council members", "fr": "Membres du conseil"},
    "councillors.hint": {
        "en": "Select a member to see their attendance and recorded votes.",
        "fr": "Choisissez un membre pour voir ses présences et ses votes consignés.",
    },
    "role.mayor": {"en": "Mayor", "fr": "Maire ou mairesse"},
    "role.borough_mayor": {"en": "Borough mayor", "fr": "Maire d'arrondissement"},
    "role.city_councillor": {"en": "City councillor", "fr": "Conseiller·ère de la Ville"},
    "profile.attended": {"en": "Sittings attended", "fr": "Séances présentes"},
    "profile.of": {"en": "of", "fr": "sur"},
    "profile.moved": {"en": "Items moved", "fr": "Points proposés"},
    "profile.seconded": {"en": "Items seconded", "fr": "Points appuyés"},
    "profile.absences": {
        "en": "Absences: {excused} excused, {unexcused} unexcused, {barred} barred from sitting.",
        "fr": "Absences : {excused} motivées, {unexcused} non motivées, {barred} privé de siéger.",
    },
    "profile.roll_calls": {"en": "Roll-call votes", "fr": "Votes enregistrés"},
    "profile.roll_calls_note": {
        "en": "Party majority is how most members of the same party voted on that roll call. "
        "It's shown for context, not as a score.",
        "fr": "La majorité du parti indique comment la plupart de ses membres ont voté. "
        "C'est un repère, pas une note.",
    },
    "profile.other": {"en": "Dissents and abstentions", "fr": "Dissidences et abstentions"},
    "profile.motions": {"en": "Items moved or seconded", "fr": "Points proposés ou appuyés"},
    "profile.none": {"en": "None recorded.", "fr": "Aucun."},
    "pos.for": {"en": "For", "fr": "Pour"},
    "pos.against": {"en": "Against", "fr": "Contre"},
    "pos.abstained": {"en": "Abstained", "fr": "Abstention"},
    "how.moved": {"en": "Moved", "fr": "Proposé"},
    "how.seconded": {"en": "Seconded", "fr": "Appuyé"},
    "search.title": {"en": "Search the record", "fr": "Chercher dans le registre"},
    "search.box": {"en": "Search words", "fr": "Mots à chercher"},
    "search.placeholder": {
        "en": "e.g. piste cyclable, déneigement, CM26 0316",
        "fr": "ex. piste cyclable, déneigement, CM26 0316",
    },
    "search.exact": {"en": "Exact words", "fr": "Mots exacts"},
    "search.meaning": {"en": "By meaning", "fr": "Par le sens"},
    "search.tip_exact": {
        "en": "Records are in French: search French words. For questions in English, use Ask.",
        "fr": "Les documents sont en français. Pour une question en anglais, utilisez Questions.",
    },
    "search.tip_meaning": {
        "en": "Finds items about the same topic even when the words differ, in English or French.",
        "fr": "Trouve les points sur le même sujet même si les mots diffèrent, en français ou en "
        "anglais.",
    },
    "search.loading_model": {
        "en": "Loading the meaning model (first search only)…",
        "fr": "Chargement du modèle de sens (première recherche seulement)…",
    },
    "search.meaning_unavailable": {
        "en": "Search by meaning is unavailable right now; showing exact-word results.",
        "fr": "La recherche par le sens est indisponible; résultats par mots exacts.",
    },
    "search.results": {"en": "{n} results", "fr": "{n} résultats"},
    "search.results_capped": {"en": "Top {n} results", "fr": "{n} premiers résultats"},
    "search.none": {
        "en": "No items match. Try fewer filters, or other words.",
        "fr": "Aucun point ne correspond. Essayez moins de filtres ou d'autres mots.",
    },
    "search.more": {"en": "Show more", "fr": "Afficher plus"},
    "search.open": {"en": "Open item {number} →", "fr": "Ouvrir le point {number} →"},
    "search.csv": {"en": "Download results (CSV)", "fr": "Télécharger les résultats (CSV)"},
    "filter.meeting": {"en": "Meeting", "fr": "Séance"},
    "filter.outcome": {"en": "Outcome", "fr": "Résultat"},
    "filter.section": {"en": "Section", "fr": "Section"},
    "filter.councillor": {"en": "Councillor", "fr": "Élu"},
    "filter.department": {"en": "Department", "fr": "Service"},
    "filter.all_meetings": {"en": "All meetings", "fr": "Toutes les séances"},
    "filter.any": {"en": "Any", "fr": "Tous"},
    "filter.anyone": {"en": "Anyone", "fr": "Tous"},
    "section.council": {"en": "City council", "fr": "Conseil municipal"},
    "section.agglomeration_orientation": {
        "en": "Agglomeration orientation",
        "fr": "Orientation, agglomération",
    },
    "orientation": {"en": "Agglomeration orientation", "fr": "Orientation, agglomération"},
    "updated": {"en": "Data last updated {date}.", "fr": "Données mises à jour le {date}."},
}


def lang() -> str:
    return "fr" if st.session_state.get("lang") == "FR" else "en"


def t(key: str, **values) -> str:
    text = STRINGS[key][lang()]
    return text.format(**values) if values else text
