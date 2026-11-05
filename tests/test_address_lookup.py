"""Address matching must never substitute a town/street centroid for a home."""
from unittest.mock import patch

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from mtl_council_agent.app import address_lookup as lookup


def test_city_hall_is_in_saint_jacques_and_outside_city_is_unmatched():
    code = lookup.district_at(-73.55411106835, 45.50883584861)
    from mtl_council_agent.app.district_map import district_properties
    assert district_properties()[code]["NOM_DISTRICT"] == "Saint-Jacques"
    assert lookup.district_at(-71.2, 46.8) is None


def test_polygons_respect_holes_multipart_and_ambiguous_edges():
    outer = [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]
    hole = [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]
    feature = {"properties": {"CODE_DISTRICT": "a"},
               "geometry": {"type": "MultiPolygon", "coordinates": [[outer, hole]]}}
    with patch.object(lookup, "boundaries", return_value={"features": [feature]}):
        assert lookup.district_at(3, 3) == "a"
        assert lookup.district_at(1.5, 1.5) is None
    other = {**feature, "properties": {"CODE_DISTRICT": "b"}}
    with patch.object(lookup, "boundaries", return_value={"features": [feature, other]}):
        assert lookup.district_at(3, 3) is None


@pytest.mark.parametrize("text", ["H2Y 1C6", "H2Y", "", "Montreal"])
def test_postal_codes_and_incomplete_queries_never_call_provider(text):
    with patch.object(lookup, "_fetch") as fetch:
        with pytest.raises(ValueError):
            lookup.lookup(text)
        fetch.assert_not_called()


def _response(features, **extra):
    return httpx.Response(200, json={"features": features, **extra},
                          request=httpx.Request("GET", lookup.ENDPOINT))


def test_direction_is_exact_and_apartments_deduplicated():
    def feature(title):
        return {"attributes": {"AdresseFormatee": title},
                "geometry": {"x": -73.55411106835, "y": 45.50883584861}}
    features = [feature("2-275 rue Notre-Dame Est, Montréal H2Y1C6"),
                feature("275 rue Notre-Dame Est, Montréal H2Y1C6"),
                feature("275 rue Notre-Dame Ouest, Montréal H2Y1T8")]
    with patch.object(lookup, "_fetch", return_value=_response(features)) as fetch:
        result = lookup.lookup("275 rue Notre-Dame Est")
        assert len(result) == 1
        assert result[0]["title"] == "275 rue Notre-Dame Est, Montréal H2Y1C6"
        assert "NoCivq = 275" in fetch.call_args.args[0]["where"]


def test_truncated_results_and_provider_errors_do_not_select_a_district():
    with patch.object(lookup, "_fetch", return_value=_response([], exceededTransferLimit=True)):
        with pytest.raises(ValueError):
            lookup.lookup("275 rue Notre-Dame")


def _feature(title):
    return {"attributes": {"AdresseFormatee": title},
            "geometry": {"x": -73.55411106835, "y": 45.50883584861}}


@pytest.mark.parametrize(("typed", "stored"), [
    ("4800 chemin de la Côte-des-Neiges", "4800 chemin de la Côte-des-Neiges, Montréal H3V1G2"),
    ("4800 chemin de la Cote-des-Neiges", "4800 chemin de la Côte-des-Neiges, Montréal H3V1G2"),
    ("3500 St-Laurent", "3500 boulevard Saint-Laurent, Montréal H2X2V1"),
    ("3500 boul. St Laurent", "3500 boulevard Saint-Laurent, Montréal H2X2V1"),
    ("3500, blvd Saint-Laurent", "3500 boulevard Saint-Laurent, Montréal H2X2V1"),
    ("1 ch Cote Ste-Catherine", "1 chemin de la Côte-Sainte-Catherine, Montréal H2V1Z8"),
    ("5000 ave Sherbrooke E", "5000 rue Sherbrooke Est, Montréal H1V1A1"),
    ("275 Notre-Dame West", "275 rue Notre-Dame Ouest, Montréal H2Y1T8"),
    ("12 rue O'Brien", "12 rue O'Brien, Montréal H4N1Y1"),
    ("275 Notre Dame East, Montreal, QC H2Y 1C6", "275 rue Notre-Dame Est, Montréal H2Y1C6"),
    ("275 Notre Dame Est Montreal Quebec Canada", "275 rue Notre-Dame Est, Montréal H2Y1C6"),
    ("4800 Cote des Neiges, Montréal, QC", "4800 chemin de la Côte-des-Neiges, Montréal H3V1G2"),
    ("4800 Cote-des-Neiges H3V", "4800 chemin de la Côte-des-Neiges, Montréal H3V1G2"),
    ("275A Notre-Dame Est", "275 rue Notre-Dame Est, Montréal H2Y1C6"),
    ("Apt 3, 275 Notre-Dame Est", "275 rue Notre-Dame Est, Montréal H2Y1C6"),
    ("275 Notre-Dame Est, app. 3", "275 rue Notre-Dame Est, Montréal H2Y1C6"),
    ("275 Notre-Dame Est #3", "275 rue Notre-Dame Est, Montréal H2Y1C6"),
    ("3-275 Notre-Dame Est", "275 rue Notre-Dame Est, Montréal H2Y1C6"),
])
def test_common_spellings_find_the_stored_address(typed, stored):
    with patch.object(lookup, "_fetch", return_value=_response([_feature(stored)])) as fetch:
        assert [r["title"] for r in lookup.lookup(typed)] == [stored]
    where = fetch.call_args.args[0]["where"]
    # The service's LIKE is accent-sensitive: a plain COTE finds nothing there.
    assert "COTE" not in where and "CÔTE" not in where
    assert all(ord(c) < 128 for c in where)


def test_the_loose_service_match_is_checked_exactly_afterwards():
    wrong = "4800 rue Cata, Montréal H3V1G2"
    with patch.object(lookup, "_fetch", return_value=_response([_feature(wrong)])):
        assert lookup.lookup("4800 rue Cote") == []


def test_a_large_building_is_not_called_too_broad():
    with patch.object(lookup, "_fetch", return_value=_response([])) as fetch:
        lookup.lookup("1 chemin de la Côte-Sainte-Catherine")
    assert fetch.call_args_list[0].args[0]["resultRecordCount"] == "1000"


def test_a_building_with_many_postal_codes_is_listed_once():
    rows = [_feature(f"1 Place Ville-Marie, Montréal H3B{i}Y{i}") for i in range(1, 5)]
    with patch.object(lookup, "_fetch", return_value=_response(rows)):
        assert len(lookup.lookup("1 Place Ville Marie")) == 1


def test_each_point_is_tested_against_the_boundaries_once():
    rows = [_feature(f"{i}-1 rue Exemple, Montréal H3B1A1") for i in range(50)]
    other = _feature("1 rue Autre, Montréal H3B1A1")
    other["geometry"] = {"x": -73.6, "y": 45.5}
    with patch.object(lookup, "_fetch", return_value=_response([*rows, other])), \
         patch.object(lookup, "district_at", return_value="182") as district_at:
        assert len(lookup.lookup("1 rue Exemple")) == 1
    assert district_at.call_count == 1


def test_a_street_without_that_number_says_so():
    street = _response([_feature("726 avenue Davaar, Montréal H2V3B2")])
    with patch.object(lookup, "_fetch", side_effect=[_response([]), street]):
        with pytest.raises(lookup.NumberNotFound):
            lookup.lookup("530 Davaar")


def test_an_unknown_street_is_not_reported_as_a_missing_number():
    with patch.object(lookup, "_fetch", side_effect=[_response([]), _response([])]):
        assert lookup.lookup("530 Nulle-Part") == []


def test_a_failed_street_check_falls_back_to_the_general_message():
    failure = httpx.ConnectError("down")
    with patch.object(lookup, "_fetch", side_effect=[_response([]), failure]):
        assert lookup.lookup("530 Davaar") == []


def test_an_address_outside_the_districts_is_not_a_missing_number():
    outside = {"attributes": {"AdresseFormatee": "1 rue Exemple, Westmount H3Z1A1"},
               "geometry": {"x": -71.2, "y": 46.8}}
    with patch.object(lookup, "_fetch", return_value=_response([outside])) as fetch:
        assert lookup.lookup("1 rue Exemple") == []
    assert fetch.call_count == 1


def test_the_provider_is_called_over_http2():
    with patch.object(lookup.httpx, "Client") as client:
        client.return_value.__enter__.return_value.get.return_value = _response([])
        lookup.lookup("275 rue Notre-Dame")
    assert client.call_args.kwargs["http2"] is True


def _preview(results):
    from unittest.mock import patch

    from mtl_council_agent.app import address_lookup as lookup
    from mtl_council_agent.app.views import districts
    with patch.object(districts, "database_configured", return_value=False), \
         patch.object(lookup, "lookup", return_value=results):
        districts.render()


def _search(results, typed="275 rue Notre-Dame Est"):
    at = AppTest.from_function(_preview, args=(results,), default_timeout=30).run()
    assert not at.exception
    at.text_input[0].set_value(typed)
    next(b for b in at.button if b.label == "Find").click().run()
    assert not at.exception
    return at


def test_one_match_selects_the_district_without_another_click():
    at = _search([{"title": "275 rue Notre-Dame Est, Montréal", "code": "182"}])
    assert at.session_state["district_code"] == "182"
    assert not any(b.label == "Show this district" for b in at.button)
    assert at.success
    assert at.text_input[0].value == "275 rue Notre-Dame Est"  # Kept, to fix a typo.


def test_matches_in_one_district_need_no_choice():
    at = _search([{"title": "275 rue Notre-Dame Est, Montréal", "code": "182"},
                  {"title": "275 rue Notre-Dame Ouest, Montréal", "code": "182"}])
    assert at.session_state["district_code"] == "182"
    assert not any(b.label == "Show this district" for b in at.button)


def test_matches_in_different_districts_ask_which_one():
    at = _search([{"title": "1800 boulevard Saint-Joseph, Lachine", "code": "182"},
                  {"title": "1800 boulevard Saint-Joseph Est, Montréal", "code": "111"}])
    next(b for b in at.button if b.label == "Show this district").click().run()
    assert not at.exception
    assert at.session_state["district_code"] == "182"
    assert at.success


def _preview_raising(error):
    from unittest.mock import patch

    import httpx

    from mtl_council_agent.app import address_lookup as lookup
    from mtl_council_agent.app.views import districts
    exception = {"number": lookup.NumberNotFound, "down": httpx.ConnectError}[error]
    with patch.object(districts, "database_configured", return_value=False), \
         patch.object(lookup, "lookup", side_effect=exception("x")):
        districts.render()


@pytest.mark.parametrize(("error", "message"), [
    ("number", "not that civic number"), ("down", "unavailable"),
])
def test_each_failure_gets_its_own_message(error, message):
    at = AppTest.from_function(_preview_raising, args=(error,), default_timeout=30).run()
    at.text_input[0].set_value("530 Davaar")
    next(b for b in at.button if b.label == "Find").click().run()
    assert not at.exception
    assert any(message in w.value for w in at.warning)
