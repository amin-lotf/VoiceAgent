from __future__ import annotations
import streamlit as st


def hide_sidebar_nav() -> None:
    st.markdown(
        "<style>[data-testid='stSidebarNav']{display:none;}</style>",
        unsafe_allow_html=True,
    )

def top_bar(key_prefix: str) -> None:
    cols = st.columns([1])
    with cols[0]:
        if st.button(
            "Home",
            use_container_width=True,
            key=f"{key_prefix}_nav_home",
        ):
            st.switch_page("pages/0_home.py")


def page_frame(title: str, *, key_prefix: str) -> None:
    top_bar(key_prefix)
    st.divider()
    st.title(title)
