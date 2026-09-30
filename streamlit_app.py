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

from mtl_council_agent.app.common import PAGES, setup_page  # noqa: E402
from mtl_council_agent.app.i18n import t  # noqa: E402
from mtl_council_agent.app.views import about, councillors, home, meetings, search  # noqa: E402

st.set_page_config(page_title="Council Record Montreal", layout="wide")
st.logo(str(Path(__file__).parent / "src/mtl_council_agent/app/wordmark.svg"), size="large")
setup_page()

PAGES.update(
    ask=st.Page(home.render, title=t("nav.ask"), url_path="ask", default=True),
    search=st.Page(search.render, title=t("nav.search"), url_path="search"),
    meetings=st.Page(meetings.render, title=t("nav.meetings"), url_path="meetings"),
    councillors=st.Page(councillors.render, title=t("nav.councillors"), url_path="councillors"),
    about=st.Page(about.render, title=t("nav.about"), url_path="about"),
)
st.navigation(list(PAGES.values()), position="top").run()
