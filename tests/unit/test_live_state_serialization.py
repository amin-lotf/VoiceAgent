from __future__ import annotations

from voice_agent.core.api.v1.live.state import (
    build_live_turn_metrics,
    serialize_live_call_state,
)


def test_serialize_live_call_state_exposes_dashboard_fields() -> None:
    state = {
        "call_id": "live-call-1",
        "phase": "intent_routing",
        "assistant_phase": "collecting_info",
        "next_action": "extract_info",
        "assistant_intent": "continue",
        "user_intent": "book_appointment",
        "last_completed_node": "call_operator",
        "messages": [
            {"role": "assistant", "content": "Hello there"},
            {"role": "user", "content": "I need a cleaning"},
        ],
        "appointment_draft": {
            "name": "Janet Doe",
            "phone": "123-456-7890",
            "reason_for_visit": "Cleaning",
            "requested_time_text": "tomorrow morning",
            "requested_time_iso": "2026-05-02T09:00:00+08:00",
            "notes": ["Prefers Dr. Lin"],
            "status": "HELD",
        },
        "held_appointment_view": {
            "id": 42,
            "name": "Janet Doe",
            "phone": "123-456-7890",
            "reason_for_visit": "Cleaning",
            "start_at": "2026-05-02T09:00:00+08:00",
            "end_at": "2026-05-02T09:30:00+08:00",
            "notes": ["Prefers Dr. Lin"],
            "status": "HELD",
        },
        "node_data": {
            "call_operator": {
                "ttft_seconds": 0.42,
                "total_delay_s": 1.31,
                "input_tokens": 55,
                "output_tokens": 18,
                "total_tokens": 73,
            },
            "basic_info": {
                "total_delay_s": 0.22,
                "field_changes": [{"field": "name", "action": "added"}],
            },
        },
    }

    live_state = serialize_live_call_state("live-call-1", state)

    assert live_state.call_id == "live-call-1"
    assert live_state.status == "held"
    assert live_state.current_node == "call_operator"
    assert live_state.phase == "intent_routing"
    assert live_state.assistant_phase == "collecting_info"
    assert live_state.next_action == "extract_info"
    assert live_state.appointment_draft.name == "Janet Doe"
    assert live_state.held_appointment is not None
    assert live_state.held_appointment.id == 42
    assert len(live_state.messages) == 2
    assert live_state.metrics.ttft_s == 0.42
    assert live_state.metrics.total_latency_s == 1.53
    assert live_state.metrics.total_tokens == 73


def test_build_live_turn_metrics_prefers_explicit_turn_latency() -> None:
    state = {
        "node_data": {
            "greeting": {
                "ttft_seconds": 0.18,
                "total_delay_s": 0.77,
                "input_tokens": 12,
                "output_tokens": 8,
                "total_tokens": 20,
            }
        }
    }

    metrics = build_live_turn_metrics(
        state,
        total_latency_s=1.11,
        first_token_delay_s=0.21,
    )

    assert metrics.ttft_s == 0.21
    assert metrics.total_latency_s == 1.11
    assert metrics.input_tokens == 12
    assert metrics.output_tokens == 8
    assert metrics.total_tokens == 20
