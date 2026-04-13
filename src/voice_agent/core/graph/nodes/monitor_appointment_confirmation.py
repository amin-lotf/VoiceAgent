from typing import Any

from voice_agent.core.types import CallState, AppointmentDraft, NextAction, AssistantPhase


async def node_monitor_appointment_status(state: CallState) -> dict[str, Any]:
    local_state ={}
    appointment_draft: AppointmentDraft = dict(state.get("appointment_draft") or {})
    offered_time_confirmed = appointment_draft.get('offered_time_confirmed') or False
    assistant_phase = state.get('assistant_phase')
    if assistant_phase== AssistantPhase.HOLDING_APPOINTMENT and offered_time_confirmed:
        local_state['next_action'] = NextAction.BOOK_APPOINTMENT
    elif assistant_phase== AssistantPhase.POST_APPOINTMENT:
        local_state['next_action'] = NextAction.TAKE_NOTE
    else:
        local_state['next_action'] =NextAction.OTHER
    return local_state