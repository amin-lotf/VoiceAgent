from __future__ import annotations

from voice_agent.core.types import CallPhase, CallState
from .utils import ensure_spoken_on_user_turn


def node_handoff_fallback(state: CallState) -> CallState:
    state["assistant_text"] = (
        "I can help with scheduling right now. For anything else, I can have our staff call you back. "
        "What's the best phone number?"
    )
    state["phase"] = CallPhase.SLOT_FILL
    state["pending_question"] = "ask_phone"
    ensure_spoken_on_user_turn(state)
    return state
