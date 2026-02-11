from __future__ import annotations

from datetime import datetime

from voice_agent.core.types import CallPhase, CallState
from .utils import ensure_appointment, ensure_spoken_on_user_turn


def node_execute_schedule_appointment(state: CallState) -> CallState:
    """
    Placeholder tool executor. Simulates creating an appointment and confirms to the caller.
    """
    appointment = ensure_appointment(state)
    appointment_id = appointment.get("appointment_id") or f"apt-{state.get('call_id', 'unknown')}-{int(datetime.utcnow().timestamp())}"
    appointment["appointment_id"] = appointment_id

    date_text = appointment.get("date_requested") or appointment.get("date_iso") or "the requested date"
    time_text = appointment.get("time_requested") or appointment.get("time_iso") or "the requested time"

    state["assistant_text"] = (
        f"All set. I've scheduled your appointment for {date_text} at {time_text}. "
        f"Your confirmation number is {appointment_id}."
    )
    state["phase"] = CallPhase.DONE
    state["pending_question"] = None
    state["appointment"] = appointment
    ensure_spoken_on_user_turn(state)
    return state
