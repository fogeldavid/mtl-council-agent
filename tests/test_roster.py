from mtl_council_agent.roster import parse_roster

# Shape of the City's CSV: a borough-only councillor, a blank row, a stray
# repeat of the header partway down (all skipped), and a councillor whose
# surname the file leaves blank.
SAMPLE = """\
Appellation,Prénom,Nom,Fonction élective,Arrondissement,District,Parti,Courriel officiel
Madame,Soraya,Martinez Ferrada,Maire(sse),Ville de Montréal,,Ensemble Montréal,
Madame,Alba Stella,Zuniga Ramos,Conseiller(ère) de la Ville,Mercier,Louis-Riel,EM,
Monsieur,Dimitrios (Jim),Beis,Maire(sse) d'arrondissement,Pierrefonds-Roxboro,,EM,
Madame,Anne,Exemple,Conseiller(ère) d'arrondissement,Anjou,Ouest,Équipe Anjou,
,,,,,,,
Appellation,Prénom,Nom,Fonction élective,Arrondissement,District,Parti,Courriel officiel
Madame,Maeva,,Conseiller(ère) de la Ville,Le Plateau,De Lorimier,PM,maeva.vilain@montreal.ca
"""


def test_only_city_council_members_are_kept():
    members = parse_roster(SAMPLE)
    assert [(m.last_name, m.role) for m in members] == [
        ("Martinez Ferrada", "mayor"),
        ("Zuniga Ramos", "city_councillor"),
        ("Beis", "borough_mayor"),
        ("Vilain", "city_councillor"),
    ]


def test_blank_fields_become_none():
    mayor = parse_roster(SAMPLE)[0]
    assert mayor.district is None
    assert mayor.borough == "Ville de Montréal"
    assert mayor.party == "Ensemble Montréal"


def test_blank_surname_is_recovered_from_the_email():
    # The City's 2025-11-02 file really does leave Maeva Vilain's surname
    # blank; loaded as is she became two officials, neither reachable.
    vilain = parse_roster(SAMPLE)[-1]
    assert (vilain.first_name, vilain.last_name) == ("Maeva", "Vilain")
