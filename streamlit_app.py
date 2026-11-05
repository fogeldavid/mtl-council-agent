"""Council Record Montreal: the public web app.

Run locally with `streamlit run streamlit_app.py`. Needs WEB_DATABASE_URL,
the read-only database login, in .env or Streamlit secrets.
"""

import sys
from pathlib import Path

import streamlit as st

# The package lives in src/. Adding it here means the app runs the same way
# locally and on Streamlit Community Cloud, with or without `pip install -e .`.
sys.path.insert(0, str(Path(__file__).parent / "src"))

from mtl_council_agent.app import navigation  # noqa: E402
from mtl_council_agent.app.common import (  # noqa: E402
    PAGES,
    database_view,
    setup_page,
)
from mtl_council_agent.app.i18n import t  # noqa: E402
from mtl_council_agent.app.views import (  # noqa: E402
    about,
    councillors,
    districts,
    home,
    meetings,
    search,
    updates,
)

st.set_page_config(page_title="The Montréal Record", layout="wide")
setup_page()

PAGES.update(
    updates=st.Page(database_view(updates.render), title=t("nav.updates"), default=True),
    districts=st.Page(districts.render, title=t("nav.districts"), url_path="districts"),
    ask=st.Page(database_view(home.render), title=t("nav.ask"), url_path="ask"),
    search=st.Page(database_view(search.render), title=t("nav.search"), url_path="search"),
    meetings=st.Page(database_view(meetings.render), title=t("nav.meetings"), url_path="meetings"),
    councillors=st.Page(
        database_view(councillors.render), title=t("nav.councillors"), url_path="councillors",
    ),
    about=st.Page(about.render, title=t("nav.about"), url_path="about"),
)
page = st.navigation(list(PAGES.values()), position="hidden")
page_key = next(key for key, candidate in PAGES.items() if candidate.url_path == page.url_path)
navigation.render(page_key)
page.run()
