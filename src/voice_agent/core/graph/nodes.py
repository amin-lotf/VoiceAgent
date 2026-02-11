from voice_agent.core.types import CallState


async def node_wait_start(state: CallState) -> CallState:
    return state