from typing import Any
from voice_agent.core.types import CallState, AppointmentDraft, AssistantPhase, AppointmentField


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _is_draft_complete(draft: AppointmentDraft) -> bool:
    return all(not _is_missing(draft.get(field.value)) for field in AppointmentField)


async def node_verify_appointment_info(state: CallState) -> dict[str, Any]:
    draft: AppointmentDraft = state.get("appointment_draft", {})

    if _is_draft_complete(draft):
        return {
            "assistant_phase": AssistantPhase.FINALIZING_APPOINTMENT
        }

    return {
        "assistant_phase": AssistantPhase.COLLECTING_INFO
    }