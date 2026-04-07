from __future__ import annotations

from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
import logging
from typing import Any

from voice_agent.const import DEFAULT_TZ, NOT_SPECIFIED
from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.graph.nodes.utils import view_id, set_node_data
from voice_agent.core.graph.utils import run_non_interruptible
from voice_agent.core.services.appointments import update_active_appointment_details
from voice_agent.core.types import CallState, AppointmentDraft, AppointmentPatch, AppointmentView, ConfirmationIntent

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


def _combine_local(d: date, hour: int, minute: int, tz_info: ZoneInfo) -> datetime:
    return datetime.combine(d, time(hour=hour, minute=minute), tzinfo=tz_info)


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
        now: datetime,
        tz_info: ZoneInfo = DEFAULT_TZ,
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


async def _sync_view_from_draft(
        state: CallState,
        *,
        sessionmaker,
        appointment_id: int,
        appointment_draft: AppointmentDraft,
) -> AppointmentView:
    async def _commit() -> AppointmentView:
        async with sessionmaker() as session:
            uow = SqlAlchemyUnitOfWork(session)
            return await update_active_appointment_details(
                uow,
                appointment_id=appointment_id,
                name=str(appointment_draft["name"]),
                phone=str(appointment_draft["phone"]),
                reason_for_visit=str(appointment_draft["reason_for_visit"]),
                notes=list(appointment_draft.get("notes") or []),
            )

    return await run_non_interruptible(state, _commit)


async def node_patch_resolver(
        state: CallState,
        *,
        sessionmaker,
) -> dict:
    appointment_draft: AppointmentDraft = state.get("appointment_draft") or {}
    appointment_patch: AppointmentPatch = state.get("appointment_patch") or {}

    now = datetime.now(DEFAULT_TZ)

    updated_appointment = apply_appointment_patch(
        appointment_draft=appointment_draft,
        appointment_patch=appointment_patch,
        now=now,
        tz_info=DEFAULT_TZ,
    )



    local_state: dict[str, Any] = {
        "appointment_draft": updated_appointment,
    }
    datetime_updated = not _is_missing(updated_appointment.get("requested_time_text"))

    if datetime_updated:
        set_node_data(local_state, "patch_resolver", {"datetime_updated": datetime_updated})

    if not _has_updatable_core_fields(updated_appointment):
        logger.warning("Skipping DB sync: appointment_draft still incomplete: %s", updated_appointment)
        return local_state

    held_view = state.get("current_appointment_view") or {}

    held_id = view_id(held_view)

    try:
        if held_id is not None:
            updated_held = await _sync_view_from_draft(
                state,
                sessionmaker=sessionmaker,
                appointment_id=held_id,
                appointment_draft=updated_appointment,
            )
            local_state["current_appointment_view"] = updated_held

    except Exception:
        logger.exception("Failed to sync appointment details to DB")

    logger.warning("appointment_draft: %s", updated_appointment)
    return local_state
