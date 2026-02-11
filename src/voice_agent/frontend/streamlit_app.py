import uuid
import streamlit as st
from voice_agent.frontend.api_clinet import ApiClient, SessionView

st.set_page_config(page_title="Voice Agent", page_icon="🎤", layout="centered")


# ----------------------------
# Session state
# ----------------------------
if "api_base_url" not in st.session_state:
    st.session_state.api_base_url = "http://localhost:8000"

if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex

if "server" not in st.session_state:
    st.session_state.server = None  # type: ignore

@st.cache_resource
def get_api() -> ApiClient:
    return ApiClient(st.session_state.api_base_url)




def _refresh_state() -> SessionView:
    api = get_api()
    s = api.get_state(session_id=st.session_state.session_id)
    st.session_state.server = s
    return s


def ensure_state() -> SessionView:
    s = st.session_state.server
    if s is None:
        return _refresh_state()
    return s


def main() -> None:
    st.set_page_config(page_title="Voice Agent", page_icon="🎤", layout="centered")
    st.switch_page("pages/0_home.py")

if __name__ == "__main__":
    main()