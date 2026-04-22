from __future__ import annotations

from typing import Any

from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.db.mappers import to_view
from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.graph.nodes.utils import get_state_data, view_id
from voice_agent.core.graph.utils import run_non_interruptible
from voice_agent.core.types import CallState, NextAction, AppointmentDraft, AppointmentPatch, AppointmentStatus, \
    AppointmentView, OperationStatus, AssistantPhase
import logging

logger = logging.getLogger(__name__)



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

async def node_verify_info(
        state: CallState,
        *,
        sessionmaker,
                           ) -> dict[str, Any]:
    next_action = state.get('next_action')
    # if next_action!=NextAction.CHECK_INFO:
    logger.warning(f'verify_info:next_action: {next_action}')
    return {}
    extractor_node_data = get_state_data(state, 'basic_info_extractor')
    node_status = extractor_node_data.get('node_status')
    if node_status == OperationStatus.FAILURE:
        logger.warning(f'basic_info: failed to extract info')
        raise Exception('basic_info: failed to extract info')
    appointment_patch: AppointmentPatch = extractor_node_data.get('appointment_patch') or {}
    if not appointment_patch:
        logger.warning(f'basic_info: empty info')
        raise Exception('basic_info: empty info')

    appointment_draft: AppointmentDraft = state.get("appointment_draft") or {}
    updated_appointment = apply_appointment_patch(
        appointment_draft=appointment_draft,
        appointment_patch=appointment_patch,
    )
    if not _has_updatable_core_fields(updated_appointment):
        logger.warning("Skipping DB sync: appointment_draft still incomplete: %s", updated_appointment)
        raise Exception('basic_info: incomplete info')
    local_state: dict[str, Any] = {
        "appointment_draft": updated_appointment,
        "next_action": NextAction.CALL_OPERATOR,
        "assistant_phase" : AssistantPhase.VERIFYING_INFO
    }


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

            synced_held_id = view_id(
                local_state.get("held_appointment_view") or state.get("held_appointment_view") or {})
            synced_scheduled_id = view_id(
                local_state.get("scheduled_appointment_view") or state.get("scheduled_appointment_view") or {}
            )
            local_state["current_appointment_id"] = synced_held_id or synced_scheduled_id

    except Exception:
        logger.exception("Failed to sync appointment details to DB")

    logger.warning("======\n basic_info: local state: %s \n ======", local_state)
    # logger.warning("======\n patch_resolver: state: %s \n ======", state)
    return local_state



