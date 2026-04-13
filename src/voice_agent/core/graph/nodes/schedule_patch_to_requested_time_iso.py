from __future__ import annotations

import logging
from datetime import datetime, date, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from voice_agent.const import DEFAULT_TZ, NOT_SPECIFIED
from voice_agent.core.graph.nodes.utils import set_node_data, get_state_data
from voice_agent.core.types import CallState, AppointmentDraft, OperationStatus, NextAction

logger = logging.getLogger(__name__)

# Conservative defaults
DAY_START_HOUR = 9
DAY_START_MINUTE = 0

MORNING_HOUR = 9
MORNING_MINUTE = 0

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


def _parse_iso_datetime(value: object, tz_info: ZoneInfo) -> datetime | None:
    if _is_not_specified(value):
        return None

    if not isinstance(value, str):
        return None

    raw = value.strip()
    if not raw:
        return None

    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz_info)

    return dt.astimezone(tz_info)


def _parse_iso_date(value: object) -> date | None:
    if _is_not_specified(value):
        return None

    if not isinstance(value, str):
        return None

    raw = value.strip()
    if not raw:
        return None

    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _parse_hhmm(value: object) -> tuple[int, int] | None:
    if _is_not_specified(value):
        return None

    if not isinstance(value, str):
        return None

    raw = value.strip()
    if not raw:
        return None

    try:
        parsed = datetime.strptime(raw, "%H:%M")
        return parsed.hour, parsed.minute
    except ValueError:
        return None


def _combine_local(d: date, hour: int, minute: int, tz_info: ZoneInfo) -> datetime:
    return datetime.combine(d, time(hour=hour, minute=minute), tzinfo=tz_info)


def _default_hour_minute_for_time_pref(time_pref: str) -> tuple[int, int]:
    if time_pref == "afternoon":
        return AFTERNOON_HOUR, AFTERNOON_MINUTE

    if time_pref == "morning":
        return MORNING_HOUR, MORNING_MINUTE

    # If user only chose a day, assume the beginning of the day.
    return DAY_START_HOUR, DAY_START_MINUTE


def _resolve_from_specific_day(
    *,
    date_key: str,
    time_pref: str,
    exact_time_text: str,
    tz_info: ZoneInfo,
) -> tuple[str | None, str]:
    resolved_date = _parse_iso_date(date_key)
    if resolved_date is None:
        return None, "specific_day_without_valid_date_key"

    exact_hhmm = _parse_hhmm(exact_time_text)
    if exact_hhmm is not None:
        hour, minute = exact_hhmm
        resolved = _combine_local(resolved_date, hour, minute, tz_info)
        return resolved.isoformat(), "resolved_specific_day_exact_time"

    hour, minute = _default_hour_minute_for_time_pref(time_pref)
    resolved = _combine_local(resolved_date, hour, minute, tz_info)

    if time_pref == "morning":
        return resolved.isoformat(), "resolved_specific_day_morning_default"

    if time_pref == "afternoon":
        return resolved.isoformat(), "resolved_specific_day_afternoon_default"

    return resolved.isoformat(), "resolved_specific_day_start_of_day_default"


def _resolve_from_relative_to_offered(
    *,
    relative_to_offered: str,
    last_offered_slot_start_at: str,
    tz_info: ZoneInfo,
) -> tuple[str | None, str]:
    offered_dt = _parse_iso_datetime(last_offered_slot_start_at, tz_info)
    if offered_dt is None:
        return None, "relative_requested_but_last_offered_missing"

    if relative_to_offered == "same_time":
        return offered_dt.isoformat(), "resolved_relative_same_time"

    if relative_to_offered == "next_day":
        return (offered_dt + timedelta(days=1)).isoformat(), "resolved_relative_next_day"

    if relative_to_offered == "previous_day":
        return (offered_dt - timedelta(days=1)).isoformat(), "resolved_relative_previous_day"

    # Still ambiguous unless you define a slot step.
    if relative_to_offered in {"earlier", "later"}:
        return None, f"relative_{relative_to_offered}_is_ambiguous"

    return None, "relative_to_offered_not_resolved"


def _next_monday(d: date) -> date:
    # Monday = 0
    days_ahead = (7 - d.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return d + timedelta(days=days_ahead)


def _resolve_from_broad_date_mode(
    *,
    date_mode: str,
    time_pref: str,
    now: datetime,
    tz_info: ZoneInfo,
) -> tuple[str | None, str]:
    local_now = now.astimezone(tz_info)
    today = local_now.date()

    hour, minute = _default_hour_minute_for_time_pref(time_pref)

    if date_mode == "next_week":
        target_date = _next_monday(today)
        resolved = _combine_local(target_date, hour, minute, tz_info)
        return resolved.isoformat(), "resolved_broad_next_week_to_start"

    if date_mode == "this_week":
        target_date = today
        resolved = _combine_local(target_date, hour, minute, tz_info)

        # If today's anchor already passed, move forward day by day.
        if resolved <= local_now:
            target_date = today + timedelta(days=1)
            resolved = _combine_local(target_date, hour, minute, tz_info)

        return resolved.isoformat(), "resolved_broad_this_week_to_start"

    if date_mode == "earliest":
        target_date = today
        resolved = _combine_local(target_date, hour, minute, tz_info)

        if resolved <= local_now:
            target_date = today + timedelta(days=1)
            resolved = _combine_local(target_date, hour, minute, tz_info)

        return resolved.isoformat(), "resolved_broad_earliest_to_start"

    return None, "broad_date_mode_not_resolved"


async def node_schedule_patch_to_requested_time_iso(
    state: CallState,
) -> dict[str, Any]:

    datetime_node_data= get_state_data(state,'datetime_extractor')
    node_status = datetime_node_data.get('node_status')
    if not node_status or node_status == OperationStatus.FAILURE:
        return {}


    now = datetime.now(DEFAULT_TZ)
    appointment: AppointmentDraft = dict(state.get("appointment_draft") or {})
    datetime_node = (state.get("node_data") or {}).get("datetime_extractor") or {}
    raw_patch = datetime_node.get("schedule_patch") or {}

    if not raw_patch:
        logger.warning("schedule_patch_to_requested_time_iso skipped: no schedule_patch")
        return {}

    date_mode = str(raw_patch.get("date_mode", NOT_SPECIFIED))
    date_key = str(raw_patch.get("date_key", NOT_SPECIFIED))
    time_pref = str(raw_patch.get("time_pref", NOT_SPECIFIED))
    exact_time_text = str(raw_patch.get("exact_time_text", NOT_SPECIFIED))
    relative_to_offered = str(raw_patch.get("relative_to_offered", NOT_SPECIFIED))

    last_offered_slot_start_at = str(
        appointment.get("last_offered_slot_start_at", NOT_SPECIFIED)
    )

    local_state: dict[str, Any] = {}
    updated_appointment = dict(appointment)

    requested_time_iso: str | None = None
    resolution_reason = "not_resolved"

    try:
        # 1) Absolute day-based resolution:
        # today / tomorrow / weekday / explicit day should already arrive as specific_day
        if date_mode == "specific_day":
            requested_time_iso, resolution_reason = _resolve_from_specific_day(
                date_key=date_key,
                time_pref=time_pref,
                exact_time_text=exact_time_text,
                tz_info=DEFAULT_TZ,
            )

        # 2) Relative-to-offered resolution
        elif not _is_not_specified(relative_to_offered):
            requested_time_iso, resolution_reason = _resolve_from_relative_to_offered(
                relative_to_offered=relative_to_offered,
                last_offered_slot_start_at=last_offered_slot_start_at,
                tz_info=DEFAULT_TZ,
            )

        # 3) Broad requests like earliest / this week / next week
        elif date_mode in {"earliest", "this_week", "next_week"}:
            requested_time_iso, resolution_reason = _resolve_from_broad_date_mode(
                date_mode=date_mode,
                time_pref=time_pref,
                now=now,
                tz_info=DEFAULT_TZ,
            )

        else:
            requested_time_iso = None
            resolution_reason = "no_resolvable_schedule_patch"

        if requested_time_iso:
            updated_appointment["requested_time_iso"] = requested_time_iso
            node_status = OperationStatus.SUCCESS
        else:
            updated_appointment["requested_time_iso"] = str(NOT_SPECIFIED)
            node_status = OperationStatus.FAILURE
            local_state['next_action'] = NextAction.CALL_OPERATOR

        local_state["appointment_draft"] = updated_appointment

        set_node_data(
            local_state,
            "schedule_patch_to_requested_time_iso",
            {
                'node_status': node_status,
            },
        )


        logger.warning(
            "schedule_patch_to_requested_time_iso resolved requested_time_iso=%r reason=%s",
            requested_time_iso,
            resolution_reason,
        )

        return local_state

    except Exception:
        logger.exception("schedule_patch_to_requested_time_iso failed")

        updated_appointment["requested_time_iso"] = str(NOT_SPECIFIED)
        local_state["appointment_draft"] = updated_appointment

        set_node_data(
            local_state,
            "schedule_patch_to_requested_time_iso",
            {
                "node_status": OperationStatus.FAILURE
            },
        )
        return local_state