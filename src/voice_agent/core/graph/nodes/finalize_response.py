from __future__ import annotations

from voice_agent.core.graph.nodes.utils import ensure_spoken_on_user_turn
from voice_agent.core.types import CallState


def node_finalize_response(state: CallState) -> dict:
    """
    Ensures a spoken response exists before ending a USER_TURN.
    """
    local_state=ensure_spoken_on_user_turn(state)
    local_state['prev_user_text'] = state.get('user_text')
    local_state['prev_assistant_text'] = state.get('assistant_text')
    return local_state
