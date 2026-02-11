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
    HANGUP = "hangup"


class CallPhase(StrEnum):
    GREETING = "greeting"
    INTENT_ROUTING = "intent_routing"
    SLOT_FILL = "slot_fill"
    CONFIRM = "confirm"
    TOOL_EXECUTION = "tool_execution"
    TRIAGE = "triage"
    HANDOFF = "handoff"
    DONE = "done"


class ClinicIntent(StrEnum):
    BOOK_APPOINTMENT = "book_appointment"
    RESCHEDULE = "reschedule"
    CANCEL = "cancel"
    NEW_PATIENT = "new_patient"
    EXISTING_PATIENT = "existing_patient"
    INSURANCE_QUESTION = "insurance_question"
    PRICING_QUESTION = "pricing_question"
    OFFICE_INFO = "office_info"
    URGENT_SYMPTOM = "urgent_symptom"
    HUMAN_HANDOFF = "human_handoff"


class AppointmentSlots(TypedDict, total=False):
    patient_type: Literal["new", "existing"]
    name: str
    date_requested: str
    date_iso: str
    time_requested: str
    time_iso: str
    provider: str
    phone: str
    email: str
    reason_for_visit: str
    insurance_provider: str





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
    meta: NotRequired[dict]

    # Flow control
    phase: Required[CallPhase]
    intent: NotRequired[ClinicIntent | None]

    # Slot container
    appointment: NotRequired[AppointmentSlots]

    # If you later support more flows:
    # reschedule: NotRequired[RescheduleSlots]
    # cancellation: NotRequired[CancelSlots]

    pending_question: NotRequired[str | None]

    # Transcript memory
    messages: NotRequired[list[dict]]
    assistant_text: NotRequired[str]

    # Control flags
    end_call: NotRequired[bool]

    # Metadata
    started_at: NotRequired[str]

