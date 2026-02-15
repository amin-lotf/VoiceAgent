from __future__ import annotations

from langgraph.config import get_stream_writer

from voice_agent.core.types import CallState, CallPhase


def node_on_call_ended(state: CallState) -> CallState:
    """Cleanup node after hangups."""
    return state

def node_handle_hangup(state: CallState) -> CallState:
    text = "Thanks for calling. If you need anything else, reach out anytime."
    state["assistant_text"] = text
    writer = get_stream_writer()
    if writer:
        for word in text.split():
            writer(("assistant_token", word + " "))
        state["assistant_streamed"] = True
    state["end_call"] = True
    state["phase"] = CallPhase.DONE
    return state
