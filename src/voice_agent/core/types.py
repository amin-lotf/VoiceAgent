from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Annotated
from typing import TypedDict, NotRequired, Required
from uuid import UUID



def merge_node_data(
    left: dict[str, dict[str, Any]] | None,
    right: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = deepcopy(left or {})
    for node_name, payload in (right or {}).items():
        if payload == {}:
            out[node_name] = {}
        else:
            out.setdefault(node_name, {})
            out[node_name].update(payload or {})
    return out

class OperationStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


class ChunkKind(StrEnum):
    TOKEN = "token"
    FINAL = "final"
    DEBUG = "debug"


class CallEvent(StrEnum):
    CALL_STARTED = "call_started"
    USER_TURN = "user_turn"
    CALL_ENDED = "call_ended"


class CallPhase(StrEnum):
    GREETING = "greeting"
    INTENT_ROUTING = "intent_routing"
    DONE = "done"

class UserIntent(StrEnum):
    BOOK_APPOINTMENT = "book_appointment"
    UNDECIDED = "undecided"

class ConfirmationIntent(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    UNCLEAR = "unclear"
    NOT_SPECIFIED = 'not_specified'

class AssistantIntent(StrEnum):
    HUMAN_HANDOFF = "human_handoff"
    HANGUP = "hangup"
    CONTINUE = "continue"

class NextAction(StrEnum):
    ASK_USER= 'ask_user'
    EXTRACT_INFO = 'extract_info'
    CHECK_INFO = 'check_info'
    MARK_VERIFIED = 'mark_verified'
    EXTRACT_DATETIME = 'extract_datetime'
    HOLD_APPOINTMENT = 'hold_appointment'
    CALL_OPERATOR = 'call_operator'
    BOOK_APPOINTMENT = 'book_appointment'
    TAKE_NOTE = 'take_note'
    REPORT_ERROR = 'report_error'
    OTHER = 'other'


class AssistantPhase(StrEnum):
    COLLECTING_USER_INTENT = "collecting_user_intent"
    COLLECTING_INFO = "collecting_info"
    VERIFYING_INFO = "verifying_info"
    CONFIRMING_SLOT = "confirming_slot"
    BOOKING_APPOINTMENT = "booking_appointment"
    COLLECTING_NOTES = "collecting_notes"
    DONE = "done"




class PatientType(StrEnum):
    NEW = "new"
    EXISTING = "existing"

class AppointmentStatus(StrEnum):
    PENDING = "PENDING"
    HELD = "HELD"         # optional: temporary hold before confirmation
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class TimeSlot:
    start_at: datetime
    end_at: datetime




class AppointmentField(StrEnum):
    NAME = "name"
    PHONE = "phone"
    REASON_FOR_VISIT = "reason_for_visit"
    NOTES = "notes"
    REQUESTED_TIME_TEXT = "requested_time_text"

class ConfirmationTopic(StrEnum):
    HOLD_CONFIRMATION = "hold_confirmation"

class RequiredAppointmentField(StrEnum):
    NAME = "name"
    PHONE = "phone"
    REASON_FOR_VISIT = "reason_for_visit"
    REQUESTED_TIME_TEXT = "requested_time_text"


class FieldChange(TypedDict, total=False):
    field: str
    old_value: str | None
    new_value: str | None
    action: str  # "added", "updated"
    source_node: str




class AppointmentDraft(TypedDict,total=False):
    name: str | None
    phone: str | None
    reason_for_visit: str | None
    notes: list[str]
    requested_time_text: str | None  # raw user input (e.g. "tomorrow morning")
    requested_time_iso: str | None  # normalized ISO (e.g. "2026-04-05T09:00:00+08:00")
    last_offered_slot_start_at: str | None  # latest offered slot in ISO datetime
    offered_time_confirmed: bool | None
    status: AppointmentStatus

class SchedulePatch(TypedDict):
    date_mode: str
    date_key: str
    time_pref: str
    exact_time_text: str
    relative_to_offered:str


class AppointmentPatch(TypedDict, total=False):
    name: str | None
    phone: str | None
    reason_for_visit: str | None
    requested_time_text: str | None
    confirmation_intent: ConfirmationIntent | None
    user_intent: UserIntent | None
    notes: list[str]


class AppointmentCreate(TypedDict):
    name: str
    phone: str
    reason_for_visit: str
    start_at: datetime
    end_at: datetime
    notes: list[str]
    status: AppointmentStatus
    patient_type: PatientType  # CRM-derived




class AppointmentView(TypedDict):
    id: int
    name: str
    phone: str
    reason_for_visit: str
    start_at: str
    end_at: str
    notes: list[str]
    status: AppointmentStatus
    patient_type: PatientType  # CRM-derived
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class EngineChunk:
    kind: ChunkKind
    data: Any




class CallState(TypedDict, total=False):
    call_id: Required[str]
    phase: Required[CallPhase]

    messages: NotRequired[list[dict]]
    assistant_text: NotRequired[str]
    assistant_streamed: NotRequired[bool]
    internal_call: NotRequired[bool]

    appointment_draft: NotRequired[AppointmentDraft]
    appointment_patch: NotRequired[AppointmentPatch]
    node_data: NotRequired[Annotated[dict[str, dict[str, Any]], merge_node_data]]
    meta: NotRequired[dict[str, Any]]

    end_call: NotRequired[bool]

    # per-turn / ephemeral
    event: NotRequired[CallEvent]
    user_text: NotRequired[str | None]
    prev_user_text: NotRequired[str | None]
    pending_question: NotRequired[str | None]
    is_pending_question: NotRequired[bool]
    assistant_phase: NotRequired[AssistantPhase | None]
    assistant_intent: NotRequired[AssistantIntent | None]
    user_intent: NotRequired[UserIntent | None]
    scheduled_appointment_view: NotRequired[AppointmentView]
    held_appointment_view: NotRequired[AppointmentView]
    current_appointment_id: NotRequired[int | None]
    prev_assistant_text: NotRequired[str]
    next_action: NotRequired[NextAction]



@dataclass(frozen=True, slots=True)
class RunResult:
    """Return type for non-streaming runs."""
    assistant_text: str
    state: CallState

