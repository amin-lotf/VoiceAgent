from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from voice_agent.core.api.v1.retell.router import (
    _derive_call_status,
    _derive_disconnect_status,
    _derive_final_status,
)
from voice_agent.core.api.v1.calls.router import _to_detail_out, _to_summary_out
from voice_agent.frontend.dashboard_state import get_call_status, normalize_selected_call_id
from voice_agent.frontend.api_clinet import ApiClient


def test_calls_router_serializes_summary_and_turns() -> None:
    started_at = datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc)
    ended_at = started_at + timedelta(minutes=2, seconds=15)
    call = SimpleNamespace(
        call_id="call-123",
        started_at=started_at,
        ended_at=ended_at,
        final_status="completed",
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


def test_dashboard_state_helpers_compute_status_and_selection() -> None:
    assert get_call_status(final_status="scheduled", ended_at=None) == "scheduled"
    assert get_call_status(final_status=None, ended_at="2026-04-15T10:01:00+00:00") == "completed"
    assert get_call_status(final_status=None, ended_at=None) == "active"

    assert normalize_selected_call_id(["call-1", "call-2"], None) == "call-1"
    assert normalize_selected_call_id(["call-1", "call-2"], "call-2") == "call-2"


def test_retell_status_derivation_prefers_appointment_outcomes() -> None:
    assert _derive_call_status({"held_appointment_view": {"id": 1}}) == "held"
    assert _derive_call_status({"scheduled_appointment_view": {"id": 2}}) == "scheduled"
    assert _derive_final_status({"phase": "done"}) == "completed"
    assert _derive_disconnect_status({"assistant_phase": "collecting_info"}) == "disconnected"
    assert _derive_disconnect_status({"scheduled_appointment_view": {"id": 3}}) == "scheduled"
