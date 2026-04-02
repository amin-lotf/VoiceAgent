from voice_agent.core.types import CallState, AssistantDirective, ExtractorNode
import logging

logger = logging.getLogger(__name__)

def collect_directives(state: CallState) -> list[AssistantDirective]:
    node_data = state.get("node_data") or {}

    # First: check if any node wants exclusive control
    for node in ExtractorNode:
        node_bucket = node_data.get(node.value) or {}
        if node_bucket.get("exclusive_directives"):
            directives = list(node_bucket.get("directives") or [])
            directives.sort(key=lambda x: x.get("priority", 0), reverse=True)
            return directives

    # Fallback: merge all directives
    directives: list[AssistantDirective] = []

    for node in ExtractorNode:
        node_bucket = node_data.get(node.value) or {}
        directives.extend(node_bucket.get("directives") or [])

    directives.sort(key=lambda x: x.get("priority", 0), reverse=True)
    return directives


async def node_planner(state: CallState) -> dict:
    directives = collect_directives(state)
    logger.warning(f"plannder:directives: {directives}")
    return {
        "directives": directives,
    }