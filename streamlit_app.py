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
    masthead,
    setup_page,
)
from mtl_council_agent.app.i18n import t  # noqa: E402
from mtl_council_agent.app.views import (  # noqa: E402
    about,
    councillors,
    decisions,
    districts,
    home,
    landing,
    meetings,
)

st.set_page_config(page_title="The Montréal Record", layout="wide")
setup_page()



def _moved_to_decisions() -> None:
    """The newsfeed and search pages became Decisions; keep their old links working."""
    st.switch_page(PAGES["decisions"], query_params=dict(st.query_params))


PAGES.update(
    landing=st.Page(landing.render, title="The Montréal Record", default=True),
    decisions=st.Page(
        database_view(decisions.render), title=t("nav.decisions"), url_path="decisions",
    ),
    districts=st.Page(districts.render, title=t("nav.districts"), url_path="districts"),
    ask=st.Page(database_view(home.render), title=t("nav.ask"), url_path="ask"),
    meetings=st.Page(database_view(meetings.render), title=t("nav.meetings"), url_path="meetings"),
    councillors=st.Page(
        database_view(councillors.render), title=t("nav.councillors"), url_path="councillors",
    ),
    about=st.Page(about.render, title=t("nav.about"), url_path="about"),
    updates=st.Page(_moved_to_decisions, title=t("nav.decisions"), url_path="updates"),
    search=st.Page(_moved_to_decisions, title=t("nav.decisions"), url_path="search"),
)
page = st.navigation(list(PAGES.values()), position="hidden")
page_key = next(key for key, candidate in PAGES.items() if candidate.url_path == page.url_path)
masthead()
# The landing page's four sections already do the nav bar's job.
if page_key != "landing":
    navigation.render(page_key)
page.run()
