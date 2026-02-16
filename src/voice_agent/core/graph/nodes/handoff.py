from __future__ import annotations

from langgraph.config import get_stream_writer

from voice_agent.core.types import CallPhase, CallState, ClinicIntent
from .utils import ensure_spoken_on_user_turn

EMERGENCY_FALLBACK_MESSAGE = (
    "I'm not able to help with medical emergencies. "
    "I'll connect you with our emergency services right away."
)


def node_handoff_fallback(state: CallState) -> CallState:
    if state.get('intent') == ClinicIntent.TRIAGE:
        state["assistant_text"] = EMERGENCY_FALLBACK_MESSAGE
    else:
        state["assistant_text"] = "I Will have our staff call you back."
    writer = get_stream_writer()
    if writer:
        for word in state["assistant_text"].split():
            writer(("assistant_token", word + " "))
        state["assistant_streamed"] = True
    state["end_call"] = True
    ensure_spoken_on_user_turn(state)
    return state
