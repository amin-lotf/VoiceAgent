from __future__ import annotations

from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
import logging
from typing import Any

from voice_agent.const import DEFAULT_TZ, NOT_SPECIFIED
from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.graph.utils import run_non_interruptible
from voice_agent.core.services.appointments import update_active_appointment_details
from voice_agent.core.types import CallState, AppointmentDraft, AppointmentPatch, AppointmentView

logger = logging.getLogger(__name__)


OPENING_HOUR = 9
OPENING_MINUTE = 0

AFTERNOON_HOUR = 12
AFTERNOON_MINUTE = 0


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


def _combine_local(d: date, hour: int, minute: int, tz_info: ZoneInfo) -> datetime:
    return datetime.combine(d, time(hour=hour, minute=minute), tzinfo=tz_info)


def _is_business_day(d: date) -> bool:
    return d.weekday() < 5  # Mon-Fri


def _next_business_day(d: date) -> date:
    cur = d
    while not _is_business_day(cur):
        cur += timedelta(days=1)
    return cur


def _start_of_next_week(d: date) -> date:
    days_until_next_monday = 7 - d.weekday()
    if days_until_next_monday <= 0:
        days_until_next_monday += 7
    return d + timedelta(days=days_until_next_monday)


def _first_business_day_this_week_from(d: date) -> date | None:
    cur = d
    end = d + timedelta(days=(4 - d.weekday())) if d.weekday() <= 4 else d
    while cur <= end:
        if _is_business_day(cur):
            return cur
        cur += timedelta(days=1)
    return None


def _parse_exact_time_text(exact_time_text: str) -> tuple[int, int] | None:
    if not exact_time_text:
        return None

    text = exact_time_text.strip()
    parts = text.split(":")
    if len(parts) != 2:
        return None

    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    return hour, minute


def _schedule_patch_is_effectively_empty(schedule_patch: dict | None) -> bool:
    if not schedule_patch:
        return True

    date_mode = (schedule_patch.get("date_mode") or "").strip().lower()
    date_key = (schedule_patch.get("date_key") or "").strip().lower()
    time_pref = (schedule_patch.get("time_pref") or "").strip().lower()
    exact_time_text = (schedule_patch.get("exact_time_text") or "").strip().lower()

    empty_values = {"", "not_specified"}

    return (
        date_mode in empty_values
        and date_key in empty_values
        and time_pref in empty_values
        and exact_time_text in empty_values
    )


def _resolve_time_from_patch(schedule_patch: dict) -> tuple[int, int]:
    time_pref = (schedule_patch.get("time_pref") or "").strip().lower()
    exact_time_text = (schedule_patch.get("exact_time_text") or "").strip()

    if _is_not_specified(time_pref):
        return OPENING_HOUR, OPENING_MINUTE

    if time_pref == "morning":
        return OPENING_HOUR, OPENING_MINUTE

    if time_pref == "afternoon":
        return AFTERNOON_HOUR, AFTERNOON_MINUTE

    if time_pref == "exact_time":
        parsed = _parse_exact_time_text(exact_time_text)
        if parsed:
            return parsed
        return OPENING_HOUR, OPENING_MINUTE

    return OPENING_HOUR, OPENING_MINUTE


def _resolve_date_from_patch(
    *,
    schedule_patch: dict,
    now: datetime,
) -> date | None:
    date_mode = (schedule_patch.get("date_mode") or "").strip().lower()
    date_key = (schedule_patch.get("date_key") or "").strip()

    today = now.date()

    if date_mode == "specific_day" and not _is_not_specified(date_key):
        try:
            return date.fromisoformat(date_key)
        except ValueError:
            return None

    if date_mode == "next_week":
        return _start_of_next_week(today)

    if date_mode == "this_week":
        return _first_business_day_this_week_from(today)

    if date_mode == "earliest":
        return _next_business_day(today)

    if _is_not_specified(date_mode):
        return _next_business_day(today)

    return None


def resolve_requested_time(
    *,
    schedule_patch: dict | None,
    now: datetime,
    tz_info: ZoneInfo = DEFAULT_TZ,
) -> datetime | None:
    if not schedule_patch:
        return None

    if _schedule_patch_is_effectively_empty(schedule_patch):
        return None

    base_date = _resolve_date_from_patch(schedule_patch=schedule_patch, now=now)
    if base_date is None:
        return None

    hour, minute = _resolve_time_from_patch(schedule_patch)
    return _combine_local(base_date, hour, minute, tz_info)


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

    requested_time_text = patch.get("requested_time")
    if not _is_not_specified(requested_time_text):
        updated["requested_time_text"] = requested_time_text

    patch_notes = patch.get("notes")
    if patch_notes:
        updated["notes"] = _merge_notes(
            updated.get("notes"),
            patch_notes,
        )

    schedule_patch = patch.get("schedule_patch")
    resolved_requested_time = resolve_requested_time(
        schedule_patch=schedule_patch,
        now=now.astimezone(tz_info),
        tz_info=tz_info,
    )

    if resolved_requested_time is not None:
        updated["requested_time"] = resolved_requested_time.isoformat()

    last_offered_slot_start_at = patch.get("last_offered_slot_start_at")
    if not _is_not_specified(last_offered_slot_start_at):
        updated["last_offered_slot_start_at"] = last_offered_slot_start_at

    return updated


def _view_id(view: object) -> int | None:
    if not isinstance(view, dict):
        return None
    raw = view.get("id")
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


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

    if not _has_updatable_core_fields(updated_appointment):
        logger.warning("Skipping DB sync: appointment_draft still incomplete: %s", updated_appointment)
        return local_state

    held_view = state.get("current_appointment_view") or {}

    held_id = _view_id(held_view)

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