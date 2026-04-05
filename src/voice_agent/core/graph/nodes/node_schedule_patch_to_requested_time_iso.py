from __future__ import annotations

import logging
from datetime import datetime, date, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from voice_agent.const import DEFAULT_TZ, NOT_SPECIFIED
from voice_agent.core.graph.nodes.utils import set_node_data
from voice_agent.core.types import CallState, AppointmentDraft

logger = logging.getLogger(__name__)

# Conservative defaults for vague time preferences
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

    if time_pref == "morning":
        resolved = _combine_local(
            resolved_date,
            MORNING_HOUR,
            MORNING_MINUTE,
            tz_info,
        )
        return resolved.isoformat(), "resolved_specific_day_morning_default"

    if time_pref == "afternoon":
        resolved = _combine_local(
            resolved_date,
            AFTERNOON_HOUR,
            AFTERNOON_MINUTE,
            tz_info,
        )
        return resolved.isoformat(), "resolved_specific_day_afternoon_default"

    return None, "specific_day_without_exact_or_defaultable_time"


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

    # "earlier" / "later" are still ambiguous without a slot interval or concrete rule.
    if relative_to_offered in {"earlier", "later"}:
        return None, f"relative_{relative_to_offered}_is_ambiguous"

    return None, "relative_to_offered_not_resolved"


async def node_schedule_patch_to_requested_time_iso(
    state: CallState,
) -> dict[str, Any]:
    tz_info: ZoneInfo = DEFAULT_TZ
    appointment: AppointmentDraft = dict(state.get("appointment_draft") or {})

    datetime_node = (state.get("node_data") or {}).get("datetime_extractor") or {}
    raw_patch = datetime_node.get("schedule_patch") or {}

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
        # 1) Absolute day-based resolution
        if date_mode == "specific_day":
            requested_time_iso, resolution_reason = _resolve_from_specific_day(
                date_key=date_key,
                time_pref=time_pref,
                exact_time_text=exact_time_text,
                tz_info=tz_info,
            )

        # 2) Relative-to-offered resolution
        elif not _is_not_specified(relative_to_offered):
            requested_time_iso, resolution_reason = _resolve_from_relative_to_offered(
                relative_to_offered=relative_to_offered,
                last_offered_slot_start_at=last_offered_slot_start_at,
                tz_info=tz_info,
            )

        # 3) Broad requests remain unresolved on purpose
        elif date_mode in {"earliest", "this_week", "next_week"}:
            requested_time_iso = None
            resolution_reason = f"broad_request_{date_mode}_left_unresolved"

        else:
            requested_time_iso = None
            resolution_reason = "no_resolvable_schedule_patch"

        if requested_time_iso:
            updated_appointment["requested_time_iso"] = requested_time_iso
        else:
            # optional: explicitly mark unresolved
            updated_appointment["requested_time_iso"] = str(NOT_SPECIFIED)

        local_state["appointment_draft"] = updated_appointment

        set_node_data(
            local_state,
            "schedule_patch_to_requested_time_iso",
            {
                "requested_time_iso": requested_time_iso or str(NOT_SPECIFIED),
                "resolution_reason": resolution_reason,
                "schedule_patch": {
                    "date_mode": date_mode,
                    "date_key": date_key,
                    "time_pref": time_pref,
                    "exact_time_text": exact_time_text,
                    "relative_to_offered": relative_to_offered,
                },
            },
        )

        logger.warning(
            "schedule_patch_to_requested_time_iso resolved requested_time_iso=%r reason=%s",
            requested_time_iso,
            resolution_reason,
        )

        return local_state

    except Exception:
        logger.warning("schedule_patch_to_requested_time_iso failed")

        updated_appointment["requested_time_iso"] = str(NOT_SPECIFIED)
        local_state["appointment_draft"] = updated_appointment

        set_node_data(
            local_state,
            "schedule_patch_to_requested_time_iso",
            {
                "requested_time_iso": str(NOT_SPECIFIED),
                "resolution_reason": "exception",
            },
        )
        return local_state