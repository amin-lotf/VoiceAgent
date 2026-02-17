from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal
from typing import TypedDict, NotRequired, Required


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


class AppointmentSlots(TypedDict, total=False):
    patient_type: Literal["new", "existing"]
    name: str
    date_requested: str
    date_iso: str
    time_requested: str
    time_iso: str
    phone: str
    reason_for_visit: str

REQUIRED_FIELDS: tuple[str, ...] = (
    "patient_type",
    "name",
    "date_requested",
    "date_iso",
    "time_requested",
    "time_iso",
    "phone",
    "reason_for_visit",
)


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
    appointment: NotRequired[AppointmentSlots]

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
