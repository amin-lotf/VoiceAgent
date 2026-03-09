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
from voice_agent.core.services.appointments import (
    list_free_slots,
    hold_slot,
    confirm_appointment,
    delete_held_appointment,
    update_held_appointment_details,
)
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
    call_llm_with_slow_filler,
)
from ...llm.huggingface_llm import agent_model
from ...prompts.slot_filling_basic import build_local_fast_extract_prompt, build_local_confirmation_prompt
from ...services.exceptions import SlotNotAvailable, NotFound

logger = logging.getLogger(__name__)

DEFAULT_SEARCH_DAYS = 7
EXPANDED_SEARCH_DAYS = 14
_KEEP = object()

PENDING_Q_ASK_NAME_PHONE = "ask_name_phone"
PENDING_Q_ASK_NAME = "ask_name"
PENDING_Q_ASK_PHONE = "ask_phone"
PENDING_Q_ASK_REASON = "ask_reason"
PENDING_Q_ASK_DATETIME = "ask_datetime"
PENDING_Q_SLOT_CONFIRM = "confirm_suggested_slot"
PENDING_Q_FINAL_CONFIRM = "confirm_final_booking"
PENDING_Q_CONFIRM_PROFILE_CHANGE = "confirm_profile_change"


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
    route_to_booking: bool = False,
    speak: bool = True,
    pending_question: str | None | object = _KEEP,
    pending_intent: ClinicIntent | None | object = _KEEP,
) -> CallState:
    state["ready_to_confirm"] = route_to_booking

    if pending_intent is not _KEEP:
        state["pending_intent"] = pending_intent
    elif route_to_booking:
        state["pending_intent"] = None

    if pending_question is not _KEEP:
        state["pending_question"] = pending_question

    if speak:
        _stream_response(state, text)
        state["assistant_text"] = text
    else:
        state["assistant_text"] = ""
        state["assistant_streamed"] = False

    return state


def _extract_appointment_basic(appointment: AppointmentDraft) -> AppointmentDraft:
    return dict(
        name=appointment.get("name"),
        phone=appointment.get("phone"),
        reason_for_visit=appointment.get("reason_for_visit"),
        last_offered_slot_start_at=appointment.get("last_offered_slot_start_at"),
    )


def _has_basic_delta(patch: dict) -> bool:
    for key in ("name", "phone", "reason_for_visit"):
        val = patch.get(key)
        if isinstance(val, str) and val.strip():
            return True
    return False


def _build_final_review_text(appointment: AppointmentDraft) -> str:
    when = "the selected time"
    start_at = parse_date(appointment.get("start_at"))
    if start_at:
        when = format_date(start_at)

    name = appointment.get("name") or "you"
    phone = appointment.get("phone") or "not provided"
    reason = appointment.get("reason_for_visit") or "your visit"

    return (
        f"Before I book it, I have {name} for {when}, reason {reason}, and phone {phone}. "
        "Should I confirm?"
    )


def _looks_like_final_review(text: str | None) -> bool:
    if not isinstance(text, str):
        return False
    t = text.strip().lower()
    return t.startswith("before i book it") and "should i confirm" in t


def _normalize_basic_value(key: str, value: str) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if key == "phone":
        return normalize_phone(raw)
    return raw


def _basic_value_equal(key: str, left: str | None, right: str | None) -> bool:
    if key == "phone":
        l = normalize_phone(left) if left else None
        r = normalize_phone(right) if right else None
        return bool(l and r and l == r)
    if left is None or right is None:
        return False
    return left.strip().casefold() == right.strip().casefold()


def _has_explicit_change_cue(user_text: str) -> bool:
    text = f" {user_text.lower()} "
    cues = (
        " actually ",
        " change ",
        " update ",
        " instead ",
        " wrong ",
        " correct ",
        " not ",
        " no,",
        " no ",
    )
    return any(cue in text for cue in cues)


def _extract_basic_patch_and_changes(
    *,
    appointment: AppointmentDraft,
    patch: dict,
    user_text: str,
) -> tuple[dict, dict[str, dict[str, str]]]:
    out_patch = dict(patch or {})
    changes: dict[str, dict[str, str]] = {}
    explicit_change = _has_explicit_change_cue(user_text)

    for key in ("name", "phone", "reason_for_visit"):
        new_norm = _normalize_basic_value(key, out_patch.get(key))
        if new_norm is None:
            out_patch.pop(key, None)
            continue

        current = appointment.get(key)
        if not current:
            out_patch[key] = new_norm
            continue

        # Existing value: never auto-overwrite. Only propose when correction is explicit.
        if _basic_value_equal(key, str(current), new_norm):
            out_patch.pop(key, None)
            continue

        if explicit_change:
            changes[key] = {"old": str(current), "new": new_norm}

        out_patch.pop(key, None)

    return out_patch, changes


def _field_label(key: str) -> str:
    if key == "reason_for_visit":
        return "reason for visit"
    return key


def _build_profile_change_text(changes: dict[str, dict[str, str]]) -> str:
    segments: list[str] = []
    for key in ("name", "phone", "reason_for_visit"):
        change = changes.get(key)
        if not change:
            continue
        segments.append(
            f"{_field_label(key)} from {change['old']} to {change['new']}"
        )
    if not segments:
        return "Do you want to update your details?"
    return "Just to confirm, you want to change " + ", and ".join(segments) + ". Is that right?"


def _apply_profile_changes(appointment: AppointmentDraft, changes: dict[str, dict[str, str]]) -> None:
    for key in ("name", "phone", "reason_for_visit"):
        change = changes.get(key)
        if not change:
            continue
        new_value = change.get("new")
        if not isinstance(new_value, str) or not new_value.strip():
            continue
        appointment[key] = new_value.strip()


async def _release_held_slot(
    state: CallState,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    held_id = state.get("held_appointment_id")
    if not held_id:
        return
    try:
        async with sessionmaker() as session:
            uow = SqlAlchemyUnitOfWork(session)
            await delete_held_appointment(uow, appointment_id=int(held_id))
    except NotFound:
        logger.info("release_held_slot skipped: appointment %s is not HELD", held_id)
    except Exception:
        logger.exception("release_held_slot failed for %s", held_id)
    state["held_appointment_id"] = None
    state["appointment_view"] = {}


async def _sync_held_slot_details(
    state: CallState,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    held_id = state.get("held_appointment_id")
    if not held_id:
        return

    appointment = state.setdefault("appointment_draft", {})
    if not (appointment.get("name") and appointment.get("phone") and appointment.get("reason_for_visit")):
        return

    notes = appointment.get("notes") or []
    if not isinstance(notes, list):
        notes = [str(notes)]

    try:
        async with sessionmaker() as session:
            uow = SqlAlchemyUnitOfWork(session)
            view = await update_held_appointment_details(
                uow,
                appointment_id=int(held_id),
                name=str(appointment["name"]),
                phone=str(appointment["phone"]),
                reason_for_visit=str(appointment["reason_for_visit"]),
                notes=notes,
            )
            state["appointment_view"] = view if isinstance(view, dict) else state.get("appointment_view", {})
    except NotFound:
        logger.info("sync_held_slot_details skipped: hold not found %s", held_id)
        state["held_appointment_id"] = None
        state["appointment_view"] = {}
    except Exception:
        logger.exception("sync_held_slot_details failed for %s", held_id)


async def _classify_confirmation_intent(
    *,
    user_text: str,
    appointment: AppointmentDraft,
    pending_question: str,
    prior_assistant_text: str | None,
) -> str:
    if not user_text:
        return "unclear"

    prompt = build_local_confirmation_prompt(
        user_text=user_text,
        appointment=appointment,
        pending_question=pending_question,
        prior_assistant_text=prior_assistant_text,
    )
    try:
        t0 = time.perf_counter()
        # resp = await asyncio.to_thread(agent_model.invoke, prompt)
        resp = await LLM.ainvoke(prompt)
        t1 = time.perf_counter()
        raw = getattr(resp, "content", "") or ""
        parsed = safe_json_parse(raw)
        logger.warning(
            "----------\nconfirm_intent time=%0.2fs raw=%s parsed=%s\n-----------",
            t1 - t0,
            raw,
            parsed,
        )
        intent = str((parsed or {}).get("intent") or "").strip().lower()
        if intent in {"confirm", "revise", "unclear"}:
            return intent
        return "unclear"
    except Exception:
        logger.exception("confirm_intent failed")
        return "unclear"


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
    state["ready_to_confirm"] = False

    # Confirm explicit profile changes before continuing scheduling.
    pending_question = str(state.get("pending_question") or "")
    pending_profile_change = state.get("pending_profile_change") or {}
    if pending_question == PENDING_Q_CONFIRM_PROFILE_CHANGE and pending_profile_change:
        confirm_intent = await _classify_confirmation_intent(
            user_text=user_text,
            appointment=appointment,
            pending_question=PENDING_Q_CONFIRM_PROFILE_CHANGE,
            prior_assistant_text=state.get("prev_assistant_text"),
        )
        if confirm_intent == "confirm":
            _apply_profile_changes(appointment, pending_profile_change)
            return_to = state.get("profile_change_return_to")
            had_date_mention = bool(state.get("profile_change_had_date_mention"))
            state["pending_profile_change"] = {}
            state["profile_change_return_to"] = None
            state["profile_change_had_date_mention"] = False

            if had_date_mention:
                if state.get("held_appointment_id"):
                    await _release_held_slot(state, sessionmaker=sessionmaker)
                return _finalize_response(
                    state,
                    "Updated. What date and time would you like?",
                    pending_question=PENDING_Q_ASK_DATETIME,
                    pending_intent=ClinicIntent.BOOK_APPOINTMENT,
                )
            if state.get("held_appointment_id"):
                await _sync_held_slot_details(state, sessionmaker=sessionmaker)
            if return_to == PENDING_Q_FINAL_CONFIRM and appointment.get("start_at"):
                return _finalize_response(
                    state,
                    _build_final_review_text(appointment),
                    pending_question=PENDING_Q_FINAL_CONFIRM,
                    pending_intent=ClinicIntent.BOOK_APPOINTMENT,
                )
            return _finalize_response(
                state,
                "Updated.",
                pending_question=PENDING_Q_ASK_DATETIME,
                pending_intent=ClinicIntent.BOOK_APPOINTMENT,
            )
        if confirm_intent == "revise":
            state["pending_profile_change"] = {}
            state["profile_change_return_to"] = None
            state["profile_change_had_date_mention"] = False
            return _finalize_response(
                state,
                "Okay, please say the exact detail you want to change.",
                pending_question=PENDING_Q_CONFIRM_PROFILE_CHANGE,
                pending_intent=ClinicIntent.BOOK_APPOINTMENT,
            )
        return _finalize_response(
            state,
            "Please confirm if you want that profile change.",
            pending_question=PENDING_Q_CONFIRM_PROFILE_CHANGE,
            pending_intent=ClinicIntent.BOOK_APPOINTMENT,
        )

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
            # resp = await asyncio.to_thread(agent_model.invoke, local_prompt)
            resp = await LLM.ainvoke(local_prompt)
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

    local_patch, profile_changes = _extract_basic_patch_and_changes(
        appointment=appointment,
        patch=local_patch,
        user_text=user_text,
    )

    if profile_changes:
        state["pending_profile_change"] = profile_changes
        state["profile_change_return_to"] = pending_question if pending_question else None
        state["profile_change_had_date_mention"] = bool(date_mentioned)
        return _finalize_response(
            state,
            _build_profile_change_text(profile_changes),
            pending_question=PENDING_Q_CONFIRM_PROFILE_CHANGE,
            pending_intent=ClinicIntent.BOOK_APPOINTMENT,
        )

    _merge_patch(state, local_patch)
    appointment = state.get("appointment_draft", {})
    basic_delta = _has_basic_delta(local_patch)

    # Fallback phone normalization (digits/letters) if still missing
    if not appointment.get("phone"):
        fallback_phone = normalize_phone(user_text)
        if fallback_phone:
            appointment["phone"] = fallback_phone

    # -------------------------
    # Ask for missing basics
    # -------------------------
    if not appointment.get("name") and not appointment.get("phone"):
        return _finalize_response(
            state,
            "Can I get your full name and phone number?",
            pending_question=PENDING_Q_ASK_NAME_PHONE,
            pending_intent=ClinicIntent.BOOK_APPOINTMENT,
        )
    if not appointment.get("name"):
        return _finalize_response(
            state,
            "What's your name?",
            pending_question=PENDING_Q_ASK_NAME,
            pending_intent=ClinicIntent.BOOK_APPOINTMENT,
        )
    if not appointment.get("phone"):
        return _finalize_response(
            state,
            f"Thanks {appointment.get('name')}. What's the best phone number to reach you?",
            pending_question=PENDING_Q_ASK_PHONE,
            pending_intent=ClinicIntent.BOOK_APPOINTMENT,
        )
    if not appointment.get("reason_for_visit"):
        return _finalize_response(
            state,
            "What's the reason for your visit?",
            pending_question=PENDING_Q_ASK_REASON,
            pending_intent=ClinicIntent.BOOK_APPOINTMENT,
        )

    pending_question = str(state.get("pending_question") or "")
    confirm_intent = "unclear"
    if pending_question in {PENDING_Q_SLOT_CONFIRM, PENDING_Q_FINAL_CONFIRM}:
        confirm_intent = await _classify_confirmation_intent(
            user_text=user_text,
            appointment=appointment,
            pending_question=pending_question,
            prior_assistant_text=state.get("prev_assistant_text"),
        )

    # Defensive fallback: if final-review text was just asked, honor that stage
    # even if pending_question drifted due transport/race timing.
    if _looks_like_final_review(state.get("prev_assistant_text")) and not date_mentioned and state.get("held_appointment_id"):
        if confirm_intent == "confirm":
            return _finalize_response(
                state,
                "",
                route_to_booking=True,
                speak=False,
                pending_question=None,
                pending_intent=None,
            )
        if confirm_intent == "revise":
            await _release_held_slot(state, sessionmaker=sessionmaker)
            return _finalize_response(
                state,
                "No problem, I released that time. What would you like to change?",
                pending_question=PENDING_Q_FINAL_CONFIRM,
                pending_intent=ClinicIntent.BOOK_APPOINTMENT,
            )
        if confirm_intent == "unclear":
            return _finalize_response(
                state,
                "Please confirm if you want me to book this, or tell me what to change.",
                pending_question=PENDING_Q_FINAL_CONFIRM,
                pending_intent=ClinicIntent.BOOK_APPOINTMENT,
            )

    # Step 1 confirmation: caller confirms/rejects the offered date.
    if pending_question == PENDING_Q_SLOT_CONFIRM:
        if confirm_intent == "confirm":
            hold_result = await _prepare_hold_for_final_confirmation(
                state,
                sessionmaker=sessionmaker,
            )
            if hold_result is not None:
                return hold_result
            return _finalize_response(
                state,
                _build_final_review_text(appointment),
                pending_question=PENDING_Q_FINAL_CONFIRM,
                pending_intent=ClinicIntent.BOOK_APPOINTMENT,
            )
        if confirm_intent == "unclear" and not date_mentioned:
            return _finalize_response(
                state,
                "Does that appointment time work for you?",
                pending_question=PENDING_Q_SLOT_CONFIRM,
                pending_intent=ClinicIntent.BOOK_APPOINTMENT,
            )
        if confirm_intent == "revise" and not date_mentioned:
            return _finalize_response(
                state,
                "Sure. What date and time would you like instead?",
                pending_question=PENDING_Q_ASK_DATETIME,
                pending_intent=ClinicIntent.BOOK_APPOINTMENT,
            )

    # Step 2 confirmation: caller confirms final summary before booking.
    if pending_question == PENDING_Q_FINAL_CONFIRM:
        if not date_mentioned and basic_delta:
            return _finalize_response(
                state,
                _build_final_review_text(appointment),
                pending_question=PENDING_Q_FINAL_CONFIRM,
                pending_intent=ClinicIntent.BOOK_APPOINTMENT,
            )
        if not date_mentioned and confirm_intent == "confirm":
            return _finalize_response(
                state,
                "",
                route_to_booking=True,
                speak=False,
                pending_question=None,
                pending_intent=None,
            )
        if not date_mentioned and confirm_intent == "revise":
            if state.get("held_appointment_id"):
                await _release_held_slot(state, sessionmaker=sessionmaker)
            return _finalize_response(
                state,
                "No problem, I released that time. What would you like to change?",
                pending_question=PENDING_Q_FINAL_CONFIRM,
                pending_intent=ClinicIntent.BOOK_APPOINTMENT,
            )
        if not date_mentioned and confirm_intent == "unclear":
            return _finalize_response(
                state,
                "Please confirm if you want me to book this, or tell me what to change.",
                pending_question=PENDING_Q_FINAL_CONFIRM,
                pending_intent=ClinicIntent.BOOK_APPOINTMENT,
            )

    # User changed date/time after we already held a slot for final confirmation.
    if pending_question == PENDING_Q_FINAL_CONFIRM and date_mentioned and state.get("held_appointment_id"):
        await _release_held_slot(state, sessionmaker=sessionmaker)

    # ----------------------------------------------------
    # 2) Scheduling resolver (OpenAI) ONLY if date mentioned
    # ----------------------------------------------------
    schedule_patch: dict = {}
    schedule_intent = "unspecified"

    # Keep last_offered in draft for context, but compute datetime for logic
    last_offered_raw = appointment.get("last_offered_slot_start_at")
    last_offered_dt = parse_date(last_offered_raw) if last_offered_raw else None

    if date_mentioned:
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
                return _finalize_response(
                    state,
                    assistant_text.strip(),
                    pending_question=PENDING_Q_ASK_DATETIME,
                    pending_intent=ClinicIntent.BOOK_APPOINTMENT,
                )
            return _finalize_response(
                state,
                "Could you tell me which day you prefer?",
                pending_question=PENDING_Q_ASK_DATETIME,
                pending_intent=ClinicIntent.BOOK_APPOINTMENT,
            )

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
        if pending_question == PENDING_Q_FINAL_CONFIRM and appointment.get("start_at") and appointment.get("end_at"):
            return _finalize_response(
                state,
                _build_final_review_text(appointment),
                pending_question=PENDING_Q_FINAL_CONFIRM,
                pending_intent=ClinicIntent.BOOK_APPOINTMENT,
            )
        return _finalize_response(
            state,
            "Do you have a preferred date, or should I book the earliest available?",
            pending_question=PENDING_Q_ASK_DATETIME,
            pending_intent=ClinicIntent.BOOK_APPOINTMENT,
        )

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
                    pending_question=PENDING_Q_ASK_DATETIME,
                    pending_intent=ClinicIntent.BOOK_APPOINTMENT,
                )

        slot = _pick_best_slot(slots, time_bucket)
        d_start_at = parse_date(slot.start_at)
        d_end_at = parse_date(slot.end_at)

        if d_start_at:
            appointment["start_at"] = d_start_at.isoformat()
            appointment["last_offered_slot_start_at"] = d_start_at.isoformat()
        if d_end_at:
            appointment["end_at"] = d_end_at.isoformat()
        offered = format_date(d_start_at) if d_start_at else "that time"
        return _finalize_response(
            state,
            f"I found {offered}. Does that work for you?",
            pending_question=PENDING_Q_SLOT_CONFIRM,
            pending_intent=ClinicIntent.BOOK_APPOINTMENT,
        )


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


async def _prepare_hold_for_final_confirmation(
    state: CallState,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> CallState | None:
    appointment = state.setdefault("appointment_draft", {})
    start_at = parse_date(appointment.get("start_at"))
    if not start_at:
        return _finalize_response(
            state,
            "What date and time would you like?",
            pending_question=PENDING_Q_ASK_DATETIME,
            pending_intent=ClinicIntent.BOOK_APPOINTMENT,
        )

    # Reuse existing hold when it matches current slot.
    held_id = state.get("held_appointment_id")
    view = state.get("appointment_view") or {}
    view_start = parse_date(view.get("start_at")) if isinstance(view, dict) else None
    if held_id and view_start and view_start == start_at:
        return None

    # Different slot requested: release previous hold first.
    if held_id:
        await _release_held_slot(state, sessionmaker=sessionmaker)

    notes = appointment.get("notes") or []
    if not isinstance(notes, list):
        notes = [str(notes)]

    async with sessionmaker() as session:
        uow = SqlAlchemyUnitOfWork(session)
        try:
            held_view = await hold_slot(
                uow,
                slot_start=start_at,
                name=appointment["name"],
                phone=appointment["phone"],
                reason_for_visit=appointment["reason_for_visit"],
                notes=notes,
            )
            state["appointment_view"] = held_view if isinstance(held_view, dict) else {}
            state["held_appointment_id"] = int((held_view or {}).get("id")) if isinstance(held_view, dict) and held_view.get("id") else None
            return None
        except SlotNotAvailable:
            next_slot = await _find_next_available_slot(sessionmaker, start_from=start_at)
            if next_slot:
                appointment["start_at"] = next_slot.start_at.isoformat()
                appointment["end_at"] = next_slot.end_at.isoformat()
                appointment["last_offered_slot_start_at"] = next_slot.start_at.isoformat()
                return _finalize_response(
                    state,
                    f"That slot was just taken. The next available is {format_date(next_slot.start_at)}. Does that work?",
                    pending_question=PENDING_Q_SLOT_CONFIRM,
                    pending_intent=ClinicIntent.BOOK_APPOINTMENT,
                )
            appointment.pop("start_at", None)
            appointment.pop("end_at", None)
            return _finalize_response(
                state,
                "That time is no longer available. Could you share another date range?",
                pending_question=PENDING_Q_ASK_DATETIME,
                pending_intent=ClinicIntent.BOOK_APPOINTMENT,
            )


async def node_book_appointment_node(
        state: CallState, *, sessionmaker: async_sessionmaker[AsyncSession]
) -> CallState:
    appointment = state.setdefault("appointment_draft", {})
    start_at = parse_date(appointment.get("start_at"))
    end_at = parse_date(appointment.get("end_at"))



    missing = [k for k in ("name", "phone", "reason_for_visit") if not appointment.get(k)]
    if not start_at:
        missing.append("start_at")
    if not end_at:
        missing.append("end_at")
    if missing:
        return _finalize_response(
            state,
            "I still need your "
            + ", ".join(missing).replace("_", " ")
            + ". Could you share that now?",
            pending_question=PENDING_Q_ASK_DATETIME,
            pending_intent=ClinicIntent.BOOK_APPOINTMENT,
        )
    held_id = state.get("held_appointment_id")
    if not held_id:
        # Safety fallback: hold now if missing.
        hold_result = await _prepare_hold_for_final_confirmation(
            state,
            sessionmaker=sessionmaker,
        )
        if hold_result is not None:
            return hold_result
        held_id = state.get("held_appointment_id")
    if not held_id:
        return _finalize_response(
            state,
            "I could not lock that time yet. Please confirm the date again.",
            pending_question=PENDING_Q_SLOT_CONFIRM,
            pending_intent=ClinicIntent.BOOK_APPOINTMENT,
        )

    async with sessionmaker() as session:
        uow = SqlAlchemyUnitOfWork(session)
        try:
            view = await confirm_appointment(
                uow,
                appointment_id=int(held_id),
            )
            logger.warning("----------\nconfirm_appointment view=%s\n-----------", view)
            state["appointment_view"] = view if isinstance(view, dict) else {}
            state["held_appointment_id"] = None
            state["pending_intent"] = None
            state["pending_question"] = None
        except NotFound:
            # HELD row may no longer exist, retry from scheduling.
            logger.warning("confirm_appointment failed, retrying from scheduling")
            state["held_appointment_id"] = None
            appointment.pop("start_at", None)
            appointment.pop("end_at", None)
            return _finalize_response(
                state,
                "I could not lock that slot anymore. Please share another date and time.",
                pending_question=PENDING_Q_ASK_DATETIME,
                pending_intent=ClinicIntent.BOOK_APPOINTMENT,
            )
        except Exception as e:
            logger.warning(f"confirm_appointment failed, {e}")
            return _finalize_response(
                state,
                "I hit a technical issue while finalizing that booking. Please confirm the time once more.",
                pending_question=PENDING_Q_FINAL_CONFIRM,
                pending_intent=ClinicIntent.BOOK_APPOINTMENT,
            )


    confirmation_text = (
        f"I booked it for {format_date(start_at)}. Please be here on time."
    )
    logger.warning("----------\nbooked confirmation: %s\n-----------", confirmation_text)
    return _finalize_response(
        state,
        confirmation_text,
        pending_question=None,
        pending_intent=None,
    )
