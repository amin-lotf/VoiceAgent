import uuid
import streamlit as st

from voice_agent.frontend.api_client import ApiClient, SessionView
from voice_agent.frontend.settings import BASE_URL

st.set_page_config(page_title="Voice Agent", page_icon="🎤", layout="centered")

def init_session_state() -> None:
    st.session_state.setdefault("session_id", uuid.uuid4().hex)
    st.session_state.setdefault("server", None)




@st.cache_resource
def get_api() -> ApiClient:
    return ApiClient(BASE_URL)




def _refresh_state() -> SessionView:
    api = get_api()
    s = api.get_state(session_id=st.session_state.session_id)
    st.session_state.server = s
    return s


def ensure_state() -> SessionView:
    s = st.session_state.get("server")
    if s is None:
        return _refresh_state()
    return s


def main() -> None:
    init_session_state()
    st.set_page_config(page_title="Voice Agent", page_icon="🎤", layout="centered")
    st.switch_page("pages/0_home.py")

if __name__ == "__main__":
    main()