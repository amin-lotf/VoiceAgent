from voice_agent.core.types import CommunicationState


async def node_wait_start(state: CommunicationState) -> CommunicationState:
    return state