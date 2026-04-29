from voice_agent.const import GLOBAL_ERROR_THRESHOLD, CONSECUTIVE_ERROR_THRESHOLD
from voice_agent.core.graph.nodes.utils import stream_text_response, set_node_data
from voice_agent.core.types import CallState, NextAction, ErrorType
import logging

logger = logging.getLogger(__name__)

def node_error_handling(state: CallState) -> dict:
    node_data = state.get("node_data", {})

    err = node_data.get("error_handling", {})
    counters = node_data.get("error_counters", {})
    local_state: dict = {}
    if not err.get("has_error"):
        local_state.update(
            stream_text_response(
                "Sorry, I’m having trouble completing this. Let me connect you to someone who can help."
            )
        )

        set_node_data(
            local_state,
            "error_handling",
            {
                "next_node": 'handoff_fallback',
            },
        )
        logger.warning(
            f"Error handling called without error data",
            extra={
                'call_id': state.get('call_id'),
                'phase': state.get('assistant_phase'),
                'node': 'error_handling',

            }
        )
        return local_state

    failed_node = err.get("failed_node")
    error_type = err.get("error_type")

    global_count = counters.get("global_error_count", 0)
    node_counters = counters.get("by_node", {}).get(failed_node, {})
    consecutive = node_counters.get("consecutive", 0)

    # --- decision ---
    should_handoff = (
        global_count >= GLOBAL_ERROR_THRESHOLD
        or consecutive >= CONSECUTIVE_ERROR_THRESHOLD
        or error_type == ErrorType.FATAL_ERROR
    )


    already_spoken = err.get("spoken_once", False)
    # --- speak only if retry ---
    if not should_handoff:
        if not already_spoken:
            local_state.update(
                stream_text_response("Sorry, one moment while I try that again.")
            )
        set_node_data(
            local_state,
            "error_handling",
            {
                "next_node": failed_node,
            },
        )
        # route back to failed node
        local_state["next_node"] = failed_node
        local_state['next_action'] = NextAction.RETRY_ACTION
        logger.warning(
            f"Retrying failed node: {failed_node}",
            extra={
                'call_id': state.get('call_id'),
                'phase': state.get('assistant_phase'),
                'node': 'error_handling',

            }
        )

    else:
        local_state.update(
            stream_text_response(
                "Sorry, I’m having trouble completing this. Let me connect you to someone who can help."
            )
        )

        set_node_data(
            local_state,
            "error_handling",
            {
                "next_node": 'handoff_fallback',
            },
        )
        logger.critical(
            f"Failed to handle by retrying node {failed_node}, handing off the call.",
            extra={
                'call_id': state.get('call_id'),
                'phase': state.get('assistant_phase'),
                'node': 'error_handling',

            }
        )
    return local_state