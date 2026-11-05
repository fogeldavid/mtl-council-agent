"""Offline map coverage, identity safety and Streamlit preview interactions."""

from __future__ import annotations

import json

import pytest
from streamlit.testing.v1 import AppTest

from mtl_council_agent.app import district_map


def test_bundled_boundaries_are_all_58_official_districts():
    features = district_map.boundaries()["features"]
    codes = district_map.district_properties()
    assert len(features) == len(codes) == 58
    assert codes["111"]["NOM_DISTRICT"] == "Mile-End"
    assert {f["geometry"]["type"] for f in features} == {"Polygon", "MultiPolygon"}


def test_roster_match_uses_both_district_and_borough():
    properties = {"NOM_ARR": "Le Plateau-Mont-Royal", "NOM_DISTRICT": "Mile-End"}
    members = [
        {"name": "Right member", "borough": "Le Plateau–Mont–Royal", "district": "Mile-End"},
        {"name": "Wrong borough", "borough": "Ville-Marie", "district": "Mile-End"},
        {"name": "Wrong district", "borough": "Le Plateau-Mont-Royal", "district": "Jeanne-Mance"},
        {"name": "Whole borough", "borough": "Le Plateau-Mont-Royal", "district": None},
    ]
    matched = district_map.representatives(properties, members)
    assert [m["name"] for m in matched] == ["Right member", "Whole borough"]


def test_selection_validates_code_and_layer():
    valid = set(district_map.district_properties())
    event = {"selection": {"objects": {district_map.MAP_LAYER_ID: [
        {"properties": {"CODE_DISTRICT": "111"}},
    ]}}}
    assert district_map.selected_code(event, valid) == "111"
    assert district_map.selected_code(event, {"999"}) is None
    assert district_map.selected_code({"selection": {"objects": {}}}, valid) is None


def test_highlight_does_not_mutate_the_official_boundaries():
    first = district_map.map_geojson("111")
    second = district_map.map_geojson("071")
    for data, code in [(first, "111"), (second, "071")]:
        selected = [f for f in data["features"] if f["properties"]["fill"][-1] == 185]
        assert [f["properties"]["CODE_DISTRICT"] for f in selected] == [code]
    assert all("fill" not in f["properties"]
               for f in district_map.display_boundaries()["features"])


def _rings(feature):
    geometry = feature["geometry"]
    polygons = (geometry["coordinates"] if geometry["type"] == "MultiPolygon"
                else [geometry["coordinates"]])
    return [polygon[0] for polygon in polygons]


def _area(feature):
    return sum(
        abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:], strict=False))) / 2
        for ring in _rings(feature)
    )


def test_map_outlines_stay_close_to_the_official_boundaries():
    official = {f["properties"]["CODE_DISTRICT"]: f for f in district_map.boundaries()["features"]}
    drawn = {f["properties"]["CODE_DISTRICT"]: f
             for f in district_map.display_boundaries()["features"]}
    assert drawn.keys() == official.keys()
    for code, feature in drawn.items():
        assert _area(feature) == pytest.approx(_area(official[code]), rel=0.01), code
        assert feature["properties"]["NOM_DISTRICT"] == official[code]["properties"]["NOM_DISTRICT"]


def test_map_data_stays_small_enough_to_resend():
    # st.pydeck_chart sends all of this each time the map changes.
    assert len(json.dumps(district_map.map_geojson("111"))) < 400_000


def test_address_lookup_still_uses_the_official_boundaries():
    points = sum(len(ring) for f in district_map.boundaries()["features"] for ring in _rings(f))
    assert points > 100_000


def _render_preview():
    from unittest.mock import patch

    from mtl_council_agent.app.views import districts

    with patch.object(districts, "database_configured", return_value=False):
        districts.render()


def test_preview_renders_and_changes_district_without_a_database():
    at = AppTest.from_function(_render_preview, default_timeout=30).run()
    assert not at.exception
    assert at.selectbox[0].value == "111"
    assert any("Map preview" in info.value for info in at.info)
    at.selectbox[0].select("071").run()
    assert not at.exception
    assert at.selectbox[0].value == "071"
    assert any("Hénault-Ratelle" in m.value for m in at.markdown)
    at.checkbox[0].uncheck().run()
    assert not at.exception


def _render_or_leave():
    from unittest.mock import patch

    import streamlit as st

    from mtl_council_agent.app.views import districts

    if st.session_state.get("away"):
        st.write("Another page")
    else:
        with patch.object(districts, "database_configured", return_value=False):
            districts.render()


def test_chosen_district_survives_leaving_the_page():
    from mtl_council_agent.app.views import districts

    at = AppTest.from_function(_render_or_leave, default_timeout=30).run()
    at.selectbox[0].select("071").run()
    at.session_state["away"] = True
    at.run()
    assert districts.SELECTION_KEY not in at.session_state  # What Streamlit does on leaving.
    at.session_state["away"] = False
    at.run()
    assert not at.exception
    assert at.selectbox[0].value == "071"


def test_every_district_has_a_representative():
    members = district_map.roster_snapshot()["members"]
    empty = [p["NOM_DISTRICT"] for p in district_map.district_properties().values()
             if not district_map.representatives(p, members)]
    assert empty == []


def test_whole_borough_members_follow_the_district_councillor():
    members = [
        {"name": "Mayor", "borough": "Anjou", "district": None},
        {"name": "Councillor", "borough": "Anjou", "district": "Est"},
        {"name": "Other district", "borough": "Anjou", "district": "Ouest"},
        {"name": "Other borough", "borough": "Lachine", "district": None},
    ]
    found = district_map.representatives({"NOM_ARR": "Anjou", "NOM_DISTRICT": "Est"}, members)
    assert [m["name"] for m in found] == ["Councillor", "Mayor"]


def test_map_callback_updates_the_dropdown_before_rerender(monkeypatch):
    from mtl_council_agent.app.views import districts

    state = {districts.CHART_KEY: {"selection": {"objects": {
        district_map.MAP_LAYER_ID: [{"properties": {"CODE_DISTRICT": "071"}}],
    }}}}
    monkeypatch.setattr(districts.st, "session_state", state)
    districts._on_map_select()
    assert state[districts.SELECTION_KEY] == "071"


def test_all_named_roster_districts_match_official_boundaries():
    properties = list(district_map.district_properties().values())
    members = district_map.roster_snapshot()["members"]
    for member in members:
        if member.get("district"):
            assert any(district_map.representatives(p, [member]) for p in properties), member
