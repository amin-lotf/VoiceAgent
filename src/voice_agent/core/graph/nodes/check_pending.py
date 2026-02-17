from voice_agent.core.types import CallState, ClinicIntent


async def node_check_pending(state: CallState) -> CallState:
    pending_intent = state.get("pending_intent")
    if pending_intent:
        state["intent"] = pending_intent
        state["pending_intent"] = None
        return state
    state["intent"] = ClinicIntent.CLARIFY
    return state
