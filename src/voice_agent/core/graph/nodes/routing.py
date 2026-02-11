from __future__ import annotations

from voice_agent.core.types import CallEvent, CallPhase, ClinicIntent, CallState
from .utils import (
    detect_emergency,
    ensure_appointment,
    ensure_spoken_on_user_turn,
)


def node_route_event(state: CallState) -> CallState:
    """
    Lightweight router based on the incoming webhook event.
    Keeps state mutations minimal; downstream conditional edges handle branching.
    """
    # Clear any previous response so downstream checks use fresh text.
    state["assistant_text"] = ""
    ensure_appointment(state)
    event = state.get("event")
    if event == CallEvent.CALL_STARTED:
        state["phase"] = CallPhase.GREETING
        state["pending_question"] = None
    elif event == CallEvent.HANGUP:
        state["end_call"] = True
        state["phase"] = CallPhase.DONE
    return state


def node_route_phase(state: CallState) -> str:
    """
    Router for user_turn events based on current CallPhase.
    Returns a routing label string for conditional edges.
    """

    # Default safety
    phase = state.get("phase")

    if phase is None:
        state["phase"] = CallPhase.INTENT_ROUTING
        return CallPhase.INTENT_ROUTING.value

    # Greeting phase should never persist into user_turn routing
    if phase == CallPhase.GREETING:
        state["phase"] = CallPhase.INTENT_ROUTING
        return CallPhase.INTENT_ROUTING.value

    # Special split for CONFIRM phase
    if phase == CallPhase.CONFIRM:
        if state.get("pending_question") == "confirm_yes_no":
            return "confirm_handle"
        return "confirm_prompt"

    # Normal phases
    if phase in {
        CallPhase.INTENT_ROUTING,
        CallPhase.SLOT_FILL,
        CallPhase.TOOL_EXECUTION,
        CallPhase.TRIAGE,
        CallPhase.HANDOFF,
        CallPhase.DONE,
    }:
        return phase.value

    # Ultimate safety fallback
    state["phase"] = CallPhase.INTENT_ROUTING
    return CallPhase.INTENT_ROUTING.value



def node_detect_intent(state: CallState) -> CallState:
    """
    Basic intent classifier focused on booking and office info.
    Falls back to handoff for unsupported asks.
    """
    user_text = (state.get("user_text") or "").strip()
    lower_text = user_text.lower()

    if detect_emergency(user_text):
        state["intent"] = ClinicIntent.URGENT_SYMPTOM
        state["phase"] = CallPhase.TRIAGE
        state["pending_question"] = None
        return state

    if not user_text:
        state["assistant_text"] = (
            "I can help with scheduling and basic office questions. "
            "How can I assist you today?"
        )
        state["phase"] = CallPhase.INTENT_ROUTING
        state["pending_question"] = None
        ensure_spoken_on_user_turn(state)
        return state

    if any(keyword in lower_text for keyword in ["book", "schedule", "appointment", "visit"]):
        state["intent"] = ClinicIntent.BOOK_APPOINTMENT
        state["phase"] = CallPhase.SLOT_FILL
        state["pending_question"] = None
        return state

    if any(keyword in lower_text for keyword in ["hours", "open", "close", "address", "location", "parking"]):
        state["intent"] = ClinicIntent.OFFICE_INFO
        state["phase"] = CallPhase.INTENT_ROUTING
        state["pending_question"] = None
        state["assistant_text"] = (
            "We're open Monday through Friday, 9 AM to 5 PM, and the clinic is at our main office location. "
            "Would you like me to help book you an appointment?"
        )
        ensure_spoken_on_user_turn(state)
        return state

    state["intent"] = ClinicIntent.HUMAN_HANDOFF
    state["phase"] = CallPhase.HANDOFF
    state["pending_question"] = None
    return state


def node_handle_hangup(state: CallState) -> CallState:
    """Cleanup node for hangups."""
    state["assistant_text"] = state.get("assistant_text") or "Thanks for calling. If you need anything else, reach out anytime."
    state["end_call"] = True
    state["phase"] = CallPhase.DONE
    return state


def node_ask_clarify_intent(state: CallState) -> CallState:
    state["assistant_text"] = (
        "I can help with booking appointments or sharing our office hours and location. "
        "What would you like to do?"
    )
    state["phase"] = CallPhase.INTENT_ROUTING
    state["pending_question"] = None
    ensure_spoken_on_user_turn(state)
    return state


def node_finalize_response(state: CallState) -> CallState:
    """
    Ensures a spoken response exists before ending a USER_TURN.
    """
    ensure_spoken_on_user_turn(state)
    return state
