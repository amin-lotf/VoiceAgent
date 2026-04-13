from voice_agent.core.types import CallState, NextAction


async def node_reset_gate(state: CallState):
    local_state = {
        "assistant_text": "",
        "assistant_streamed": False,
        "user_text": "", "meta": {},
        "next_action": NextAction.OTHER,
        'internal_call': True,
    }
    return local_state
