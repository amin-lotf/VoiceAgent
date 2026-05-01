from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi.encoders import jsonable_encoder

from voice_agent.const import (
    INPUT_TOKENS_KEY,
    OUTPUT_TOKENS_KEY,
    TOTAL_DELAY_KEY,
    TOTAL_TOKENS_KEY,
)
from voice_agent.core.api.v1.live.schemas import (
    LiveAppointmentDraftOut,
    LiveAppointmentViewOut,
    LiveCallStateOut,
    LiveMessageOut,
    LiveMetricsOut,
)
from voice_agent.core.types import CallState


def _stringify(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return round(max(0.0, float(value)), 6)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return None


def _clean_notes(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _stringify(item)
        if text:
            out.append(text)
    return out


def _serialize_message(call_id: str, index: int, raw: Mapping[str, Any]) -> LiveMessageOut | None:
    role_raw = _stringify(raw.get("role")) or "system"
    role = role_raw.lower()
    if role not in {"assistant", "user", "system"}:
        role = "system"

    content = _stringify(raw.get("content"))
    if not content:
        return None

    return LiveMessageOut(
        id=f"{call_id}:message:{index}",
        role=role,
        content=content,
        created_at=_stringify(raw.get("created_at")),
        response_id=_coerce_int(raw.get("response_id")),
    )


def _serialize_appointment_draft(raw: object) -> LiveAppointmentDraftOut:
    payload = raw if isinstance(raw, Mapping) else {}
    return LiveAppointmentDraftOut(
        name=_stringify(payload.get("name")),
        phone=_stringify(payload.get("phone")),
        reason_for_visit=_stringify(payload.get("reason_for_visit")),
        requested_time_text=_stringify(payload.get("requested_time_text")),
        requested_time_iso=_stringify(payload.get("requested_time_iso")),
        last_offered_slot_start_at=_stringify(payload.get("last_offered_slot_start_at")),
        offered_time_confirmed=payload.get("offered_time_confirmed")
        if isinstance(payload.get("offered_time_confirmed"), bool)
        else None,
        status=_stringify(payload.get("status")),
        notes=_clean_notes(payload.get("notes")),
    )


def _serialize_appointment_view(raw: object) -> LiveAppointmentViewOut | None:
    if not isinstance(raw, Mapping):
        return None

    appt_id = _coerce_int(raw.get("id"))
    if appt_id is None:
        return None

    return LiveAppointmentViewOut(
        id=appt_id,
        name=_stringify(raw.get("name")),
        phone=_stringify(raw.get("phone")),
        reason_for_visit=_stringify(raw.get("reason_for_visit")),
        start_at=_stringify(raw.get("start_at")),
        end_at=_stringify(raw.get("end_at")),
        notes=_clean_notes(raw.get("notes")),
        status=_stringify(raw.get("status")),
        patient_type=_stringify(raw.get("patient_type")),
        created_at=_stringify(raw.get("created_at")),
        updated_at=_stringify(raw.get("updated_at")),
    )


def _sum_node_metric(node_data: Mapping[str, Any], key: str) -> int:
    total = 0
    for bucket in node_data.values():
        if not isinstance(bucket, Mapping):
            continue
        value = _coerce_int(bucket.get(key))
        if value is not None:
            total += value
    return total


def _sum_node_delay(node_data: Mapping[str, Any]) -> float | None:
    total = 0.0
    seen = False
    for bucket in node_data.values():
        if not isinstance(bucket, Mapping):
            continue
        value = _coerce_float(bucket.get(TOTAL_DELAY_KEY))
        if value is None:
            continue
        total += value
        seen = True
    return round(total, 6) if seen else None


def _min_node_ttft(node_data: Mapping[str, Any]) -> float | None:
    values: list[float] = []
    for bucket in node_data.values():
        if not isinstance(bucket, Mapping):
            continue
        value = _coerce_float(bucket.get("ttft_seconds"))
        if value is not None:
            values.append(value)
    return min(values) if values else None


def _derive_status(state: Mapping[str, Any]) -> str:
    if state.get("scheduled_appointment_view"):
        return "scheduled"
    if state.get("held_appointment_view"):
        return "held"
    if bool(state.get("end_call")):
        return "completed"
    if state.get("messages"):
        return "active"
    return "idle"


def _derive_current_node(state: Mapping[str, Any]) -> str | None:
    for key in ("active_node", "last_completed_node", "last_failed_node"):
        value = _stringify(state.get(key))
        if value:
            return value
    return None


def _serialize_node_data(raw: object) -> dict[str, dict[str, Any]]:
    payload = raw if isinstance(raw, Mapping) else {}
    serialized: dict[str, dict[str, Any]] = {}
    for node_name, bucket in payload.items():
        if not isinstance(bucket, Mapping):
            continue
        serialized[str(node_name)] = dict(jsonable_encoder(bucket))
    return serialized


def build_live_turn_metrics(
    state: CallState | dict[str, Any] | None,
    *,
    total_latency_s: float | None = None,
    first_token_delay_s: float | None = None,
) -> LiveMetricsOut:
    payload = jsonable_encoder(state or {})
    node_data = payload.get("node_data") if isinstance(payload, Mapping) else {}
    if not isinstance(node_data, Mapping):
        node_data = {}

    ttft_s = _coerce_float(first_token_delay_s) or _min_node_ttft(node_data)
    latency = _coerce_float(total_latency_s)
    if latency is None:
        latency = _sum_node_delay(node_data)

    input_tokens = _sum_node_metric(node_data, INPUT_TOKENS_KEY)
    output_tokens = _sum_node_metric(node_data, OUTPUT_TOKENS_KEY)
    total_tokens = _sum_node_metric(node_data, TOTAL_TOKENS_KEY)

    return LiveMetricsOut(
        ttft_s=ttft_s,
        total_latency_s=latency,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def serialize_live_call_state(
    call_id: str,
    state: CallState | dict[str, Any] | None,
) -> LiveCallStateOut:
    payload = jsonable_encoder(state or {})

    raw_messages = payload.get("messages") if isinstance(payload, Mapping) else []
    messages: list[LiveMessageOut] = []
    if isinstance(raw_messages, list):
        for index, raw in enumerate(raw_messages):
            if not isinstance(raw, Mapping):
                continue
            message = _serialize_message(call_id, index, raw)
            if message is not None:
                messages.append(message)

    call_id_value = _stringify(payload.get("call_id")) or call_id
    node_data = _serialize_node_data(payload.get("node_data"))

    return LiveCallStateOut(
        call_id=call_id_value,
        status=_derive_status(payload),
        phase=_stringify(payload.get("phase")),
        assistant_phase=_stringify(payload.get("assistant_phase")),
        next_action=_stringify(payload.get("next_action")),
        assistant_intent=_stringify(payload.get("assistant_intent")),
        user_intent=_stringify(payload.get("user_intent")),
        current_node=_derive_current_node(payload),
        end_call=bool(payload.get("end_call", False)),
        messages=messages,
        appointment_draft=_serialize_appointment_draft(payload.get("appointment_draft")),
        held_appointment=_serialize_appointment_view(payload.get("held_appointment_view")),
        scheduled_appointment=_serialize_appointment_view(payload.get("scheduled_appointment_view")),
        metrics=build_live_turn_metrics(payload),
        node_data=node_data,
    )
