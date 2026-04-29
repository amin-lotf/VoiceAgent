from __future__ import annotations

import logging

from voice_agent.core.types import CallEvent, CallPhase, CallState

logger = logging.getLogger(__name__)






def node_route_event(state: CallState) -> CallState:
    """
    Lightweight router based on the incoming webhook event.
    Keeps state mutations minimal; downstream conditional edges handle branching.
    """
    # Clear any previous response so downstream checks use fresh text.
    state["assistant_text"] = ""
    event = state.get("event")
    if event == CallEvent.CALL_STARTED:
        state["phase"] = CallPhase.GREETING
    elif event == CallEvent.CALL_ENDED:
        state["end_call"] = True
        state["phase"] = CallPhase.DONE
    else:
        state["phase"] = CallPhase.INTENT_ROUTING
    logger.info(
        f'Call phase: {state["phase"]}',
        extra={
            'call_id': state.get('call_id'),
            'phase': state.get('assistant_phase'),
            'node': 'route_event',
        })
    return state






