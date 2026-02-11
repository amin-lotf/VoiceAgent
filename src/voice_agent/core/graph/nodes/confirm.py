from __future__ import annotations

from voice_agent.core.types import CallPhase, CallState
from .utils import ensure_appointment, ensure_spoken_on_user_turn, is_no, is_yes


def node_confirm_appointment(state: CallState) -> CallState:
    appointment = ensure_appointment(state)

    date_text = appointment.get("date_requested") or appointment.get("date_iso") or "the requested date"
    time_text = appointment.get("time_requested") or appointment.get("time_iso") or "the time you mentioned"

    state["assistant_text"] = f"Just to confirm: I will book you for {date_text} at {time_text}. Is that correct?"
    state["pending_question"] = "confirm_yes_no"
    state["phase"] = CallPhase.CONFIRM
    ensure_spoken_on_user_turn(state)
    return state


def node_handle_confirm_yes_no(state: CallState) -> CallState:
    # If we haven't asked for confirmation yet, do that first.
    if state.get("pending_question") != "confirm_yes_no":
        return node_confirm_appointment(state)

    user_text = (state.get("user_text") or "").strip()
    appointment = ensure_appointment(state)

    if is_yes(user_text):
        state["phase"] = CallPhase.TOOL_EXECUTION
        state["pending_question"] = None
        state["assistant_text"] = ""
        return state

    if is_no(user_text):
        appointment.pop("date_requested", None)
        appointment.pop("date_iso", None)
        appointment.pop("time_requested", None)
        appointment.pop("time_iso", None)

        state["phase"] = CallPhase.SLOT_FILL
        state["pending_question"] = "ask_datetime"
        state["assistant_text"] = "No problem. What date and time would you like instead?"
        state["appointment"] = appointment
        return state

    state["assistant_text"] = "I didn't catch that. Should I go ahead and book this appointment?"
    state["phase"] = CallPhase.CONFIRM
    state["pending_question"] = "confirm_yes_no"
    ensure_spoken_on_user_turn(state)
    return state
