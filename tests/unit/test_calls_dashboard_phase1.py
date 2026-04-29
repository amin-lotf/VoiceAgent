from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from voice_agent.core.api.v1.retell.router import (
    _derive_call_status,
    _derive_disconnect_status,
    _derive_final_status,
    _extract_scheduled_appointment_snapshot,
)
from voice_agent.core.api.v1.calls.router import _to_detail_out, _to_summary_out
from voice_agent.frontend.dashboard_state import (
    format_in_default_tz,
    get_call_status,
    normalize_selected_call_id,
)
from voice_agent.frontend.api_clinet import ApiClient


def test_calls_router_serializes_summary_and_turns() -> None:
    started_at = datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc)
    ended_at = started_at + timedelta(minutes=2, seconds=15)
    call = SimpleNamespace(
        call_id="call-123",
        started_at=started_at,
        ended_at=ended_at,
        final_status="completed",
        scheduled_appointment={
            "id": 88,
            "name": "Janet Doe",
            "phone": "123-456-7890",
            "reason_for_visit": "Cleaning",
            "start_at": "2026-04-16T10:30:00+00:00",
            "end_at": "2026-04-16T11:00:00+00:00",
            "notes": ["Bring insurance card"],
            "status": "SCHEDULED",
            "patient_type": "existing",
            "created_at": "2026-04-15T10:01:00+00:00",
            "updated_at": "2026-04-15T10:02:00+00:00",
        },
        turns=[
            {
                "role": "assistant",
                "content": "Hello there",
                "created_at": started_at.isoformat(),
                "total_tokens": 42,
                "total_delay_s": 1.2,
                "first_token_delay_s": 0.4,
            },
            {
                "role": "user",
                "content": "I need an appointment",
                "created_at": (started_at + timedelta(seconds=30)).isoformat(),
                "total_tokens": None,
                "total_delay_s": None,
                "first_token_delay_s": None,
            },
        ],
    )

    summary = _to_summary_out(call)
    detail = _to_detail_out(call)

    assert summary.call_id == "call-123"
    assert summary.duration_seconds == 135
    assert summary.final_status == "completed"
    assert summary.total_tokens == 42
    assert summary.avg_total_delay_s == 1.2
    assert summary.avg_first_token_delay_s == 0.4
    assert detail.turns[0].role == "assistant"
    assert detail.turns[1].content == "I need an appointment"
    assert detail.turns[0].total_tokens == 42
    assert detail.turns[0].total_delay_s == 1.2
    assert detail.turns[0].first_token_delay_s == 0.4
    assert detail.turns[1].total_tokens is None
    assert detail.scheduled_appointment is not None
    assert detail.scheduled_appointment.name == "Janet Doe"
    assert detail.scheduled_appointment.notes == ["Bring insurance card"]


def test_api_client_parses_call_detail_payload() -> None:
    payload = {
        "call_id": "call-456",
        "started_at": "2026-04-15T10:00:00+00:00",
        "ended_at": "2026-04-15T10:01:00+00:00",
        "duration_seconds": 60,
        "final_status": "scheduled",
        "total_tokens": 99,
        "avg_total_delay_s": 1.4,
        "avg_first_token_delay_s": 0.8,
        "turns": [
            {
                "role": "user",
                "content": "Can I come tomorrow?",
                "created_at": "2026-04-15T10:00:15+00:00",
                "total_tokens": None,
                "total_delay_s": None,
                "first_token_delay_s": None,
            }
        ],
        "scheduled_appointment": {
            "id": 99,
            "name": "Janet Doe",
            "phone": "123-456-7890",
            "reason_for_visit": "Cleaning",
            "start_at": "2026-04-16T10:30:00+00:00",
            "end_at": "2026-04-16T11:00:00+00:00",
            "notes": ["Bring insurance card"],
            "status": "SCHEDULED",
            "patient_type": "existing",
            "created_at": "2026-04-15T10:01:00+00:00",
            "updated_at": "2026-04-15T10:02:00+00:00",
        },
    }

    detail = ApiClient._parse_call_detail(payload)

    assert detail.call_id == "call-456"
    assert detail.final_status == "scheduled"
    assert detail.total_tokens == 99
    assert detail.avg_total_delay_s == 1.4
    assert detail.avg_first_token_delay_s == 0.8
    assert len(detail.turns) == 1
    assert detail.turns[0].role == "user"
    assert detail.turns[0].total_delay_s is None
    assert detail.scheduled_appointment is not None
    assert detail.scheduled_appointment.reason_for_visit == "Cleaning"


def test_extract_scheduled_appointment_snapshot_only_returns_scheduled_view() -> None:
    snapshot = _extract_scheduled_appointment_snapshot(
        {
            "held_appointment_view": {"id": 7, "name": "Hold Only"},
            "scheduled_appointment_view": {
                "id": 9,
                "name": "Janet Doe",
                "phone": "123-456-7890",
                "reason_for_visit": "Cleaning",
                "start_at": "2026-04-16T10:30:00+00:00",
                "notes": ["Bring insurance card"],
            },
        }
    )

    assert snapshot == {
        "id": 9,
        "name": "Janet Doe",
        "phone": "123-456-7890",
        "reason_for_visit": "Cleaning",
        "start_at": "2026-04-16T10:30:00+00:00",
        "notes": ["Bring insurance card"],
    }
    assert _extract_scheduled_appointment_snapshot({"held_appointment_view": {"id": 7}}) is None


def test_dashboard_state_helpers_compute_status_and_selection() -> None:
    assert get_call_status(final_status="scheduled", ended_at=None) == "scheduled"
    assert get_call_status(final_status=None, ended_at="2026-04-15T10:01:00+00:00") == "completed"
    assert get_call_status(final_status=None, ended_at=None) == "active"

    assert normalize_selected_call_id(["call-1", "call-2"], None) == "call-1"
    assert normalize_selected_call_id(["call-1", "call-2"], "call-2") == "call-2"
    assert format_in_default_tz("2026-04-15T10:00:00+00:00", fmt="%Y-%m-%d %H:%M:%S") == "2026-04-15 18:00:00"
    assert format_in_default_tz("2026-04-15T10:30:00+00:00", fmt="%b %d, %Y at %I:%M %p") == "Apr 15, 2026 at 06:30 PM"


def test_retell_status_derivation_prefers_appointment_outcomes() -> None:
    assert _derive_call_status({"held_appointment_view": {"id": 1}}) == "held"
    assert _derive_call_status({"scheduled_appointment_view": {"id": 2}}) == "scheduled"
    assert _derive_final_status({"phase": "done"}) == "completed"
    assert _derive_disconnect_status({"assistant_phase": "collecting_info"}) == "disconnected"
    assert _derive_disconnect_status({"scheduled_appointment_view": {"id": 3}}) == "scheduled"
