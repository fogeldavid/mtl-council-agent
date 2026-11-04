"""Offline map coverage, identity safety and Streamlit preview interactions."""

from __future__ import annotations

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
        {"name": "No district", "borough": "Le Plateau-Mont-Royal", "district": None},
    ]
    matched = district_map.representatives(properties, members)
    assert [m["name"] for m in matched] == ["Right member"]


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
    assert all("fill" not in f["properties"] for f in district_map.boundaries()["features"])


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
    at.selectbox[0].select("Tétreaultville · Mercier–Hochelaga-Maisonneuve").run()
    assert not at.exception
    assert at.selectbox[0].value == "071"
    assert any("Hénault-Ratelle" in m.value for m in at.markdown)
    at.checkbox[0].uncheck().run()
    assert not at.exception


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
