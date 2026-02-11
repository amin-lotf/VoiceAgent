from __future__ import annotations

from voice_agent.core.types import CallPhase, CallState
from .utils import ensure_appointment


def node_on_call_started(state: CallState) -> CallState:
    """Initial greeting when the call is first connected."""
    ensure_appointment(state)
    state["phase"] = CallPhase.INTENT_ROUTING
    state["pending_question"] = None
    state["assistant_text"] = (
        "Hi, thanks for calling. How can I help you today? "
        "You can say things like book an appointment, reschedule, or ask about office hours."
    )
    state["intent"] = None
    return state
