from __future__ import annotations

from typing import Any

from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.db.mappers import to_view
from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.graph.nodes.utils import get_state_data, view_id, set_node_data, is_not_specified
from voice_agent.core.graph.utils import run_non_interruptible, record_node_error, mark_node_succeeded, \
    prep_internal_operator_call
from voice_agent.core.services.hubspot_sync import enqueue_hubspot_appointment_scheduled_event
from voice_agent.core.types import CallState, NextAction, AppointmentDraft, AppointmentPatch, AppointmentStatus, \
    AppointmentView, OperationStatus, AssistantPhase, FieldChange, RequiredAppointmentField, ErrorType
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


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


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


def _normalize_change_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.lower() in {"not_specified", str(NOT_SPECIFIED).lower()}:
            return None
        return text
    return str(value).strip() or None


def build_field_changes(
        *,
        before: AppointmentDraft,
        after: AppointmentDraft,
        source_node: str,
) -> list[FieldChange]:
    changes: list[FieldChange] = []

    for field in RequiredAppointmentField:
        old_value = _normalize_change_value(before.get(field.value, ))
        new_value = _normalize_change_value(after.get(field.value))

        if new_value is None:
            continue

        if old_value is None:
            changes.append(
                {
                    "field": field.value,
                    "old_value": None,
                    "new_value": new_value,
                    "action": "added",
                    "source_node": source_node,
                }
            )
            continue

        if old_value != new_value:
            changes.append(
                {
                    "field": field,
                    "old_value": old_value,
                    "new_value": new_value,
                    "action": "updated",
                    "source_node": source_node,
                }
            )

    return changes


def apply_appointment_patch(
        *,
        appointment_draft: AppointmentDraft,
        appointment_patch: AppointmentPatch,
) -> AppointmentDraft:
    updated: AppointmentDraft = dict(appointment_draft or {})
    patch: AppointmentPatch = dict(appointment_patch or {})
    for field in ("name", "phone", "reason_for_visit"):
        new_value = patch.get(field, NOT_SPECIFIED)
        if not is_not_specified(new_value):
            updated[field] = new_value
    requested_time_text = patch.get("requested_time_text")
    if not is_not_specified(requested_time_text):
        updated["requested_time_text"] = requested_time_text

    patch_notes = patch.get("notes")
    if patch_notes:
        updated["notes"] = _merge_notes(
            updated.get("notes"),
            patch_notes,
        )
    return updated


def _has_updatable_core_fields(draft: AppointmentDraft) -> bool:
    return all(
        not is_not_specified(draft.get(field))
        for field in ("name", "phone", "reason_for_visit")
    )


def _missing_required_fields(draft: AppointmentDraft) -> list:
    return [field.value for field in RequiredAppointmentField if is_not_specified(draft.get(field))]


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
    if appt.status == AppointmentStatus.SCHEDULED:
        await enqueue_hubspot_appointment_scheduled_event(
            uow,
            appointment_id=appt.id,
            delay_seconds=0,
        )
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


async def node_basic_info(
        state: CallState,
        *,
        sessionmaker,
) -> dict[str, Any]:
    local_state = {}
    set_node_data(
        local_state,
        "basic_info",
        {
            "field_changes": [],
        },
    )
    next_action = state.get('next_action')
    if next_action not in (NextAction.CHECK_INFO, NextAction.RETRY_ACTION):
        if next_action == NextAction.MARK_VERIFIED:
            local_state['assistant_phase'] = AssistantPhase.CONFIRMING_SLOT
            local_state['next_action'] = NextAction.EXTRACT_DATETIME
            local_state['messages'] = []
            logger.info(
                f'Info verified',
                extra={
                    'call_id': state.get('call_id'),
                    'phase':state.get('assistant_phase'),
                    'node': 'basic_info',
                })
        logger.info(
            f'Next action: {next_action}',
            extra={
                'call_id': state.get('call_id'),
                'phase': state.get('assistant_phase'),
                'node': 'basic_info',
            })
        return local_state
    extractor_node_data = get_state_data(state, 'basic_info_extractor')
    appointment_patch: AppointmentPatch = extractor_node_data.get('appointment_patch') or {}
    appointment_draft: AppointmentDraft = state.get("appointment_draft") or {}
    updated_appointment = apply_appointment_patch(
        appointment_draft=appointment_draft,
        appointment_patch=appointment_patch,
    )

    field_changes = build_field_changes(
        before=appointment_draft,
        after=updated_appointment,
        source_node="basic_info",
    )

    # if True:
    if not _has_updatable_core_fields(updated_appointment):
        local_state.update(prep_internal_operator_call(state, clear_messages=False))
        local_state['assistant_phase'] = AssistantPhase.COLLECTING_INFO
        missing_fields = _missing_required_fields(updated_appointment)
        set_node_data(local_state, "basic_info", {"missing_required_fields": missing_fields})
        logger.warning(
            f'Verification incomplete: missing fields: {missing_fields}',
            extra={
                'call_id': state.get('call_id'),
                'phase': state.get('assistant_phase'),
                'node': 'basic_info',
            })
        return local_state
    local_state.update(prep_internal_operator_call(state, clear_messages=True))
    local_state['appointment_draft'] = updated_appointment
    local_state['assistant_phase'] = AssistantPhase.VERIFYING_INFO

    set_node_data(
        local_state,
        "basic_info",
        {
            "field_changes": field_changes,
        },
    )

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
        mark_node_succeeded(state, local_state, "basic_info")
        logger.info(
            f'Info updated',
            extra={
                'call_id': state.get('call_id'),
                'phase': state.get('assistant_phase'),
                'node': 'basic_info',
            })
        return local_state

    except Exception as exc:
        local_state.update(
            record_node_error(
                state,
                node_name="basic_info",
                error_type=ErrorType.DB_ERROR,
                error_message=str(exc)
            )
        )
        local_state['next_action'] = NextAction.REPORT_ERROR
        logger.exception(
            f'Failed to update info: {str(exc)[:128]}',
            extra={
                'call_id': state.get('call_id'),
                'phase': state.get('assistant_phase'),
                'node': 'basic_info',
            })
        return local_state
