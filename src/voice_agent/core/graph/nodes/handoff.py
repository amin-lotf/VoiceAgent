from __future__ import annotations

from langgraph.config import get_stream_writer
import logging
from voice_agent.core.types import CallPhase, CallState, AssistantIntent
from .utils import ensure_spoken_on_user_turn

logger = logging.getLogger(__name__)


def node_handoff_fallback(state: CallState) -> CallState:
    state["assistant_text"] = "I Will have our staff call you back. Goodbye."
    writer = get_stream_writer()
    if writer:
        for word in state["assistant_text"].split():
            writer(("assistant_token", word + " "))
        state["assistant_streamed"] = True
    state["end_call"] = True
    ensure_spoken_on_user_turn(state)
    logger.info(
        'Handoff the the call to the staff',
        extra={
            'call_id': state.get('call_id'),
            'phase': state.get('assistant_phase'),
            'node': 'handoff',
        }
    )
    return state
