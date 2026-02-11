from __future__ import annotations

from voice_agent.core.types import CallPhase, CallState
from .utils import (
    ensure_appointment,
    is_valid_email,
    next_missing_slot,
    normalize_phone,
    parse_date_time,
)


def node_ask_next_appointment_slot(state: CallState) -> CallState:
    appointment = ensure_appointment(state)
    missing = next_missing_slot(appointment)

    if missing is None:
        state["phase"] = CallPhase.CONFIRM
        state["assistant_text"] = "I think I have everything I need. Let me confirm the details with you."
        state["pending_question"] = "confirm_yes_no"
        return state

    prompts = {
        "ask_datetime": "What date and time would you like for the appointment?",
        "ask_name": "What's the patient's full name?",
        "ask_phone": "What's the best phone number to reach you?",
        "ask_email": "What's the best email to send the confirmation to?",
    }

    state["pending_question"] = missing
    state["phase"] = CallPhase.SLOT_FILL
    state["assistant_text"] = prompts.get(missing, "Could you share more details?")
    return state


def node_fill_appointment_slot(state: CallState) -> CallState:
    appointment = ensure_appointment(state)
    user_text = (state.get("user_text") or "").strip()
    pending = state.get("pending_question")

    # Opportunistically capture details even if no explicit question is pending.
    if not pending and user_text:
        date_text, time_text, ambiguous = parse_date_time(user_text)
        if date_text and not appointment.get("date_requested"):
            appointment["date_requested"] = date_text
        if time_text and not appointment.get("time_requested"):
            appointment["time_requested"] = time_text
        phone_candidate = normalize_phone(user_text)
        if phone_candidate and not appointment.get("phone"):
            appointment["phone"] = phone_candidate
        if is_valid_email(user_text) and not appointment.get("email"):
            appointment["email"] = user_text

    assistant_text: str | None = None

    if pending == "ask_datetime":
        date_text, time_text, ambiguous = parse_date_time(user_text)
        if not date_text or not time_text or ambiguous:
            assistant_text = "I didn't catch the date and time. What date and time work best for you?"
            state["pending_question"] = "ask_datetime"
            state["phase"] = CallPhase.SLOT_FILL
        else:
            appointment["date_requested"] = date_text
            appointment["time_requested"] = time_text
            state["pending_question"] = None

    elif pending == "ask_name":
        if not user_text:
            assistant_text = "Could you share the patient's full name?"
            state["pending_question"] = "ask_name"
            state["phase"] = CallPhase.SLOT_FILL
        else:
            appointment["name"] = user_text
            state["pending_question"] = None

    elif pending == "ask_phone":
        normalized = normalize_phone(user_text)
        if not normalized:
            assistant_text = "That number didn't come through. What's the best 10-digit phone number to reach you?"
            state["pending_question"] = "ask_phone"
            state["phase"] = CallPhase.SLOT_FILL
        else:
            appointment["phone"] = normalized
            state["pending_question"] = None

    elif pending == "ask_email":
        if not is_valid_email(user_text):
            assistant_text = "Could you share a valid email address for the confirmation?"
            state["pending_question"] = "ask_email"
            state["phase"] = CallPhase.SLOT_FILL
        else:
            appointment["email"] = user_text
            state["pending_question"] = None

    missing = next_missing_slot(appointment)
    if missing is None:
        state["phase"] = CallPhase.CONFIRM
    else:
        state["phase"] = CallPhase.SLOT_FILL

    if assistant_text:
        state["assistant_text"] = assistant_text

    state["appointment"] = appointment
    return state
