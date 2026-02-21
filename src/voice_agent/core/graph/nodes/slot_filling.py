from __future__ import annotations

import json
from datetime import datetime, timedelta, time
from typing import Any
from zoneinfo import ZoneInfo

from langgraph.config import get_stream_writer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.llm.openai_llm import LLM
from voice_agent.core.services.appointments import hold_slot, list_free_slots
from voice_agent.core.services.exceptions import SlotNotAvailable
from voice_agent.core.types import CallPhase, CallState, ClinicIntent, TimeSlot
from voice_agent.core.prompts.slot_filling import build_slot_fill_prompt
from .utils import normalize_phone, safe_json_parse
import logging

from ...settings import settings

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Taipei")
DEFAULT_SEARCH_DAYS = 7
EXPANDED_SEARCH_DAYS = 14






def _merge_patch(state: CallState, patch: dict) -> None:
    appt = state.setdefault("appointment_create", {})
    notes_append = patch.get("notes_append")
    if isinstance(notes_append, list):
        notes = appt.setdefault("notes", [])
        for note in notes_append:
            if isinstance(note, str) and note.strip():
                notes.append(note.strip())

    for key in ("name", "phone", "reason_for_visit"):
        val = patch.get(key)
        if isinstance(val, str) and val.strip():
            if key == "phone":
                norm = normalize_phone(val)
                if norm:
                    appt[key] = norm
            else:
                appt[key] = val.strip()


def _is_complete(appointment: dict) -> bool:
    if not appointment.get("name"):
        return False
    if not appointment.get("phone"):
        return False
    if not appointment.get("reason_for_visit"):
        return False
    return isinstance(appointment.get("start_at"), datetime) and isinstance(appointment.get("end_at"), datetime)


def _format_dt(dt: datetime) -> str:
    if not isinstance(dt, datetime):
        return ""
    local_dt = dt.astimezone(TZ)
    try:
        return local_dt.strftime("%A, %b %-d at %-I:%M %p")
    except Exception:
        # Windows-compatible (no %-d)
        return local_dt.strftime("%A, %b %d at %I:%M %p").lstrip("0").replace(" 0", " ")


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=TZ)
        return value.astimezone(TZ)
    if isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip())
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ)
            return dt.astimezone(TZ)
        except Exception:
            return None
    return None


def _coerce_int(val: Any, default: int) -> int:
    try:
        return int(val)
    except Exception:
        return default


def _get_now(state: CallState) -> datetime:
    meta = state.get("meta") or {}
    meta_now = meta.get("now")
    dt = _parse_dt(meta_now)
    return dt or datetime.now(TZ)


def _stream_response(state: CallState, text: str) -> None:
    state["assistant_text"] = text
    writer = get_stream_writer()
    if writer:
        for word in text.split():
            writer(("assistant_token", word + " "))
        state["assistant_streamed"] = True


def _serialize_datetimes(state: CallState) -> None:
    def _ser(val: Any) -> Any:
        if isinstance(val, datetime):
            return val.astimezone(TZ).isoformat()
        return val

    appt = state.get("appointment_create")
    if isinstance(appt, dict):
        for key in ("start_at", "end_at"):
            if key in appt:
                appt[key] = _ser(appt[key])

    view = state.get("appointment_view")
    if isinstance(view, dict):
        for key in ("start_at", "end_at", "created_at", "updated_at"):
            if key in view:
                view[key] = _ser(view[key])

    if "last_offered_slot_start_at" in state:
        state["last_offered_slot_start_at"] = _ser(state.get("last_offered_slot_start_at"))





def _mask_phone(phone: str) -> str:
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(digits) <= 4:
        return digits or "unknown"
    return ("*" * (len(digits) - 4)) + digits[-4:]


def _compute_search_window(
    *,
    schedule_intent: str,
    patch: dict,
    now: datetime,
    last_offered: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    days = _coerce_int(patch.get("search_days"), DEFAULT_SEARCH_DAYS)
    if schedule_intent == "earliest":
        start = now
        end = now + timedelta(days=days)
        return start, end

    if schedule_intent == "specific":
        start = _parse_dt(patch.get("desired_start_at"))
        if start:
            end = start + timedelta(days=days)
            return start, end
        return None, None

    if schedule_intent == "range":
        start = _parse_dt(patch.get("range_start_at"))
        end = _parse_dt(patch.get("range_end_at"))
        if not start:
            return None, None
        if not end or end <= start:
            end = start + timedelta(days=days)
        return start, end

    if schedule_intent == "reject_and_search":
        start = _parse_dt(patch.get("desired_start_at")) or _parse_dt(patch.get("range_start_at"))
        end = _parse_dt(patch.get("range_end_at"))
        if start is None and last_offered:
            start = last_offered + timedelta(days=1)
        if start is None:
            start = now + timedelta(days=1)
        if end is None or end <= start:
            end = start + timedelta(days=days)
        return start, end

    return None, None


def _finalize_response(
    state: CallState,
    text: str,
    *,
    ready: bool | None = None,
    speak: bool = True,
) -> CallState:
    appointment = state.get("appointment_create") or {}
    state["pending_intent"] = ClinicIntent.BOOK_APPOINTMENT
    state["ready_to_confirm"] = _is_complete(appointment) if ready is None else ready

    if speak:
        _stream_response(state, text)
        state["assistant_text"] = text
        state["pending_question"] = text
    else:
        state["assistant_text"] = ""
        state["assistant_streamed"] = False
        state["pending_question"] = None


    _serialize_datetimes(state)
    return state


async def node_fill_appointment_slot(
    state: CallState, *, sessionmaker: async_sessionmaker[AsyncSession]
) -> CallState:
    appointment = state.setdefault("appointment_create", {})
    now = _get_now(state)
    last_offered = _parse_dt(state.get("last_offered_slot_start_at"))

    # Normalize any stored datetimes back to tz-aware objects
    for key in ("start_at", "end_at"):
        if key in appointment:
            parsed = _parse_dt(appointment.get(key))
            if parsed:
                appointment[key] = parsed

    user_text = (state.get("user_text") or "").strip()

    patch = {}
    if user_text:
        prompt = build_slot_fill_prompt(
            user_text=user_text,
            appointment=appointment,
            now=now,
            last_offered=last_offered,
            opening_time=settings.OPENING_TIME.isoformat(),
            closing_time=settings.CLOSING_TIME.isoformat(),
        )
        try:
            resp = await LLM.ainvoke(prompt)
            raw_content = resp.content or ""
            parsed = safe_json_parse(raw_content)
            logger.warning("slot_fill LLM raw=%s parsed=%s", raw_content, parsed)
            if isinstance(parsed, dict):
                patch = parsed.get("patch") or {}
        except Exception:
            logger.exception("slot_fill LLM parse failed")
            patch = {}

    _merge_patch(state, patch)
    appointment = state["appointment_create"]

    # Fallback: if phone still missing and user_text looks like a number, capture it.
    if not appointment.get("phone"):
        fallback_phone = normalize_phone(user_text)
        if fallback_phone:
            appointment["phone"] = fallback_phone
            logger.warning("slot_fill fallback phone captured=%s", fallback_phone)

    name_missing = not bool(appointment.get("name"))
    phone_missing = not bool(appointment.get("phone"))
    if name_missing and phone_missing:
        return _finalize_response(state, "Can I get your full name and phone number?")
    if phone_missing:
        return _finalize_response(
            state,
            f"Thanks {appointment.get('name')}. What’s the best phone number to reach you?",
        )
    if name_missing:
        return _finalize_response(state, "Got it. What’s your full name?")

    if not appointment.get("reason_for_visit"):
        return _finalize_response(state, "What’s the reason for your visit?")

    schedule_intent = str(patch.get("schedule_intent") or "unspecified")
    start_range, end_range = _compute_search_window(
        schedule_intent=schedule_intent,
        patch=patch,
        now=now,
        last_offered=last_offered,
    )
    logger.warning(
        "slot_fill intent=%s start_range=%s end_range=%s name=%s phone=%s reason=%s",
        schedule_intent,
        start_range,
        end_range,
        appointment.get("name"),
        appointment.get("phone"),
        appointment.get("reason_for_visit"),
    )

    if schedule_intent == "unspecified" or start_range is None or end_range is None:
        return _finalize_response(
            state, "Do you have a preferred date, or should I book the earliest available?"
        )

    async with sessionmaker() as session:
        uow = SqlAlchemyUnitOfWork(session)
        slots = await list_free_slots(
            uow,
            start_range=start_range,
            end_range=end_range,
        )
        logger.warning("slot_fill slots_found=%d", len(slots))

        if not slots:
            fallback_start = max(end_range, now)
            fallback_end = fallback_start + timedelta(days=EXPANDED_SEARCH_DAYS)
            slots = await list_free_slots(
                uow,
                start_range=fallback_start,
                end_range=fallback_end,
            )
            if slots:
                slot = min(slots, key=lambda s: s.start_at)
                appointment["start_at"] = slot.start_at
                appointment["end_at"] = slot.end_at
                state["last_offered_slot_start_at"] = slot.start_at
                # We have a concrete slot; move directly to confirmation to avoid double-speaking.
                return _finalize_response(state, "", speak=False)

            appointment.pop("start_at", None)
            appointment.pop("end_at", None)
            return _finalize_response(
                state,
                "I’m not seeing any openings in the next couple of weeks. Could you share another date range?",
                ready=False,
            )

        slot = min(slots, key=lambda s: s.start_at)
        appointment["start_at"] = slot.start_at
        appointment["end_at"] = slot.end_at
        state["last_offered_slot_start_at"] = slot.start_at
        # We have a concrete slot; move directly to confirmation to avoid double-speaking.
        return _finalize_response(state, "", speak=False)


async def _find_next_available_slot(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    start_from: datetime,
) -> TimeSlot | None:
    for days in (DEFAULT_SEARCH_DAYS, EXPANDED_SEARCH_DAYS):
        async with sessionmaker() as session:
            uow = SqlAlchemyUnitOfWork(session)
            slots = await list_free_slots(
                uow,
                start_range=start_from,
                end_range=start_from + timedelta(days=days),
            )
            if slots:
                return min(slots, key=lambda s: s.start_at)
    return None


async def node_confirm_appointment_slot(
    state: CallState, *, sessionmaker: async_sessionmaker[AsyncSession]
) -> CallState:
    appointment = state.setdefault("appointment_create", {})
    start_at = _parse_dt(appointment.get("start_at"))
    end_at = _parse_dt(appointment.get("end_at"))
    if start_at:
        appointment["start_at"] = start_at
    if end_at:
        appointment["end_at"] = end_at

    missing = [k for k in ("name", "phone", "reason_for_visit", "start_at", "end_at") if not appointment.get(k)]
    if missing:
        return _finalize_response(
            state,
            "I still need your "
            + ", ".join(missing).replace("_", " ")
            + ". Could you share that now?",
            ready=False,
        )

    notes = appointment.get("notes") or []
    if not isinstance(notes, list):
        notes = [str(notes)]

    async with sessionmaker() as session:
        uow = SqlAlchemyUnitOfWork(session)
        try:
            view = await hold_slot(
                uow,
                slot_start=start_at,
                name=appointment["name"],
                phone=appointment["phone"],
                reason_for_visit=appointment["reason_for_visit"],
                notes=notes,
            )
            state["appointment_view"] = view if isinstance(view, dict)  else {}
            state["last_offered_slot_start_at"] = start_at
        except SlotNotAvailable:
            next_slot = await _find_next_available_slot(sessionmaker, start_from=start_at)
            if next_slot:
                appointment["start_at"] = next_slot.start_at
                appointment["end_at"] = next_slot.end_at
                state["last_offered_slot_start_at"] = next_slot.start_at
                logger.info("slot_confirm fallback next_slot=%s", next_slot.start_at)
                return _finalize_response(
                    state,
                    f"That slot was just taken. The next available is {_format_dt(next_slot.start_at)}. Does that work?",
                )
            appointment.pop("start_at", None)
            appointment.pop("end_at", None)
            logger.info("slot_confirm no slots available after conflict")
            return _finalize_response(
                state,
                "That time isn’t available and I couldn’t find another in the next couple of weeks. Could you share another date range?",
                ready=False,
            )

    masked_phone = _mask_phone(appointment["phone"])
    summary = (
        f"Got it. Booking {appointment['name']} (phone ending in {masked_phone}) for "
        f"{_format_dt(appointment['start_at'])} to discuss {appointment['reason_for_visit']}. Is that correct?"
    )
    return _finalize_response(state, summary)
