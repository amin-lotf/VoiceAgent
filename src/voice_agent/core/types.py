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
        out.setdefault(node_name, {})
        out[node_name].update(payload or {})
    return out


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
    RESCHEDULE = "reschedule"
    CANCEL = "cancel"
    UNDECIDED = "undecided"

class ClinicIntent(StrEnum):
    HUMAN_HANDOFF = "human_handoff"
    HANGUP = "hangup"
    CONTINUE = "continue"





class OfficeTopic(StrEnum):
    HOURS = "hours"
    ADDRESS = "address"
    LOCATION = "location"
    PARKING = "parking"

class PatientType(StrEnum):
    NEW = "new"
    EXISTING = "existing"

class AppointmentStatus(StrEnum):
    HELD = "held"         # optional: temporary hold before confirmation
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class TimeSlot:
    start_at: datetime
    end_at: datetime

class AppointmentDraft(TypedDict,total=False):
    name: str | None
    phone: str | None
    reason_for_visit: str | None
    requested_time: str | None
    last_offered_slot_start_at: str | None

class SchedulePatch(TypedDict):
    date_mode: str
    date_key: str
    time_pref: str
    exact_time_text: str

class AppointmentPatch(TypedDict, total=False):
    name: str | None
    phone: str | None
    reason_for_visit: str | None
    requested_time_text: str | None
    last_offered_slot_start_at: str | None
    schedule_patch: SchedulePatch | None


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

    appointment_draft: NotRequired[AppointmentDraft]
    appointment_patch: NotRequired[AppointmentPatch]
    node_data: NotRequired[Annotated[dict[str, dict[str, Any]], merge_node_data]]
    meta: NotRequired[dict[str, Any]]

    end_call: NotRequired[bool]

    # per-turn / ephemeral
    event: NotRequired[CallEvent]
    user_text: NotRequired[str | None]
    prev_user_text: NotRequired[str | None]
    clinic_intent: NotRequired[ClinicIntent | None]
    user_intent: NotRequired[UserIntent | None]
    pending_intent: NotRequired[ClinicIntent | None]
    appointment_view: NotRequired[AppointmentView]
    prev_assistant_text: NotRequired[str]



@dataclass(frozen=True, slots=True)
class RunResult:
    """Return type for non-streaming runs."""
    assistant_text: str
    state: CallState

