from __future__ import annotations

import asyncio
import time
import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from langgraph.config import get_stream_writer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from voice_agent.const import DEFAULT_TZ
from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.llm.openai_llm import LLM
from voice_agent.core.services.appointments import list_free_slots, hold_slot
from voice_agent.core.types import (
    CallState,
    ClinicIntent,
    TimeSlot,
    AppointmentDraft,
)
from voice_agent.core.prompts.slot_filling import build_slot_fill_prompt
from voice_agent.core.settings import settings

from .utils import (
    normalize_phone,
    safe_json_parse,
    parse_date,
    format_date,
    is_appointment_complete,
    call_llm_with_slow_filler,
)
from ...llm.huggingface_llm import agent_model
from ...prompts.slot_filling_basic import build_local_fast_extract_prompt
from ...services.exceptions import SlotNotAvailable

logger = logging.getLogger(__name__)

DEFAULT_SEARCH_DAYS = 7
EXPANDED_SEARCH_DAYS = 14


def _coerce_int(val: Any, default: int) -> int:
    try:
        return int(val)
    except Exception:
        return default


def _get_now(state: CallState, tz_info: ZoneInfo = DEFAULT_TZ) -> datetime:
    meta = state.get("meta") or {}
    meta_now = meta.get("now")
    dt = parse_date(meta_now)
    return dt or datetime.now(tz_info)


def _stream_response(state: CallState, text: str) -> None:
    state["assistant_text"] = text
    writer = get_stream_writer()
    if writer:
        for word in text.split():
            writer(("assistant_token", word + " "))
        state["assistant_streamed"] = True


def _finalize_response(
    state: CallState,
    text: str,
    *,
    ready: bool | None = None,
    speak: bool = True,
) -> CallState:
    appointment = state.get("appointment_draft") or {}

    if ready:
        read_to_confirm = is_appointment_complete(appointment)
        if read_to_confirm:
            state["ready_to_confirm"] = read_to_confirm
            state['pending_intent'] = ClinicIntent.CONFIRM_APPOINTMENT

    else:
        state["pending_intent"] = ClinicIntent.BOOK_APPOINTMENT
    if speak:
        _stream_response(state, text)
        state["assistant_text"] = text
        state["pending_question"] = text
    else:
        state["assistant_text"] = ""
        state["assistant_streamed"] = False
        state["pending_question"] = None

    return state

def _extract_appointment_basic(appointment: AppointmentDraft) -> AppointmentDraft:
    return dict(
        name=appointment.get("name"),
        phone=appointment.get("phone"),
        reason_for_visit=appointment.get("reason_for_visit"),
        last_offered_slot_start_at=appointment.get("last_offered_slot_start_at"),
    )


def _merge_patch(state: CallState, patch: dict) -> None:
    """
    Merge only supported delta fields into appointment_draft.
    Notes are appended; strings are trimmed; phone is normalized.
    """
    appt = state.setdefault("appointment_draft", {})

    # notes
    notes_append = patch.get("notes_append")
    if isinstance(notes_append, list):
        notes = appt.setdefault("notes", [])
        for note in notes_append:
            if isinstance(note, str) and note.strip():
                notes.append(note.strip())

    # basics
    for key in ("name", "phone", "reason_for_visit"):
        val = patch.get(key)
        if isinstance(val, str) and val.strip():
            if key == "phone":
                norm = normalize_phone(val)
                if norm:
                    appt[key] = norm
            else:
                appt[key] = val.strip()

    # scheduling fields (keep as-is; python will parse/validate later)
    # NOTE: these are optional; they won't exist in local_patch.
    for key in ("schedule_intent", "desired_start_at", "search_days", "time_bucket", "assistant_text", "clarify_reason"):
        if key in patch:
            appt[key] = patch.get(key)


def _compute_search_window(
    *,
    schedule_intent: str,
    patch: dict,
    now: datetime,
    last_offered: datetime | None,
) -> tuple[datetime | None, datetime | None, str | None]:
    """
    Returns (start_range, end_range, time_bucket).

    - specific: anchor = desired_start_at (datetime), python expands window
    - earliest: anchor = now, python expands window
    - reject_and_search: anchor = last_offered + 1 minute (or now), python expands window
    """
    days = _coerce_int(patch.get("search_days"), DEFAULT_SEARCH_DAYS)

    bucket = patch.get("time_bucket")
    if bucket not in ("morning", "afternoon", "evening"):
        bucket = None

    if schedule_intent == "earliest":
        start = now
        end = now + timedelta(days=days)
        return start, end, bucket

    if schedule_intent == "specific":
        anchor = parse_date(patch.get("desired_start_at"))
        if not anchor:
            return None, None, bucket
        # Never search in the past
        start = max(anchor, now)
        end = start + timedelta(days=days)
        return start, end, bucket

    if schedule_intent == "reject_and_search":
        # Move just past last_offered so we can find a different slot on same day.
        start = (last_offered + timedelta(minutes=1)) if last_offered else (now + timedelta(minutes=1))
        end = start + timedelta(days=days)
        return start, end, bucket

    return None, None, bucket


def _bucket_match(dt: datetime, bucket: str | None) -> bool:
    if bucket is None:
        return True  # no preference
    h = dt.hour
    if bucket == "morning":
        return h < 12
    if bucket == "afternoon":
        return 12 <= h < 17
    if bucket == "evening":
        return h >= 17
    return True


def _pick_best_slot(slots: list[TimeSlot], bucket: str | None) -> TimeSlot:
    """
    Prefer the earliest slot whose start_at falls in the requested bucket.
    If none match, return the earliest slot overall.
    """
    matching: list[TimeSlot] = []
    for s in slots:
        dt = parse_date(getattr(s, "start_at", None))
        if dt and _bucket_match(dt, bucket):
            matching.append(s)

    if matching:
        return min(matching, key=lambda s: s.start_at)

    return min(slots, key=lambda s: s.start_at)


async def node_fill_appointment_slot(
    state: CallState,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> CallState:
    appointment: AppointmentDraft = state.setdefault("appointment_draft", {})
    now = _get_now(state)
    user_text = (state.get("user_text") or "").strip()

    # -------------------------
    # 1) Fast local extraction
    # -------------------------
    local_patch: dict = {}
    date_mentioned = False

    if user_text:
        local_prompt = build_local_fast_extract_prompt(
            user_text=user_text,
            appointment=_extract_appointment_basic(appointment),
            now=now,
        )
        try:
            # writer = get_stream_writer()
            t0 = time.perf_counter()
            resp = await asyncio.to_thread(agent_model.invoke, local_prompt)
            t1 = time.perf_counter()
            raw = getattr(resp, "content", "") or ""
            parsed = safe_json_parse(raw)
            logger.warning(
                "----------\nlocal_extract time=%0.2fs raw=%s parsed=%s\n-----------",
                t1 - t0,
                raw,
                parsed,
            )
            if isinstance(parsed, dict):
                local_patch = parsed.get("patch") or {}
                date_mentioned = bool(parsed.get("date_mentioned") or False)
        except Exception:
            logger.exception("local_extract failed")
            local_patch = {}
            date_mentioned = False

    _merge_patch(state, local_patch)
    appointment = state.get("appointment_draft", {})

    # Fallback phone normalization (digits/letters) if still missing
    if not appointment.get("phone"):
        fallback_phone = normalize_phone(user_text)
        if fallback_phone:
            appointment["phone"] = fallback_phone

    # -------------------------
    # Ask for missing basics
    # -------------------------
    if not appointment.get("name") and not appointment.get("phone"):
        return _finalize_response(state, "Can I get your full name and phone number?")
    if not appointment.get("name"):
        return _finalize_response(state, "What's your name?")
    if not appointment.get("phone"):
        return _finalize_response(
            state, f"Thanks {appointment.get('name')}. What's the best phone number to reach you?"
        )
    if not appointment.get("reason_for_visit"):
        return _finalize_response(state, "What's the reason for your visit?")

    # ----------------------------------------------------
    # 2) Scheduling resolver (OpenAI) ONLY if date mentioned
    # ----------------------------------------------------
    schedule_patch: dict = {}
    schedule_intent = "unspecified"

    # Keep last_offered in draft for context, but compute datetime for logic
    last_offered_raw = appointment.get("last_offered_slot_start_at")
    last_offered_dt = parse_date(last_offered_raw) if last_offered_raw else None

    if date_mentioned or last_offered_dt:
        resolver_prompt = build_slot_fill_prompt(
            user_text=user_text,
            state=state,
            appointment=appointment,
            now=now,
            last_offered=last_offered_raw,  # prompt expects str | None
            opening_time=settings.OPENING_TIME.strftime("%H:%M"),
            closing_time=settings.CLOSING_TIME.strftime("%H:%M"),
        )

        try:
            t0 = time.perf_counter()
            writer = get_stream_writer()
            resp = await call_llm_with_slow_filler(
                writer=writer,
                coro=LLM.ainvoke(resolver_prompt),
                filler_text="One moment. ",
                delay_s=0.45,
            )
            t1 = time.perf_counter()
            raw = getattr(resp, "content", "") or ""
            parsed = safe_json_parse(raw)
            logger.warning(
                "----------\nschedule_resolve time=%0.2fs raw=%s parsed=%s\n-----------",
                t1 - t0,
                raw,
                parsed,
            )

            if isinstance(parsed, dict):
                schedule_patch = parsed.get("patch") or {}
                schedule_intent = str(schedule_patch.get("schedule_intent") or "unspecified")
        except Exception:
            logger.exception("schedule_resolve failed")
            schedule_patch = {}
            schedule_intent = "unspecified"

        _merge_patch(state, schedule_patch)
        appointment = state.get("appointment_draft", {})

        # Handle clarify immediately
        if schedule_intent == "clarify":
            assistant_text = schedule_patch.get("assistant_text")
            if isinstance(assistant_text, str) and assistant_text.strip():
                logger.warning("clarify_intent: %s", assistant_text)
                return _finalize_response(state, assistant_text.strip(), ready=False)
            return _finalize_response(state, "Could you tell me which day you prefer?", ready=False)

        # Refresh last_offered_dt if resolver changed it (rare, but safe)
        last_offered_raw = appointment.get("last_offered_slot_start_at")
        last_offered_dt = parse_date(last_offered_raw) if last_offered_raw else None

    start_range, end_range, time_bucket = _compute_search_window(
        schedule_intent=schedule_intent,
        patch=schedule_patch,
        now=now,
        last_offered=last_offered_dt,
    )

    logger.warning(
        "----------\nslot_fill intent=%s start_range=%s end_range=%s bucket=%s name=%s phone=%s reason=%s\n-----------",
        schedule_intent,
        start_range,
        end_range,
        time_bucket,
        appointment.get("name"),
        appointment.get("phone"),
        appointment.get("reason_for_visit"),
    )

    if schedule_intent == "unspecified" or start_range is None or end_range is None:
        return _finalize_response(state, "Do you have a preferred date, or should I book the earliest available?")

    # -------------------------
    # Slot search
    # -------------------------
    async with sessionmaker() as session:
        uow = SqlAlchemyUnitOfWork(session)
        slots = await list_free_slots(uow, start_range=start_range, end_range=end_range)
        logger.warning("----------\nslot_fill slots_found=%d\n-----------", len(slots))

        if not slots:
            # extend AFTER requested window
            fallback_start = max(now, end_range + timedelta(minutes=1))
            fallback_end = fallback_start + timedelta(days=EXPANDED_SEARCH_DAYS)
            slots = await list_free_slots(uow, start_range=fallback_start, end_range=fallback_end)

            if not slots:
                appointment.pop("start_at", None)
                appointment.pop("end_at", None)
                return _finalize_response(
                    state,
                    "I'm not seeing any openings in the next couple of weeks. Could you share another date range?",
                    ready=False,
                )

        slot = _pick_best_slot(slots, time_bucket)
        d_start_at = parse_date(slot.start_at)
        d_end_at = parse_date(slot.end_at)

        text = ""
        if d_start_at:
            appointment["start_at"] = d_start_at.isoformat()
            appointment["last_offered_slot_start_at"] = d_start_at.isoformat()
            text += f"I'm looking for an available slot starting {format_date(d_start_at)}. "
        if d_end_at:
            appointment["end_at"] = d_end_at.isoformat()
            text += f"It should end {format_date(d_end_at)}. "

        return _finalize_response(state, text, speak=True)


def _mask_phone(phone: str) -> str:
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(digits) <= 4:
        return digits or "unknown"
    return ("*" * (len(digits) - 4)) + digits[-4:]



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
    start_at = parse_date(appointment.get("start_at"))
    end_at = parse_date(appointment.get("end_at"))
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
            state["appointment_view"] = view if isinstance(view, dict) else {}
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
                    f"That slot was just taken. The next available is {format_date(next_slot.start_at)}. Does that work?",
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
        f"{format_date(appointment['start_at'])} to discuss {appointment['reason_for_visit']}. Is that correct?"
    )
    return _finalize_response(state, summary)
