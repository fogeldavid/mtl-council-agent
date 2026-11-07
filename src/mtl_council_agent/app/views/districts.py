"""Find your district by name, address or map, and who represents it."""

from __future__ import annotations

import httpx
import pydeck as pdk
import streamlit as st

from mtl_council_agent.app import address_lookup, district_map, queries
from mtl_council_agent.app.common import PAGES, database_configured, run
from mtl_council_agent.app.i18n import t

SELECTION_KEY = "district_code"
SAVED_SELECTION_KEY = "district_code_saved"
# Set by an address search, which runs after the dropdown is drawn; Streamlit only
# lets a widget's value change before then, so it's applied on the next run.
PENDING_SELECTION_KEY = "district_code_pending"
CHART_KEY = "district_polygons"


def _on_map_select() -> None:
    code = district_map.selected_code(
        st.session_state.get(CHART_KEY, {}), set(district_map.district_properties()),
    )
    if code:
        st.session_state[SELECTION_KEY] = code
        st.session_state.pop("district_address_selected", None)


def _choose_address() -> None:
    results = st.session_state.get("district_address_results", [])
    index = st.session_state.get("district_address_choice", 0)
    if results and 0 <= index < len(results):
        code = results[index]["code"]
        st.session_state[SELECTION_KEY] = code
        st.session_state["district_address_selected"] = code
        st.session_state.pop("district_address_results", None)


def _heading(properties: dict) -> str:
    return f"{properties['NOM_DISTRICT']}, {properties['NOM_ARR']}"


def _search_address(address: str) -> None:
    for key in ("district_address_results", "district_address_selected",
                "district_address_choice"):
        st.session_state.pop(key, None)
    if not address_lookup.valid_address(address):
        st.warning(t("find.invalid"))
        return
    try:
        with st.spinner(t("find.searching")):
            results = address_lookup.lookup(address)
    except address_lookup.NumberNotFound:
        st.warning(t("find.no_number"))
        return
    except (ValueError, httpx.HTTPError):
        st.warning(t("find.error"))
        return
    if not results:
        st.info(t("find.none"))
    elif len({result["code"] for result in results}) == 1:
        # Every match is in one district, so there's nothing left to ask.
        code = results[0]["code"]
        st.session_state[PENDING_SELECTION_KEY] = code
        st.session_state["district_address_selected"] = code
        st.rerun()
    else:
        st.session_state["district_address_results"] = results


def _find_district() -> None:
    with st.form("find_district", border=False):
        box, button = st.columns([4, 1], vertical_alignment="bottom")
        address = box.text_input(
            t("find.title"), placeholder=t("find.hint"), help=t("find.privacy"),
            key="district_address_text",
        )
        submitted = button.form_submit_button(t("find.submit"), width="stretch")
    if submitted:
        _search_address(address)
    results = st.session_state.get("district_address_results", [])
    if results:
        st.selectbox(t("find.confirm"), range(len(results)), key="district_address_choice",
                     format_func=lambda i: results[i]["title"])
        st.button(t("find.select"), on_click=_choose_address)
    code = st.session_state.get("district_address_selected")
    if code and code == st.session_state.get(SELECTION_KEY):
        st.success(t("find.success", district=_heading(district_map.district_properties()[code])))


def _representatives(district: dict, members: list[dict], connected: bool) -> None:
    st.subheader(_heading(district))
    matched = district_map.representatives(district, members)
    if not matched:
        st.info(t("districts.no_representative"))
        return
    st.markdown(
        f'<div class="people-label">{t("districts.representatives")}</div>',
        unsafe_allow_html=True,
    )
    for member in matched:
        role = t(
            "districts.role_district" if member.get("district") else "districts.role_borough",
            role=t("role." + member["role"]), party=member["party"] or "—",
        )
        with st.container(key=f"district-people-{member.get('id') or member['name']}"):
            st.caption(role)
            if connected:
                st.page_link(
                    PAGES["councillors"], label=t("districts.open", name=member["name"]),
                    query_params={"id": member["id"]},
                )
            else:
                st.markdown(f"**{member['name']}**")


def render() -> None:
    st.title(t("districts.title"))
    connected = database_configured()
    snapshot = district_map.roster_snapshot()
    if connected:
        members = run(queries.councillors)
    else:
        members = [
            {**member, "name": f"{member['first_name']} {member['last_name']}"}
            for member in snapshot["members"]
        ]
        st.info(t("districts.preview"))
    properties = district_map.district_properties()
    codes = sorted(properties, key=lambda code: (
        properties[code]["NOM_ARR"], properties[code]["NOM_DISTRICT"],
    ))
    pending = st.session_state.pop(PENDING_SELECTION_KEY, None)
    if pending in properties:
        st.session_state[SELECTION_KEY] = pending
    elif st.session_state.get(SELECTION_KEY) not in properties:
        # Streamlit drops a widget's value on leaving the page, so restore the plain
        # copy. Otherwise start on the official Mile-End code, also in the roster.
        saved = st.session_state.get(SAVED_SELECTION_KEY)
        st.session_state[SELECTION_KEY] = saved if saved in properties else "111"
    pick, find = st.columns(2, gap="medium")
    selected = pick.selectbox(
        t("districts.choose"), codes, key=SELECTION_KEY,
        format_func=lambda code: (
            f"{properties[code]['NOM_ARR']}: {properties[code]['NOM_DISTRICT']}"
        ),
    )
    st.session_state[SAVED_SELECTION_KEY] = selected
    with find:
        _find_district()
    map_column, details = st.columns([1.65, 1], gap="large")
    with map_column:
        chart = st.container()
        basemap = st.checkbox(t("districts.basemap"), value=True)
        deck = pdk.Deck(
            layers=[pdk.Layer(
                "GeoJsonLayer", district_map.map_geojson(selected),
                id=district_map.MAP_LAYER_ID, pickable=True, auto_highlight=True,
                filled=True, stroked=True, get_fill_color="properties.fill",
                get_line_color=[52, 93, 80, 210], line_width_min_pixels=1,
            )],
            initial_view_state=pdk.ViewState(
                latitude=45.53, longitude=-73.69, zoom=9.7, pitch=0,
            ),
            map_style="light" if basemap else None,
            map_provider="carto" if basemap else None,
            tooltip={"text": "{NOM_DISTRICT}\n{NOM_ARR}"},
        )
        chart.pydeck_chart(
            deck, height=520, key=CHART_KEY, on_select=_on_map_select,
            selection_mode="single-object",
        )
        st.caption(
            f"{t('districts.map_help')} {t('districts.attribution')} "
            f"[{t('districts.boundaries')}]({district_map.BOUNDARY_SOURCE}) · "
            f"[{t('find.source')}]({address_lookup.SOURCE})"
        )
    with details:
        _representatives(properties[selected], members, connected)
        st.caption(f"[{t('districts.roster_source')}]({snapshot['source_url']})")
        if not connected:
            st.caption(t("districts.roster_date", date=snapshot["retrieved_on"]))
