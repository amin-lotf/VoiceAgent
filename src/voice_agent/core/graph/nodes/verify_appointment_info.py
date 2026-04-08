from typing import Any
from voice_agent.core.types import CallState, AppointmentDraft, AssistantPhase, \
    RequiredAppointmentField, NextAction
import logging

logger = logging.getLogger(__name__)

def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _is_draft_complete(draft: AppointmentDraft) -> bool:
    return all(not _is_missing(draft.get(field.value)) for field in RequiredAppointmentField)


async def node_verify_appointment_info(state: CallState) -> dict[str, Any]:
    draft: AppointmentDraft = state.get("appointment_draft", {})
    local_state ={}
    if _is_draft_complete(draft):
        local_state['assistant_phase'] = AssistantPhase.HOLDING_APPOINTMENT
        local_state['next_action'] = NextAction.HOLD_APPOINTMENT
        logger.warning('verify_appointment_info: appointment is complete, moving to finalize_response')
    else:
        local_state['next_action'] = NextAction.OTHER
        logger.warning('verify_appointment_info: appointment is incomplete, continuing to collect information')

    return local_state
