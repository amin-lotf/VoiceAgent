from __future__ import annotations

from voice_agent.core.types import CallEvent, CallPhase, CallState, ClinicIntent
from .utils import detect_emergency, ensure_spoken_on_user_turn


def node_triage_precheck(state: CallState) -> CallState:
    """Lightweight emergency detection before normal routing."""
    state["triage_triggered"] = False
    if state.get("event") != CallEvent.USER_TURN:
        return state

    if detect_emergency(state.get("user_text")):
        state["intent"] = ClinicIntent.URGENT_SYMPTOM
        state["phase"] = CallPhase.TRIAGE
        state["pending_question"] = None
        state["triage_triggered"] = True
    return state


def node_triage_respond(state: CallState) -> CallState:
    """Escalate to emergency guidance."""
    state["assistant_text"] = (
        "I'm not able to help with medical emergencies. "
        "Please hang up and call 911 or your local emergency services right away."
    )
    state["end_call"] = True
    state["phase"] = CallPhase.DONE
    state["pending_question"] = None
    ensure_spoken_on_user_turn(state)
    return state
