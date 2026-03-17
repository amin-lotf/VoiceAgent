from __future__ import annotations

from langgraph.config import get_stream_writer

from voice_agent.core.graph.nodes.utils import stream_text_response
from voice_agent.core.types import CallState, CallPhase


def node_on_call_ended(state: CallState) -> dict:
    """Cleanup node after hangups."""
    return {}

def node_handle_hangup(state: CallState) -> dict:
    text = "Thanks for calling. If you need anything else, reach out anytime."
    local_state = stream_text_response(text)
    local_state["end_call"] = True
    local_state["phase"] = CallPhase.DONE
    return local_state
