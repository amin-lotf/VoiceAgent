from typing import Any

from voice_agent.core.types import CallState, AppointmentDraft, NextAction


async def node_monitor_appointment_confirmation(state: CallState) -> dict[str, Any]:
    local_state ={}
    appointment_draft: AppointmentDraft = dict(state.get("appointment_draft") or {})
    offered_time_confirmed = appointment_draft.get('offered_time_confirmed') or False
    if offered_time_confirmed:
        local_state['next_action'] = NextAction.BOOK_APPOINTMENT
    else:
        local_state['next_action'] =NextAction.OTHER
    return local_state