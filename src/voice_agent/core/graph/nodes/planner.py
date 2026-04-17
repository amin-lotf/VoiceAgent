from voice_agent.core.graph.nodes.utils import reset_node_data
from voice_agent.core.types import (
    CallState,
    AssistantDirective,
    DirectiveSourceNode,
    AssistantPhase,
    AppointmentStatus,
)
import logging

logger = logging.getLogger(__name__)

def reset_directive_node_data(state: dict, previous_state: CallState) -> None:
    for node in DirectiveSourceNode:
        reset_node_data(state, node.value, preserve_from=previous_state)


def collect_directives(state: CallState) -> list[AssistantDirective]:
    node_data = state.get("node_data") or {}

    # First: check if any node wants exclusive control
    for node in DirectiveSourceNode:
        node_bucket = node_data.get(node.value) or {}
        if node_bucket.get("exclusive_directives"):
            directives = list(node_bucket.get("directives") or [])
            directives.sort(key=lambda x: x.get("priority", 0), reverse=True)
            return directives

    # Fallback: merge all directives
    directives: list[AssistantDirective] = []

    for node in DirectiveSourceNode:
        node_bucket = node_data.get(node.value) or {}
        directives.extend(node_bucket.get("directives") or [])

    directives.sort(key=lambda x: x.get("priority", 0), reverse=True)
    return directives


async def node_planner(state: CallState) -> dict:
    directives = collect_directives(state)
    local_state = {'directives': directives}
    reset_directive_node_data(local_state, state)
    logger.warning(f"=====\nplanner:directives: {directives}\n=====")
    return local_state
