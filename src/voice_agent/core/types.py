from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from typing import TypedDict, NotRequired, Required
from uuid import UUID


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
    TRIAGE = "triage"
    DONE = "done"


class ClinicIntent(StrEnum):
    BOOK_APPOINTMENT = "book_appointment"
    RESCHEDULE = "reschedule"
    CANCEL = "cancel"
    OFFICE_INFO = "office_info"
    HUMAN_HANDOFF = "human_handoff"
    CLARIFY = "clarify"
    HANGUP = "hangup"
    CHECK_PENDING= "check_pending"
    TRIAGE= "triage"

APPOINTMENT_INTENTS = {
    ClinicIntent.BOOK_APPOINTMENT,
    ClinicIntent.RESCHEDULE,
    ClinicIntent.CANCEL,
}





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
    name: str
    phone: str
    reason_for_visit: str
    start_at: str
    end_at: str
    last_offered_slot_start_at: str | None
    datetime_confirmed: bool
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
    # Identity
    call_id: Required[str]

    # Event envelope (per webhook)
    event: Required[CallEvent]
    user_text: NotRequired[str | None]
    prev_user_text: NotRequired[str | None]
    meta: NotRequired[dict]

    # Flow control
    phase: Required[CallPhase]
    intent: NotRequired[ClinicIntent | None]
    intent_confidence: NotRequired[float | None]
    pending_intent: NotRequired[ClinicIntent | None]

    # Slot container
    appointment_draft: NotRequired[AppointmentDraft]
    appointment_view: NotRequired[AppointmentView]
    ready_to_confirm: NotRequired[bool]
    # If you later support more flows:
    # reschedule: NotRequired[RescheduleSlots]
    # cancellation: NotRequired[CancelSlots]

    pending_question: NotRequired[str | None]

    # Transcript memory
    messages: NotRequired[list[dict]]
    assistant_text: NotRequired[str]
    prev_assistant_text: NotRequired[str]
    assistant_streamed: NotRequired[bool]
    # Control flags
    end_call: NotRequired[bool]
    triage_triggered: NotRequired[bool]

    # Metadata
    started_at: NotRequired[str]
    office_topics: NotRequired[list[OfficeTopic]]


@dataclass(frozen=True, slots=True)
class RunResult:
    """Return type for non-streaming runs."""
    assistant_text: str
    state: CallState
