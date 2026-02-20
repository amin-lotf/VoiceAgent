from __future__ import annotations

from langgraph.config import get_stream_writer

from voice_agent.core.types import  CallState



def node_fill_appointment_slot(state: CallState) -> CallState:
    appointment = state.get("appointment") or {}
    text = "do you have a preferred date and time?"
    state["assistant_text"] = text
    writer = get_stream_writer()
    if writer:
        for word in text.split():
            writer(("assistant_token", word + " "))
        state["assistant_streamed"] = True
    return state
