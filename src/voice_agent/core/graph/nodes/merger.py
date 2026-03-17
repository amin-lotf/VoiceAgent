from voice_agent.core.types import CallState, AppointmentDraft, AppointmentPatch
import logging

logger = logging.getLogger(__name__)

NOT_SPECIFIED = "not_specified"


def apply_appointment_patch(
    *,
    appointment_draft: AppointmentDraft,
    appointment_patch: AppointmentPatch,
) -> dict:
    updated = dict(appointment_draft or {})
    patch = dict(appointment_patch or {})

    for field in ("name", "phone", "reason_for_visit"):
        new_value = patch.get(field, NOT_SPECIFIED)

        # only overwrite when model explicitly sent a real new value
        if new_value != NOT_SPECIFIED:
            updated[field] = new_value

    dt_value = patch.get("requested_time_text", NOT_SPECIFIED)
    if dt_value != NOT_SPECIFIED:
        updated["requested_time_text"] = dt_value

    return updated


def node_merger(state: CallState) -> dict:
    appointment_draft = state.get("appointment_draft") or {}
    appointment_patch = state.get("appointment_patch") or {}
    updated_appointment =apply_appointment_patch(
        appointment_draft=appointment_draft,
        appointment_patch=appointment_patch)
    local_state:dict= {
        "appointment_draft":updated_appointment }
    logger.warning(f"appointment_draft:{updated_appointment}")
    return local_state