from voice_agent.core.graph.nodes.utils import reset_node_data
from voice_agent.core.turn_signals import looks_like_schedule_change
from voice_agent.core.types import (
    CallState,
    AssistantDirective,
    DirectiveSourceNode,
    AssistantPhase,
    AppointmentStatus,
)
import logging

logger = logging.getLogger(__name__)

def reset_directive_node_data(state: dict) -> None:
    for node in DirectiveSourceNode:
        reset_node_data(state, node.value)

def _should_skip_node_for_current_turn(state: CallState, node: DirectiveSourceNode) -> bool:
    user_text = (state.get("user_text") or "").strip()
    if not user_text or not looks_like_schedule_change(user_text):
        return False

    appointment_draft = state.get("appointment_draft") or {}
    assistant_phase = state.get("assistant_phase")
    appointment_status = appointment_draft.get("status")

    if node == DirectiveSourceNode.HELD_APPOINTMENT_INFO:
        return (
            assistant_phase == AssistantPhase.HOLDING_APPOINTMENT
            or appointment_status == AppointmentStatus.HELD
        )

    if node in {DirectiveSourceNode.BOOK_APPOINTMENT, DirectiveSourceNode.NOTE_INFO}:
        return (
            assistant_phase == AssistantPhase.POST_APPOINTMENT
            or appointment_status == AppointmentStatus.SCHEDULED
        )

    return False

def collect_directives(state: CallState) -> list[AssistantDirective]:
    node_data = state.get("node_data") or {}

    # First: check if any node wants exclusive control
    for node in DirectiveSourceNode:
        if _should_skip_node_for_current_turn(state, node):
            continue
        node_bucket = node_data.get(node.value) or {}
        if node_bucket.get("exclusive_directives"):
            directives = list(node_bucket.get("directives") or [])
            directives.sort(key=lambda x: x.get("priority", 0), reverse=True)
            return directives

    # Fallback: merge all directives
    directives: list[AssistantDirective] = []

    for node in DirectiveSourceNode:
        if _should_skip_node_for_current_turn(state, node):
            continue
        node_bucket = node_data.get(node.value) or {}
        directives.extend(node_bucket.get("directives") or [])

    directives.sort(key=lambda x: x.get("priority", 0), reverse=True)
    return directives


async def node_planner(state: CallState) -> dict:
    directives = collect_directives(state)
    local_state = {'directives': directives}
    reset_directive_node_data(local_state)
    logger.warning(f"=====\nplanner:directives: {directives}\n=====")
    return local_state
