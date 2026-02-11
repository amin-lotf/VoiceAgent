import streamlit as st

from voice_agent.frontend.streamlit_app import get_api, ensure_state
from voice_agent.frontend.ui.layout import hide_sidebar_nav, page_frame

st.set_page_config(page_title="Home", layout="wide")


api = get_api()
page_frame("Home", key_prefix="home")


# ----------------------------
# Main
# ----------------------------
s = ensure_state()