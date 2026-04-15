from voice_agent.core.types import CallState, NextAction


async def node_reset_gate(state: CallState):
    prev_assistant_text = state.get("assistant_text") or ""
    prev_user_text = state.get("user_text") or ""
    local_state = {
        "assistant_text": "",
        "assistant_streamed": False,
        "user_text": "", "meta": {},
        "next_action": NextAction.OTHER,
        'internal_call': True,
        'prev_assistant_text': prev_assistant_text,
        'prev_user_text': prev_user_text,
    }
    return local_state
