from __future__ import annotations

import html
import importlib
from typing import TYPE_CHECKING

import streamlit as st

st.set_page_config(page_title="Calls Dashboard", layout="wide")

import voice_agent.frontend.api_client as api_client_module
from voice_agent.frontend.dashboard_state import (
    format_in_default_tz,
    get_call_status,
    normalize_selected_call_id,
)
from voice_agent.frontend.settings import BASE_URL

api_client_module = importlib.reload(api_client_module)
ApiClient = api_client_module.ApiClient
ApiError = api_client_module.ApiError

if TYPE_CHECKING:
    from voice_agent.frontend.api_client import (
        CallDetailView,
        CallSummaryView,
        ScheduledAppointmentView,
    )


def get_api() -> ApiClient:
    return ApiClient(BASE_URL)


def _format_timestamp(value: str | None) -> str:
    return format_in_default_tz(value, fmt="%Y-%m-%d %H:%M:%S")


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


def _format_scheduled_date(value: str | None) -> str:
    return format_in_default_tz(value, fmt="%b %d, %Y at %I:%M %p")


def _escape(value: str | None) -> str:
    text = (value or "").strip() or "-"
    return html.escape(text)


def _status_badge(status: str) -> str:
    normalized = (status or "unknown").strip().lower().replace("_", "-")
    label = (status or "unknown").replace("_", " ").title()
    return f"<span class='status-badge status-{html.escape(normalized)}'>{html.escape(label)}</span>"


def _info_item(label: str, value: str) -> str:
    return (
        "<div class='info-item'>"
        f"<div class='info-label'>{html.escape(label)}</div>"
        f"<div class='info-value'>{value}</div>"
        "</div>"
    )


def _notes_markup(notes: list[str]) -> str:
    items = [note.strip() for note in notes if note and note.strip()]
    if not items:
        return "<div class='notes-empty'>No notes recorded.</div>"
    rows = "".join(f"<li>{html.escape(note)}</li>" for note in items)
    return f"<ul class='notes-list'>{rows}</ul>"


def _render_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
        }
        .page-title {
            font-size: 2rem;
            font-weight: 700;
            color: #f3f4f6;
            margin-bottom: 0.25rem;
        }
        .page-subtitle {
            color: #9ca3af;
            margin-bottom: 1.5rem;
        }
        .section-label {
            margin: 1.5rem 0 0.75rem 0;
            font-size: 0.8rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #93c5fd;
        }
        .detail-card {
            border: 1px solid rgba(148, 163, 184, 0.22);
            border-radius: 8px;
            padding: 1.25rem;
            background: linear-gradient(180deg, rgba(15, 23, 42, 0.82), rgba(15, 23, 42, 0.65));
            box-shadow: 0 18px 40px rgba(2, 6, 23, 0.18);
        }
        .card-header {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 1rem;
        }
        .card-title {
            margin: 0;
            font-size: 1.05rem;
            font-weight: 700;
            color: #f8fafc;
        }
        .card-subtitle {
            margin-top: 0.2rem;
            color: #94a3b8;
            font-size: 0.92rem;
            word-break: break-word;
        }
        .status-badge {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 0.35rem 0.7rem;
            border-radius: 999px;
            font-size: 0.76rem;
            font-weight: 700;
            text-transform: uppercase;
            border: 1px solid transparent;
            white-space: nowrap;
        }
        .status-scheduled {
            background: rgba(16, 185, 129, 0.16);
            border-color: rgba(16, 185, 129, 0.34);
            color: #6ee7b7;
        }
        .status-held {
            background: rgba(245, 158, 11, 0.16);
            border-color: rgba(245, 158, 11, 0.34);
            color: #fcd34d;
        }
        .status-completed, .status-active {
            background: rgba(59, 130, 246, 0.16);
            border-color: rgba(96, 165, 250, 0.34);
            color: #93c5fd;
        }
        .status-disconnected {
            background: rgba(244, 63, 94, 0.16);
            border-color: rgba(251, 113, 133, 0.34);
            color: #fda4af;
        }
        .status-unknown {
            background: rgba(148, 163, 184, 0.16);
            border-color: rgba(148, 163, 184, 0.34);
            color: #cbd5e1;
        }
        .info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 0.85rem;
        }
        .info-item {
            padding: 0.9rem 1rem;
            border-radius: 8px;
            background: rgba(30, 41, 59, 0.58);
            border: 1px solid rgba(148, 163, 184, 0.12);
        }
        .info-label {
            font-size: 0.74rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: #94a3b8;
            margin-bottom: 0.35rem;
        }
        .info-value {
            color: #f8fafc;
            font-size: 1rem;
            line-height: 1.5;
            word-break: break-word;
        }
        .notes-block {
            margin-top: 1rem;
            padding: 1rem;
            border-radius: 8px;
            background: rgba(30, 41, 59, 0.58);
            border: 1px solid rgba(148, 163, 184, 0.12);
        }
        .notes-list {
            margin: 0;
            padding-left: 1.2rem;
            color: #e5e7eb;
        }
        .notes-list li + li {
            margin-top: 0.35rem;
        }
        .notes-empty {
            color: #cbd5e1;
        }
        .conversation-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 0.75rem;
        }
        .conversation-count {
            color: #94a3b8;
            font-size: 0.92rem;
        }
        .turn-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 0.75rem;
        }
        .turn-role {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 0.28rem 0.62rem;
            border-radius: 999px;
            font-size: 0.74rem;
            font-weight: 700;
            text-transform: uppercase;
        }
        .turn-role-assistant {
            background: rgba(96, 165, 250, 0.16);
            color: #bfdbfe;
        }
        .turn-role-caller {
            background: rgba(45, 212, 191, 0.16);
            color: #99f6e4;
        }
        .turn-meta {
            color: #94a3b8;
            font-size: 0.86rem;
            text-align: right;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_page_header() -> None:
    st.markdown(
        """
        <div class="page-title">Calls Dashboard</div>
        <div class="page-subtitle">Saved calls, response timings, and scheduled appointments.</div>
        """,
        unsafe_allow_html=True,
    )


def _render_overview(calls: list[CallSummaryView]) -> None:
    statuses = [get_call_status(final_status=call.final_status, ended_at=call.ended_at) for call in calls]
    total_calls = len(calls)
    scheduled_calls = sum(status == "scheduled" for status in statuses)
    active_calls = sum(status == "active" for status in statuses)
    completed_calls = sum(status == "completed" for status in statuses)

    cols = st.columns(4)
    cols[0].metric("Saved Calls", total_calls)
    cols[1].metric("Scheduled", scheduled_calls)
    cols[2].metric("Completed", completed_calls)
    cols[3].metric("Active", active_calls)


def _render_call_information(call: CallDetailView) -> None:
    status = get_call_status(final_status=call.final_status, ended_at=call.ended_at)
    info_grid = "".join(
        [
            _info_item("Call ID", _escape(call.call_id)),
            _info_item("Started At", _escape(_format_timestamp(call.started_at))),
            _info_item("Ended At", _escape(_format_timestamp(call.ended_at))),
            _info_item("Duration", _escape(_format_duration(call.duration_seconds))),
            _info_item("Total Tokens", _escape(_format_tokens(call.total_tokens))),
            _info_item("Avg Total Delay", _escape(_format_delay(call.avg_total_delay_s))),
            _info_item("Avg First Token Delay", _escape(_format_delay(call.avg_first_token_delay_s))),
            _info_item("Turn Count", _escape(str(len(call.turns)))),
        ]
    )
    st.markdown(
        (
            "<div class='section-label'>Call Information</div>"
            "<div class='detail-card'>"
            "<div class='card-header'>"
            "<div>"
            "<div class='card-title'>Selected Call</div>"
            f"<div class='card-subtitle'>{_escape(call.call_id)}</div>"
            "</div>"
            f"{_status_badge(status)}"
            "</div>"
            f"<div class='info-grid'>{info_grid}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _render_scheduled_appointment(appointment: ScheduledAppointmentView) -> None:
    info_grid = "".join(
        [
            _info_item("Name", _escape(appointment.name)),
            _info_item("Phone", _escape(appointment.phone)),
            _info_item("Reason For Visit", _escape(appointment.reason_for_visit)),
            _info_item("Scheduled Date", _escape(_format_scheduled_date(appointment.start_at))),
        ]
    )
    st.markdown(
        (
            "<div class='section-label'>Scheduled Appointment</div>"
            "<div class='detail-card'>"
            "<div class='card-header'>"
            "<div>"
            "<div class='card-title'>Appointment Details</div>"
            "<div class='card-subtitle'>Only scheduled appointments are shown here.</div>"
            "</div>"
            f"{_status_badge(appointment.status or 'scheduled')}"
            "</div>"
            f"<div class='info-grid'>{info_grid}</div>"
            "<div class='notes-block'>"
            "<div class='info-label'>Notes</div>"
            f"{_notes_markup(appointment.notes)}"
            "</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _render_conversation(call: CallDetailView) -> None:
    if not call.turns:
        st.info("No saved turns for this call yet.")
        return

    for turn in call.turns:
        role_label = "Assistant" if turn.role == "assistant" else "Caller"
        role_class = "turn-role-assistant" if turn.role == "assistant" else "turn-role-caller"
        meta_parts = [
            f"Time: {_format_timestamp(turn.created_at)}",
            f"Tokens: {_format_tokens(turn.total_tokens)}",
            f"Delay: {_format_delay(turn.total_delay_s)}",
            f"1st token: {_format_delay(turn.first_token_delay_s)}",
        ]

        with st.container(border=True):
            st.markdown(
                (
                    "<div class='turn-header'>"
                    f"<span class='turn-role {role_class}'>{html.escape(role_label)}</span>"
                    f"<div class='turn-meta'>{html.escape(' | '.join(meta_parts))}</div>"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )
            st.markdown(turn.content or "")


def _render_logs(call: CallDetailView) -> None:
    if not call.logs:
        st.info("No saved logs for this call yet.")
        return

    for entry in call.logs:
        meta_parts = [
            f"Level: {(entry.level or 'info').upper()}",
            f"Time: {_format_timestamp(entry.timestamp)}",
        ]
        if entry.details and entry.details.get("logger"):
            meta_parts.append(f"Logger: {entry.details.get('logger')}")
        if entry.details and entry.details.get("node"):
            meta_parts.append(f"Node: {entry.details.get('node')}")
        if entry.details and entry.details.get("phase"):
            meta_parts.append(f"Phase: {entry.details.get('phase')}")

        with st.container(border=True):
            st.markdown(f"**{entry.message or '-'}**")
            st.caption(" | ".join(meta_parts))


def _render_saved_call_data(call: CallDetailView) -> None:
    st.markdown("<div class='section-label'>Saved Call Data</div>", unsafe_allow_html=True)
    transcript_tab, logs_tab = st.tabs(
        [f"Saved Transcript ({len(call.turns)})", f"Saved Logs ({len(call.logs)})"]
    )

    with transcript_tab:
        with st.container(height=480):
            _render_conversation(call)

    with logs_tab:
        with st.container(height=480):
            _render_logs(call)


def _render_detail(call: CallDetailView) -> None:
    _render_call_information(call)
    if call.scheduled_appointment is not None:
        _render_scheduled_appointment(call.scheduled_appointment)
    _render_saved_call_data(call)


def main() -> None:
    api = get_api()
    _render_styles()
    _render_page_header()

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
        st.error(str(exc))
        return

    _render_overview(calls)

    if not calls:
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
        st.error(str(exc))
        return

    _render_detail(selected_call)


main()
