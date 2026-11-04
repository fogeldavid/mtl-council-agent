"""Clickable official district boundaries with attributed council voting records."""

from __future__ import annotations

import httpx
import pydeck as pdk
import streamlit as st

from mtl_council_agent.app import address_lookup, district_map, queries
from mtl_council_agent.app.common import (
    PAGES,
    database_configured,
    display_number,
    fmt_date,
    masthead,
    md_text,
    record_title,
    run,
)
from mtl_council_agent.app.i18n import t

SELECTION_KEY = "district_code"
SAVED_SELECTION_KEY = "district_code_saved"
CHART_KEY = "district_polygons"


def _on_map_select() -> None:
    code = district_map.selected_code(
        st.session_state.get(CHART_KEY, {}), set(district_map.district_properties()),
    )
    if code:
        st.session_state[SELECTION_KEY] = code


def _choose_address() -> None:
    results = st.session_state.get("district_address_results", [])
    index = st.session_state.get("district_address_choice", 0)
    if results and 0 <= index < len(results):
        code = results[index]["code"]
        st.session_state[SELECTION_KEY] = code
        st.session_state["district_address_selected"] = code
        st.session_state.pop("district_address_results", None)


def _find_district() -> None:
    st.subheader(t("find.title"))
    st.caption(t("find.french"))
    st.caption(t("find.privacy"))
    with st.form("find_district", clear_on_submit=True):
        address = st.text_input(t("find.address"), max_chars=200, help=t("find.hint"))
        submitted = st.form_submit_button(t("find.submit"))
    if submitted:
        st.session_state.pop("district_address_results", None)
        st.session_state.pop("district_address_selected", None)
        st.session_state.pop("district_address_choice", None)
        if not address_lookup.valid_address(address):
            st.warning(t("find.invalid"))
        else:
            try:
                results = address_lookup.lookup(address)
            except (ValueError, httpx.HTTPError):
                st.warning(t("find.error"))
            else:
                st.session_state["district_address_results"] = results
                if not results:
                    st.info(t("find.none"))
    results = st.session_state.get("district_address_results", [])
    if results:
        st.selectbox(t("find.confirm"), range(len(results)), key="district_address_choice",
                     format_func=lambda i: results[i]["title"])
        st.button(t("find.select"), on_click=_choose_address)
    code = st.session_state.get("district_address_selected")
    if code and code == st.session_state.get(SELECTION_KEY):
        name = district_map.district_properties()[code]["NOM_DISTRICT"]
        st.success(t("find.success", district=name))
    st.markdown(f"[{t('find.source')}]({address_lookup.SOURCE})")


def _votes(member: dict) -> None:
    rows = run(queries.district_recorded_votes, member["id"])
    if not rows:
        st.caption(t("districts.no_votes"))
        return
    st.caption(t("districts.vote_note"))
    for row in rows:
        st.markdown(f"**{t('pos.' + row['position'])}** · {fmt_date(row['meeting_date'])}")
        st.write(md_text(record_title(row["title"])))
        number = display_number(row["item_number"], row["section"])
        if row["section"] == "agglomeration_orientation":
            st.caption(t("orientation"))
        if st.button(t("search.open", number=number),
                     key=f"district_item_{member['id']}_{row['id']}", type="tertiary"):
            st.switch_page(PAGES["updates"], query_params={"item": row["id"]})
        if row["source_url"]:
            st.link_button(t("districts.minutes"), row["source_url"])
        else:
            st.caption(t("districts.no_source"))
        st.divider()
    st.page_link(
        PAGES["councillors"], label=t("districts.profile"),
        query_params={"id": member["id"]},
    )


def render() -> None:
    masthead()
    st.title(t("districts.title"))
    st.write(t("districts.subtitle"))
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
    if st.session_state.get(SELECTION_KEY) not in properties:
        # Streamlit drops a widget's value on leaving the page, so restore the plain
        # copy. Otherwise start on the official Mile-End code, also in the roster.
        saved = st.session_state.get(SAVED_SELECTION_KEY)
        st.session_state[SELECTION_KEY] = saved if saved in properties else "111"
    selected = st.selectbox(
        t("districts.choose"), codes, key=SELECTION_KEY,
        format_func=lambda code: (
            f"{properties[code]['NOM_DISTRICT']} · {properties[code]['NOM_ARR']}"
        ),
    )
    st.session_state[SAVED_SELECTION_KEY] = selected
    map_column, details = st.columns([1.65, 1], gap="large")
    with map_column:
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
        st.pydeck_chart(
            deck, height=600, key=CHART_KEY, on_select=_on_map_select,
            selection_mode="single-object",
        )
        _find_district()
        st.caption(t("districts.map_help"))
        st.caption(t("districts.attribution"))
        st.link_button(t("districts.boundaries"), district_map.BOUNDARY_SOURCE)
    with details:
        district = properties[selected]
        st.subheader(district["NOM_DISTRICT"])
        st.caption(district["NOM_ARR"])
        matched = district_map.representatives(district, members)
        if not matched:
            st.info(t("districts.no_representative"))
        for member in matched:
            st.markdown(f"### {member['name']}")
            st.write(member["party"] or "—")
            st.caption(t("role." + member["role"]))
            if not member.get("district"):
                st.caption(t("districts.borough_wide"))
            if connected:
                st.metric(t("stat.votes"), member["recorded_votes"])
                _votes(member)
        st.link_button(t("districts.roster_source"), snapshot["source_url"])
        if not connected:
            st.caption(t("districts.roster_date", date=snapshot["retrieved_on"]))
    st.info(t("districts.map_note"))
