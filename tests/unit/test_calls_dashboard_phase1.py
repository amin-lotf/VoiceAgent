from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from voice_agent.core.api.v1.calls.router import _to_detail_out, _to_summary_out
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
            },
            {
                "role": "user",
                "content": "I need an appointment",
                "created_at": (started_at + timedelta(seconds=30)).isoformat(),
            },
        ],
    )

    summary = _to_summary_out(call)
    detail = _to_detail_out(call)

    assert summary.call_id == "call-123"
    assert summary.duration_seconds == 135
    assert summary.final_status == "completed"
    assert detail.turns[0].role == "assistant"
    assert detail.turns[1].content == "I need an appointment"


def test_api_client_parses_call_detail_payload() -> None:
    payload = {
        "call_id": "call-456",
        "started_at": "2026-04-15T10:00:00+00:00",
        "ended_at": "2026-04-15T10:01:00+00:00",
        "duration_seconds": 60,
        "final_status": "scheduled",
        "turns": [
            {
                "role": "user",
                "content": "Can I come tomorrow?",
                "created_at": "2026-04-15T10:00:15+00:00",
            }
        ],
    }

    detail = ApiClient._parse_call_detail(payload)

    assert detail.call_id == "call-456"
    assert detail.final_status == "scheduled"
    assert len(detail.turns) == 1
    assert detail.turns[0].role == "user"
