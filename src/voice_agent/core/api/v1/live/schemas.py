from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field


class LiveUserMessageIn(BaseModel):
    type: Literal["user.message"]
    text: str


class LiveCancelIn(BaseModel):
    type: Literal["assistant.cancel"]


class LivePingIn(BaseModel):
    type: Literal["ping"]
    timestamp: int | None = None


class LiveSnapshotRequestIn(BaseModel):
    type: Literal["session.snapshot"]


LiveClientEvent = Union[
    LiveUserMessageIn,
    LiveCancelIn,
    LivePingIn,
    LiveSnapshotRequestIn,
]


class LiveMessageOut(BaseModel):
    id: str
    role: Literal["assistant", "user", "system"]
    content: str
    created_at: str | None = None
    response_id: int | None = None


class LiveMetricsOut(BaseModel):
    ttft_s: float | None = None
    total_latency_s: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class LiveAppointmentDraftOut(BaseModel):
    name: str | None = None
    phone: str | None = None
    reason_for_visit: str | None = None
    requested_time_text: str | None = None
    requested_time_iso: str | None = None
    last_offered_slot_start_at: str | None = None
    offered_time_confirmed: bool | None = None
    status: str | None = None
    notes: list[str] = Field(default_factory=list)


class LiveAppointmentViewOut(BaseModel):
    id: int
    name: str | None = None
    phone: str | None = None
    reason_for_visit: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    notes: list[str] = Field(default_factory=list)
    status: str | None = None
    patient_type: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class LiveCallStateOut(BaseModel):
    call_id: str
    status: str = "idle"
    phase: str | None = None
    assistant_phase: str | None = None
    next_action: str | None = None
    assistant_intent: str | None = None
    user_intent: str | None = None
    current_node: str | None = None
    end_call: bool = False
    messages: list[LiveMessageOut] = Field(default_factory=list)
    appointment_draft: LiveAppointmentDraftOut = Field(default_factory=LiveAppointmentDraftOut)
    held_appointment: LiveAppointmentViewOut | None = None
    scheduled_appointment: LiveAppointmentViewOut | None = None
    metrics: LiveMetricsOut = Field(default_factory=LiveMetricsOut)
    node_data: dict[str, dict[str, Any]] = Field(default_factory=dict)


class LiveCapabilitiesOut(BaseModel):
    cancel_active_response: bool = True
    dashboard_available: bool = True
    logs_available: bool = True


class LiveEventBase(BaseModel):
    type: str
    timestamp: str


class LiveSessionReadyOut(LiveEventBase):
    type: Literal["session.ready"] = "session.ready"
    call_id: str
    state: LiveCallStateOut
    capabilities: LiveCapabilitiesOut = Field(default_factory=LiveCapabilitiesOut)


class LiveStateSnapshotOut(LiveEventBase):
    type: Literal["state.snapshot"] = "state.snapshot"
    state: LiveCallStateOut


class LiveUserMessageOut(LiveEventBase):
    type: Literal["user.message"] = "user.message"
    message: LiveMessageOut


class LiveAssistantStartedOut(LiveEventBase):
    type: Literal["assistant.response.started"] = "assistant.response.started"
    response_id: int
    trigger: str | None = None


class LiveAssistantDeltaOut(LiveEventBase):
    type: Literal["assistant.response.delta"] = "assistant.response.delta"
    response_id: int
    delta: str


class LiveAssistantCompletedOut(LiveEventBase):
    type: Literal["assistant.response.completed"] = "assistant.response.completed"
    response_id: int
    message: LiveMessageOut
    metrics: LiveMetricsOut
    end_call: bool = False
    state: LiveCallStateOut


class LiveAssistantCancelledOut(LiveEventBase):
    type: Literal["assistant.response.cancelled"] = "assistant.response.cancelled"
    response_id: int | None = None
    reason: str


class LivePhaseChangedOut(LiveEventBase):
    type: Literal["phase.changed"] = "phase.changed"
    phase: str | None = None
    assistant_phase: str | None = None
    next_action: str | None = None
    current_node: str | None = None


class LiveAppointmentUpdatedOut(LiveEventBase):
    type: Literal["appointment.updated"] = "appointment.updated"
    appointment_draft: LiveAppointmentDraftOut
    held_appointment: LiveAppointmentViewOut | None = None
    scheduled_appointment: LiveAppointmentViewOut | None = None


class LiveInternalEventOut(LiveEventBase):
    type: Literal["internal.event"] = "internal.event"
    event_name: str
    node: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class LiveLogOut(LiveEventBase):
    type: Literal["log"] = "log"
    level: Literal["debug", "info", "warning", "error"]
    message: str
    details: dict[str, Any] | None = None


class LiveErrorOut(LiveEventBase):
    type: Literal["error"] = "error"
    message: str


class LivePongOut(LiveEventBase):
    type: Literal["pong"] = "pong"
    client_timestamp: int | None = None
