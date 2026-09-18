"""Official-name identity, from real spellings found in the minutes."""

from mtl_council_agent.names import closest_match, display_name, normalized_name


def test_honorifics_are_dropped_from_the_display_name():
    assert display_name("M. Claude Pinard") == "Claude Pinard"
    assert display_name("Mme Marie Plourde") == "Marie Plourde"
    assert display_name("Claude Pinard") == "Claude Pinard"


def test_display_name_keeps_accents():
    assert display_name("Ericka Alnéus") == "Ericka Alnéus"


def test_honorific_and_accent_variants_share_one_key():
    key = normalized_name("Ericka Alneus")
    assert normalized_name("Ericka Alnéus") == key
    assert normalized_name("Mme Ericka Alneus") == key
    assert normalized_name("  Ericka   Alnéus  ") == key


def test_different_people_do_not_share_a_key():
    assert normalized_name("Claude Pinard") != normalized_name("Marie Plourde")


def test_source_typo_matches_the_correct_official():
    roster = [
        normalized_name("Julien Hénault-Ratelle"),
        normalized_name("Claude Pinard"),
        normalized_name("Marie Plourde"),
    ]
    typo = normalized_name("Julien Hénault-Ratellte")
    assert closest_match(typo, roster) == normalized_name("Julien Hénault-Ratelle")


def test_distinct_names_are_not_merged():
    roster = [normalized_name("Claude Pinard"), normalized_name("Marie Plourde")]
    assert closest_match(normalized_name("Aref Salem"), roster) is None
    # Shared surnames must stay distinct.
    assert closest_match(normalized_name("Alan DeSousa"), roster) is None


def test_exact_name_finds_itself():
    roster = [normalized_name("Aref Salem")]
    assert closest_match(normalized_name("Aref Salem"), roster) == "aref salem"
