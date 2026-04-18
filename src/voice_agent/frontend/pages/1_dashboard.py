from __future__ import annotations

import importlib
from datetime import datetime
from typing import TYPE_CHECKING

import streamlit as st

import voice_agent.frontend.api_clinet as api_client_module
from voice_agent.frontend.dashboard_state import (
    get_call_status,
    normalize_selected_call_id,
)
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


def _format_delay(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.3f}s"


def _format_tokens(value: int | None) -> str:
    if value is None:
        return "-"
    return f"{value:,}"


def _call_label(call: CallSummaryView) -> str:
    status = get_call_status(final_status=call.final_status, ended_at=call.ended_at)
    return f"{call.call_id} | {_format_timestamp(call.started_at)} | {status}"


def _render_detail(call: CallDetailView) -> None:
    st.title("Calls Dashboard")

    cols = st.columns(3)
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
        st.caption("Status")
        st.write(get_call_status(final_status=call.final_status, ended_at=call.ended_at))
        st.caption("Turn Count")
        st.write(len(call.turns))

    with cols[2]:
        st.caption("Total Tokens")
        st.write(_format_tokens(call.total_tokens))
        st.caption("Avg Total Delay")
        st.write(_format_delay(call.avg_total_delay_s))
        st.caption("Avg First Token Delay")
        st.write(_format_delay(call.avg_first_token_delay_s))

    st.divider()
    st.subheader("Conversation")

    if not call.turns:
        st.info("No saved turns for this call yet.")
        return

    for turn in call.turns:
        message_role = "assistant" if turn.role == "assistant" else "user"
        with st.chat_message(message_role):
            content_col, meta_col = st.columns([5, 2])
            with content_col:
                st.markdown(turn.content)
            with meta_col:
                st.caption(f"Time: {_format_timestamp(turn.created_at)}")
                st.caption(f"Tokens: {_format_tokens(turn.total_tokens)}")
                st.caption(f"Delay: {_format_delay(turn.total_delay_s)}")
                st.caption(f"1st token: {_format_delay(turn.first_token_delay_s)}")


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

    st.session_state["dashboard_selected_call_id"] = normalize_selected_call_id(
        call_ids,
        st.session_state.get("dashboard_selected_call_id"),
    )

    with st.sidebar:
        st.radio(
            "Call List",
            options=call_ids,
            key="dashboard_selected_call_id",
            format_func=lambda call_id: labels[call_id],
        )

    selected_call_id = st.session_state["dashboard_selected_call_id"]

    try:
        selected_call = api.get_call(call_id=selected_call_id)
    except ApiError as exc:
        st.title("Calls Dashboard")
        st.error(str(exc))
        return

    _render_detail(selected_call)


main()
