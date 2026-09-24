"""Official-name identity, from real spellings found in the minutes."""

from mtl_council_agent.names import (
    closest_match,
    display_name,
    matches_roster_entry,
    near_miss,
    normalized_name,
)


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
    match = closest_match(typo, roster)
    assert match is not None
    name, score = match
    assert name == normalized_name("Julien Hénault-Ratelle")
    assert score > 0.95


def test_distinct_names_are_not_merged():
    roster = [normalized_name("Claude Pinard"), normalized_name("Marie Plourde")]
    assert closest_match(normalized_name("Aref Salem"), roster) is None
    # Shared surnames must stay distinct.
    assert closest_match(normalized_name("Alan DeSousa"), roster) is None


def test_people_sharing_a_surname_stay_separate():
    # The threshold has to survive a roster that gains related names.
    roster = [normalized_name("Marie Plourde")]
    assert closest_match(normalized_name("Pierre Plourde"), roster) is None
    assert closest_match(normalized_name("Marie Plourdeau"), roster) is None


def test_exact_name_finds_itself():
    roster = [normalized_name("Aref Salem")]
    assert closest_match(normalized_name("Aref Salem"), roster) == ("aref salem", 1.0)


def test_obvious_typos_still_merge():
    roster = [normalized_name("Marie Plourde")]
    # Trailing character (0.963) and truncation (0.960): same person.
    assert closest_match(normalized_name("Marie Plourdes"), roster) is not None
    assert closest_match(normalized_name("Marie Plourd"), roster) is not None


def test_ambiguous_names_are_flagged_rather_than_merged():
    roster = [normalized_name("Marie Plourde")]
    # "Maria" is a different given name and scores 0.923. Merging would be a
    # silent error, so it is refused and surfaced for a human instead.
    assert closest_match(normalized_name("Maria Plourde"), roster) is None
    assert near_miss(normalized_name("Maria Plourde"), roster) is not None
    # Plainly a different person (0.522): not merged, not flagged.
    assert closest_match(normalized_name("Aref Salem"), roster) is None
    assert near_miss(normalized_name("Aref Salem"), roster) is None


def test_roster_entry_matches_a_shortened_given_name():
    # The roster's "Alba Stella Zuniga Ramos" is "Alba Zuniga Ramos" in the
    # minutes; the similarity score (0.83) is far below the merge threshold.
    key = normalized_name("Alba Zuniga Ramos")
    assert matches_roster_entry(key, "Alba Stella", "Zuniga Ramos")


def test_roster_entry_matches_a_nickname():
    assert matches_roster_entry(normalized_name("Jim Beis"), "Dimitrios (Jim)", "Beis")
    assert matches_roster_entry(
        normalized_name("M. Dimitrios (Jim) Beis"), "Dimitrios (Jim)", "Beis"
    )


def test_roster_entry_needs_both_surname_and_given_name():
    # A shared first name or a surname that merely ends the same way is not
    # the same person: Andrée Hénault is not Julien Hénault-Ratelle.
    andree = normalized_name("Andrée Hénault")
    julien = normalized_name("Julien Hénault-Ratelle")
    assert not matches_roster_entry(andree, "Julien", "Hénault-Ratelle")
    assert not matches_roster_entry(julien, "Andrée", "Hénault")
    assert not matches_roster_entry(normalized_name("Alba Autre"), "Alba Stella", "Zuniga Ramos")
