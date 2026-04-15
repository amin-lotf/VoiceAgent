from __future__ import annotations

import importlib
from datetime import datetime
from typing import TYPE_CHECKING

import streamlit as st

import voice_agent.frontend.api_clinet as api_client_module
from voice_agent.frontend.settings import BASE_URL

api_client_module = importlib.reload(api_client_module)
ApiClient = api_client_module.ApiClient
ApiError = api_client_module.ApiError

if TYPE_CHECKING:
    from voice_agent.frontend.api_clinet import CallDetailView, CallSummaryView


def get_api() -> ApiClient:
    return ApiClient(BASE_URL)


def _format_timestamp(value: str | None) -> str:
    if not value:
        return "-"

    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


def _format_duration(value: int | None) -> str:
    if value is None:
        return "-"

    minutes, seconds = divmod(value, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _call_label(call: CallSummaryView) -> str:
    status = call.final_status or "active"
    return f"{call.call_id} | {_format_timestamp(call.started_at)} | {status}"


def _render_detail(call: CallDetailView) -> None:
    st.title("Calls Dashboard")

    cols = st.columns(2)
    with cols[0]:
        st.caption("Call ID")
        st.code(call.call_id)
        st.caption("Started At")
        st.write(_format_timestamp(call.started_at))
        st.caption("Ended At")
        st.write(_format_timestamp(call.ended_at))

    with cols[1]:
        st.caption("Duration")
        st.write(_format_duration(call.duration_seconds))
        st.caption("Final Status")
        st.write(call.final_status or "-")
        st.caption("Turn Count")
        st.write(len(call.turns))

    st.divider()
    st.subheader("Conversation")

    if not call.turns:
        st.info("No saved turns for this call yet.")
        return

    for turn in call.turns:
        message_role = "assistant" if turn.role == "assistant" else "user"
        with st.chat_message(message_role):
            st.markdown(turn.content)
            if turn.created_at:
                st.caption(_format_timestamp(turn.created_at))


def main() -> None:
    api = get_api()

    with st.sidebar:
        st.subheader("Navigation")
        if st.button("Open Live Tester", use_container_width=True):
            st.switch_page("pages/0_home.py")

        st.divider()
        st.subheader("Saved Calls")
        if st.button("Refresh Calls", use_container_width=True):
            st.rerun()

    try:
        calls = api.list_calls(limit=100)
    except ApiError as exc:
        st.title("Calls Dashboard")
        st.error(str(exc))
        return

    if not calls:
        st.title("Calls Dashboard")
        st.info("No saved calls yet.")
        return

    call_ids = [call.call_id for call in calls]
    labels = {call.call_id: _call_label(call) for call in calls}

    default_call_id = st.session_state.get("dashboard_selected_call_id")
    if default_call_id not in call_ids:
        default_call_id = call_ids[0]

    with st.sidebar:
        selected_call_id = st.radio(
            "Call List",
            options=call_ids,
            index=call_ids.index(default_call_id),
            format_func=lambda call_id: labels[call_id],
        )

    st.session_state["dashboard_selected_call_id"] = selected_call_id

    try:
        selected_call = api.get_call(call_id=selected_call_id)
    except ApiError as exc:
        st.title("Calls Dashboard")
        st.error(str(exc))
        return

    _render_detail(selected_call)


main()
