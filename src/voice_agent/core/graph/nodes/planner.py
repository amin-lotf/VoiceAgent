from voice_agent.core.types import CallState, AssistantDirective, ExtractorNode


def collect_directives(state: CallState) -> list[AssistantDirective]:
    node_data = state.get("node_data") or {}

    directives: list[AssistantDirective] = []

    for node in ExtractorNode:
        node_bucket = node_data.get(node.value) or {}
        directives.extend(node_bucket.get("directives") or [])

    directives.sort(key=lambda x: x.get("priority", 0), reverse=True)
    return directives


async def node_planner(state: CallState) -> dict:
    directives = collect_directives(state)
    return {
        'directives': directives,
    }