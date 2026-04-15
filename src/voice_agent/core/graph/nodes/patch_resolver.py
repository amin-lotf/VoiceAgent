from __future__ import annotations

import logging
from typing import Any

from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.db.mappers import to_view
from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.graph.nodes.utils import view_id, set_node_data
from voice_agent.core.graph.utils import run_non_interruptible
from voice_agent.core.types import CallState, AppointmentDraft, AppointmentPatch, AppointmentView, ConfirmationIntent, \
    UserIntent, AssistantPhase, AppointmentStatus

logger = logging.getLogger(__name__)

def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False

def _is_not_specified(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in {
        "",
        "not_specified",
        str(NOT_SPECIFIED).lower(),
    }:
        return True
    return False

def _is_confirmed(intent: ConfirmationIntent) -> bool:
    return intent == ConfirmationIntent.ACCEPT

def _merge_notes(
        current_notes: list[str] | None,
        patch_notes: list[str] | None,
) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()

    for item in (current_notes or []):
        text = str(item).strip()
        if text and text not in seen:
            merged.append(text)
            seen.add(text)

    for item in (patch_notes or []):
        text = str(item).strip()
        if text and text not in seen:
            merged.append(text)
            seen.add(text)

    return merged


def apply_appointment_patch(
        *,
        appointment_draft: AppointmentDraft,
        appointment_patch: AppointmentPatch,
) -> AppointmentDraft:
    updated: AppointmentDraft = dict(appointment_draft or {})
    patch: AppointmentPatch = dict(appointment_patch or {})

    for field in ("name", "phone", "reason_for_visit"):
        new_value = patch.get(field, NOT_SPECIFIED)
        if not _is_not_specified(new_value):
            updated[field] = new_value

    requested_time_text = patch.get("requested_time_text")
    if not _is_not_specified(requested_time_text):
        updated["requested_time_text"] = requested_time_text
        updated['offered_time_confirmed'] = False

    patch_notes = patch.get("notes")
    if patch_notes:
        updated["notes"] = _merge_notes(
            updated.get("notes"),
            patch_notes,
        )

    confirmation_intent = patch.get("confirmation_intent") or ConfirmationIntent.NOT_SPECIFIED
    if _is_confirmed(confirmation_intent):
        updated["offered_time_confirmed"] = True



    return updated


def _has_updatable_core_fields(draft: AppointmentDraft) -> bool:
    return all(
        not _is_not_specified(draft.get(field))
        for field in ("name", "phone", "reason_for_visit")
    )


def _build_sync_plan(
    *,
    appointment_status: AppointmentStatus | None,
    held_id: int | None,
    scheduled_id: int | None,
) -> list[tuple[str, int, bool]]:
    if appointment_status == AppointmentStatus.SCHEDULED:
        if scheduled_id is not None:
            return [("scheduled_appointment_view", scheduled_id, True)]
        if held_id is not None:
            return [("held_appointment_view", held_id, True)]
        return []

    plan: list[tuple[str, int, bool]] = []
    if held_id is not None:
        plan.append(("held_appointment_view", held_id, True))
    if scheduled_id is not None and scheduled_id != held_id:
        plan.append(("scheduled_appointment_view", scheduled_id, held_id is None))
    return plan


async def _update_active_view_from_draft(
    uow: SqlAlchemyUnitOfWork,
    *,
    appointment_id: int,
    appointment_draft: AppointmentDraft,
    include_notes: bool,
) -> AppointmentView:
    appt = await uow.appointments.get(appointment_id)
    if appt is None:
        raise ValueError(f"Appointment {appointment_id} not found")
    if appt.status not in (AppointmentStatus.HELD, AppointmentStatus.SCHEDULED):
        raise ValueError(f"Appointment {appointment_id} is not active")

    fields = {
        "name": str(appointment_draft["name"]),
        "phone": str(appointment_draft["phone"]),
        "reason_for_visit": str(appointment_draft["reason_for_visit"]),
    }
    if include_notes:
        fields["notes"] = list(appointment_draft.get("notes") or [])

    appt = await uow.appointments.update_fields(appointment_id, **fields)
    assert appt is not None
    return to_view(appt)


async def _sync_views_from_draft(
    state: CallState,
    *,
    sessionmaker,
    sync_plan: list[tuple[str, int, bool]],
    appointment_draft: AppointmentDraft,
) -> dict[str, AppointmentView]:
    async def _commit() -> dict[str, AppointmentView]:
        async with sessionmaker() as session:
            uow = SqlAlchemyUnitOfWork(session)
            async with uow:
                updated_views: dict[str, AppointmentView] = {}
                for state_key, appointment_id, include_notes in sync_plan:
                    updated_views[state_key] = await _update_active_view_from_draft(
                        uow,
                        appointment_id=appointment_id,
                        appointment_draft=appointment_draft,
                        include_notes=include_notes,
                    )
                return updated_views

    return await run_non_interruptible(state, _commit)


async def node_patch_resolver(
        state: CallState,
        *,
        sessionmaker,
) -> dict:
    appointment_draft: AppointmentDraft = state.get("appointment_draft") or {}
    appointment_patch: AppointmentPatch = state.get("appointment_patch") or {}

    updated_appointment = apply_appointment_patch(
        appointment_draft=appointment_draft,
        appointment_patch=appointment_patch,
    )


    local_state: dict[str, Any] = {
        "appointment_draft": updated_appointment,
    }
    user_intent = appointment_patch.get("user_intent")
    intent_updated = False
    if user_intent and user_intent != UserIntent.UNDECIDED and user_intent != state.get("user_intent"):
        local_state["user_intent"] = user_intent
        intent_updated = True
        local_state['assistant_phase'] = AssistantPhase.COLLECTING_INFO
    set_node_data(local_state, "patch_resolver", {"user_intent_updated": intent_updated})

    datetime_updated = not _is_missing(appointment_patch.get("requested_time_text"))



    set_node_data(local_state, "patch_resolver", {"datetime_updated": datetime_updated})

    if not _has_updatable_core_fields(updated_appointment):
        logger.warning("Skipping DB sync: appointment_draft still incomplete: %s", updated_appointment)
        return local_state

    held_view = state.get("held_appointment_view") or {}
    scheduled_view = state.get("scheduled_appointment_view") or {}
    held_id = view_id(held_view)
    scheduled_id = view_id(scheduled_view)
    sync_plan = _build_sync_plan(
        appointment_status=updated_appointment.get("status"),
        held_id=held_id,
        scheduled_id=scheduled_id,
    )

    try:
        if sync_plan:
            updated_views = await _sync_views_from_draft(
                state,
                sessionmaker=sessionmaker,
                sync_plan=sync_plan,
                appointment_draft=updated_appointment,
            )
            local_state.update(updated_views)

            synced_held_id = view_id(local_state.get("held_appointment_view") or state.get("held_appointment_view") or {})
            synced_scheduled_id = view_id(
                local_state.get("scheduled_appointment_view") or state.get("scheduled_appointment_view") or {}
            )
            local_state["current_appointment_id"] = synced_held_id or synced_scheduled_id

    except Exception:
        logger.exception("Failed to sync appointment details to DB")

    # logger.warning("======\n patch_resolver: local state: %s \n ======", local_state)
    # logger.warning("======\n patch_resolver: state: %s \n ======", state)
    return local_state
