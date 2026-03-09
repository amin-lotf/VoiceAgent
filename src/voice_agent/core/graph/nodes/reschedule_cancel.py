from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from langgraph.config import get_stream_writer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from voice_agent.const import DEFAULT_TZ
from voice_agent.core.db.mappers import to_view
from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.llm.openai_llm import LLM
from voice_agent.core.prompts.slot_filling import build_slot_fill_prompt
from voice_agent.core.prompts.slot_filling_basic import (
    build_local_confirmation_prompt,
    build_local_fast_extract_prompt,
)
from voice_agent.core.services.appointments import (
    cancel_appointment,
    list_free_slots,
    list_future_appointments_by_phone,
    reschedule_appointment,
)
from voice_agent.core.services.exceptions import NotFound, SlotNotAvailable
from voice_agent.core.settings import settings
from voice_agent.core.types import (
    AppointmentDraft,
    AppointmentStatus,
    AppointmentView,
    CallState,
    ClinicIntent,
    TimeSlot,
)

from .utils import call_llm_with_slow_filler, format_date, normalize_phone, parse_date, safe_json_parse

logger = logging.getLogger(__name__)

DEFAULT_SEARCH_DAYS = 7
EXPANDED_SEARCH_DAYS = 14

PENDING_Q_RC_ASK_PHONE = "reschedule_cancel_ask_phone"
PENDING_Q_RC_CHOOSE_ACTION = "reschedule_cancel_choose_action"
PENDING_Q_RC_ASK_DATETIME = "reschedule_cancel_ask_datetime"
PENDING_Q_RC_SLOT_CONFIRM = "reschedule_cancel_confirm_slot"
PENDING_Q_RC_CANCEL_CONFIRM = "reschedule_cancel_confirm_cancel"

_KEEP = object()


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
    route_to_update: bool = False,
    speak: bool = True,
    pending_question: str | None | object = _KEEP,
    pending_intent: ClinicIntent | None | object = _KEEP,
) -> CallState:
    state["ready_to_update"] = route_to_update
    if pending_intent is not _KEEP:
        state["pending_intent"] = pending_intent
    elif route_to_update:
        state["pending_intent"] = None

    if pending_question is not _KEEP:
        state["pending_question"] = pending_question

    if speak:
        _stream_response(state, text)
    else:
        state["assistant_text"] = ""
        state["assistant_streamed"] = False
    return state


def _active_status(status: Any) -> bool:
    if isinstance(status, AppointmentStatus):
        return status in {AppointmentStatus.HELD, AppointmentStatus.SCHEDULED}
    try:
        raw = getattr(status, "value", status)
        return AppointmentStatus(str(raw)) in {AppointmentStatus.HELD, AppointmentStatus.SCHEDULED}
    except Exception:
        return False


def _candidate_appointment_id(state: CallState) -> int | None:
    for key in ("appointment_id", "held_appointment_id"):
        raw = state.get(key)
        if raw is None:
            continue
        try:
            return int(raw)
        except Exception:
            continue
    view = state.get("appointment_view") or {}
    if isinstance(view, dict) and view.get("id") is not None:
        try:
            return int(view.get("id"))
        except Exception:
            return None
    return None


def _action_from_intent(intent: ClinicIntent | None) -> Literal["reschedule", "cancel"] | None:
    if intent == ClinicIntent.RESCHEDULE:
        return "reschedule"
    if intent == ClinicIntent.CANCEL:
        return "cancel"
    return None


def _action_from_text(user_text: str) -> Literal["reschedule", "cancel"] | None:
    text = f" {(user_text or '').strip().lower()} "
    if not text.strip():
        return None

    cancel_cues = (" cancel ", " call off ", " remove ", " delete ")
    if any(c in text for c in cancel_cues):
        return "cancel"

    reschedule_cues = (
        " reschedule ",
        " change ",
        " move ",
        " another time ",
        " different time ",
        " different day ",
        " new time ",
        " new date ",
    )
    if any(c in text for c in reschedule_cues):
        return "reschedule"
    return None


def _pending_intent_for_flow(state: CallState) -> ClinicIntent:
    action = state.get("update_action")
    if action == "cancel":
        return ClinicIntent.CANCEL
    if action == "reschedule":
        return ClinicIntent.RESCHEDULE
    intent = state.get("intent")
    if intent in {ClinicIntent.RESCHEDULE, ClinicIntent.CANCEL}:
        return intent
    return ClinicIntent.RESCHEDULE


def _apply_view_to_state(state: CallState, view: AppointmentView) -> None:
    state["appointment_view"] = view
    state["appointment_id"] = int(view.get("id")) if view.get("id") else None
    if view.get("status") == AppointmentStatus.HELD:
        state["held_appointment_id"] = int(view.get("id")) if view.get("id") else None
    else:
        state["held_appointment_id"] = None

    appointment = state.setdefault("appointment_draft", {})
    appointment["name"] = view.get("name") or appointment.get("name")
    phone = normalize_phone(view.get("phone")) if isinstance(view.get("phone"), str) else None
    if phone:
        appointment["phone"] = phone
    appointment["reason_for_visit"] = view.get("reason_for_visit") or appointment.get("reason_for_visit")
    if isinstance(view.get("start_at"), str):
        appointment["start_at"] = view["start_at"]
        appointment["last_offered_slot_start_at"] = view["start_at"]
    if isinstance(view.get("end_at"), str):
        appointment["end_at"] = view["end_at"]


def _found_appointment_text(view: AppointmentView) -> str:
    name = view.get("name") or "unknown"
    when = "the scheduled time"
    start_at = parse_date(view.get("start_at"))
    if start_at:
        when = format_date(start_at)
    return (
        f"I found your appointment under name {name} for {when}. "
        "Would you like to change the date or cancel it?"
    )


async def _lookup_appointment_by_id(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    appointment_id: int,
) -> AppointmentView | None:
    async with sessionmaker() as session:
        uow = SqlAlchemyUnitOfWork(session)
        async with uow:
            row = await uow.appointments.get(appointment_id)
            if row is None:
                return None
            if row.status not in {AppointmentStatus.HELD, AppointmentStatus.SCHEDULED}:
                return None
            return to_view(row)


async def _lookup_appointments_by_phone(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    phone: str,
    now: datetime,
) -> list[AppointmentView]:
    async with sessionmaker() as session:
        uow = SqlAlchemyUnitOfWork(session)
        return await list_future_appointments_by_phone(uow, phone=phone, now=now)


def _extract_appointment_basic(appointment: AppointmentDraft) -> AppointmentDraft:
    return dict(
        name=appointment.get("name"),
        phone=appointment.get("phone"),
        reason_for_visit=appointment.get("reason_for_visit"),
        last_offered_slot_start_at=appointment.get("last_offered_slot_start_at"),
    )


def _merge_patch(appointment: AppointmentDraft, patch: dict) -> None:
    for key in ("name", "phone", "reason_for_visit"):
        val = patch.get(key)
        if isinstance(val, str) and val.strip():
            if key == "phone":
                norm = normalize_phone(val)
                if norm:
                    appointment[key] = norm
            else:
                appointment[key] = val.strip()

    for key in ("schedule_intent", "desired_start_at", "search_days", "time_bucket", "assistant_text", "clarify_reason"):
        if key in patch:
            appointment[key] = patch.get(key)


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
        resp = await LLM.ainvoke(prompt)
        t1 = time.perf_counter()
        raw = getattr(resp, "content", "") or ""
        parsed = safe_json_parse(raw, logger=logger)
        logger.warning(
            "reschedule_cancel confirm_intent time=%0.2fs raw=%s parsed=%s",
            t1 - t0,
            raw,
            parsed,
        )
        intent = str((parsed or {}).get("intent") or "").strip().lower()
        if intent in {"confirm", "revise", "unclear"}:
            return intent
    except Exception:
        logger.exception("reschedule_cancel confirm_intent failed")
    return "unclear"


async def _run_local_extract(
    *,
    user_text: str,
    appointment: AppointmentDraft,
    now: datetime,
) -> tuple[dict, bool]:
    prompt = build_local_fast_extract_prompt(
        user_text=user_text,
        appointment=_extract_appointment_basic(appointment),
        now=now,
    )
    try:
        t0 = time.perf_counter()
        resp = await LLM.ainvoke(prompt)
        t1 = time.perf_counter()
        raw = getattr(resp, "content", "") or ""
        parsed = safe_json_parse(raw, logger=logger)
        logger.warning(
            "reschedule_cancel local_extract time=%0.2fs raw=%s parsed=%s",
            t1 - t0,
            raw,
            parsed,
        )
        if isinstance(parsed, dict):
            return parsed.get("patch") or {}, bool(parsed.get("date_mentioned") or False)
    except Exception:
        logger.exception("reschedule_cancel local_extract failed")
    return {}, False


async def _resolve_schedule_patch(
    *,
    user_text: str,
    state: CallState,
    appointment: AppointmentDraft,
    now: datetime,
    last_offered: str | None,
) -> tuple[dict, str]:
    resolver_prompt = build_slot_fill_prompt(
        user_text=user_text,
        state=state,
        appointment=appointment,
        now=now,
        last_offered=last_offered,
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
        parsed = safe_json_parse(raw, logger=logger)
        logger.warning(
            "reschedule_cancel schedule_resolve time=%0.2fs raw=%s parsed=%s",
            t1 - t0,
            raw,
            parsed,
        )
        if isinstance(parsed, dict):
            patch = parsed.get("patch") or {}
            return patch, str(patch.get("schedule_intent") or "unspecified")
    except Exception:
        logger.exception("reschedule_cancel schedule_resolve failed")
    return {}, "unspecified"


def _compute_search_window(
    *,
    schedule_intent: str,
    patch: dict,
    now: datetime,
    last_offered: datetime | None,
) -> tuple[datetime | None, datetime | None, str | None]:
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
        start = max(anchor, now)
        end = start + timedelta(days=days)
        return start, end, bucket

    if schedule_intent == "reject_and_search":
        start = (last_offered + timedelta(minutes=1)) if last_offered else (now + timedelta(minutes=1))
        end = start + timedelta(days=days)
        return start, end, bucket

    return None, None, bucket


def _bucket_match(dt: datetime, bucket: str | None) -> bool:
    if bucket is None:
        return True
    h = dt.hour
    if bucket == "morning":
        return h < 12
    if bucket == "afternoon":
        return 12 <= h < 17
    if bucket == "evening":
        return h >= 17
    return True


def _pick_best_slot(slots: list[TimeSlot], bucket: str | None) -> TimeSlot:
    matching: list[TimeSlot] = []
    for slot in slots:
        dt = parse_date(getattr(slot, "start_at", None))
        if dt and _bucket_match(dt, bucket):
            matching.append(slot)
    if matching:
        return min(matching, key=lambda s: s.start_at)
    return min(slots, key=lambda s: s.start_at)


def _clear_update_context(state: CallState) -> None:
    state["ready_to_update"] = False
    state["pending_question"] = None
    state["pending_intent"] = None
    state["update_action"] = None


async def _handle_reschedule_datetime(
    state: CallState,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    user_text: str,
    now: datetime,
) -> CallState:
    appointment: AppointmentDraft = state.setdefault("appointment_draft", {})
    pending_question = str(state.get("pending_question") or "")

    local_patch, date_mentioned = await _run_local_extract(
        user_text=user_text,
        appointment=appointment,
        now=now,
    )
    _merge_patch(appointment, local_patch)

    if pending_question == PENDING_Q_RC_SLOT_CONFIRM:
        confirm_intent = await _classify_confirmation_intent(
            user_text=user_text,
            appointment=appointment,
            pending_question=PENDING_Q_RC_SLOT_CONFIRM,
            prior_assistant_text=state.get("prev_assistant_text"),
        )
        if confirm_intent == "confirm" and not date_mentioned:
            return _finalize_response(
                state,
                "",
                route_to_update=True,
                speak=False,
                pending_question=None,
                pending_intent=None,
            )
        if confirm_intent == "unclear" and not date_mentioned:
            return _finalize_response(
                state,
                "Does that new appointment time work for you?",
                pending_question=PENDING_Q_RC_SLOT_CONFIRM,
                pending_intent=ClinicIntent.RESCHEDULE,
            )

    if not date_mentioned:
        return _finalize_response(
            state,
            "What date and time would you like instead?",
            pending_question=PENDING_Q_RC_ASK_DATETIME,
            pending_intent=ClinicIntent.RESCHEDULE,
        )

    last_offered_raw = appointment.get("last_offered_slot_start_at")
    schedule_patch, schedule_intent = await _resolve_schedule_patch(
        user_text=user_text,
        state=state,
        appointment=appointment,
        now=now,
        last_offered=last_offered_raw,
    )
    _merge_patch(appointment, schedule_patch)

    if schedule_intent == "clarify":
        assistant_text = schedule_patch.get("assistant_text")
        if isinstance(assistant_text, str) and assistant_text.strip():
            return _finalize_response(
                state,
                assistant_text.strip(),
                pending_question=PENDING_Q_RC_ASK_DATETIME,
                pending_intent=ClinicIntent.RESCHEDULE,
            )
        return _finalize_response(
            state,
            "Could you tell me which day you prefer?",
            pending_question=PENDING_Q_RC_ASK_DATETIME,
            pending_intent=ClinicIntent.RESCHEDULE,
        )

    last_offered_dt = parse_date(appointment.get("last_offered_slot_start_at"))
    start_range, end_range, time_bucket = _compute_search_window(
        schedule_intent=schedule_intent,
        patch=schedule_patch,
        now=now,
        last_offered=last_offered_dt,
    )

    if schedule_intent == "unspecified" or start_range is None or end_range is None:
        return _finalize_response(
            state,
            "Do you prefer a specific date, or should I find the earliest available?",
            pending_question=PENDING_Q_RC_ASK_DATETIME,
            pending_intent=ClinicIntent.RESCHEDULE,
        )

    async with sessionmaker() as session:
        uow = SqlAlchemyUnitOfWork(session)
        slots = await list_free_slots(uow, start_range=start_range, end_range=end_range)
        if not slots:
            fallback_start = max(now, end_range + timedelta(minutes=1))
            fallback_end = fallback_start + timedelta(days=EXPANDED_SEARCH_DAYS)
            slots = await list_free_slots(uow, start_range=fallback_start, end_range=fallback_end)
        if not slots:
            appointment.pop("start_at", None)
            appointment.pop("end_at", None)
            return _finalize_response(
                state,
                "I am not seeing openings in the next couple of weeks. Could you share another date range?",
                pending_question=PENDING_Q_RC_ASK_DATETIME,
                pending_intent=ClinicIntent.RESCHEDULE,
            )

    slot = _pick_best_slot(slots, time_bucket)
    start_at = parse_date(slot.start_at)
    end_at = parse_date(slot.end_at)
    if start_at:
        appointment["start_at"] = start_at.isoformat()
        appointment["last_offered_slot_start_at"] = start_at.isoformat()
    if end_at:
        appointment["end_at"] = end_at.isoformat()

    offered = format_date(start_at) if start_at else "that time"
    return _finalize_response(
        state,
        f"I found {offered}. Does that new time work for you?",
        pending_question=PENDING_Q_RC_SLOT_CONFIRM,
        pending_intent=ClinicIntent.RESCHEDULE,
    )


async def node_reschedule_cancel_node(
    state: CallState,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> CallState:
    appointment = state.setdefault("appointment_draft", {})
    user_text = (state.get("user_text") or "").strip()
    pending_question = str(state.get("pending_question") or "")
    now = _get_now(state)
    state["ready_to_update"] = False

    action = _action_from_text(user_text)
    if action is None and state.get("update_action") in {"reschedule", "cancel"}:
        action = state["update_action"]
    if action is None:
        action = _action_from_intent(state.get("intent"))
    if action:
        state["update_action"] = action

    view = state.get("appointment_view") if isinstance(state.get("appointment_view"), dict) else None
    if view and not _active_status(view.get("status")):
        view = None
        state["appointment_view"] = {}
        state["appointment_id"] = None

    appointment_id = _candidate_appointment_id(state)
    if appointment_id and not view:
        found = await _lookup_appointment_by_id(
            sessionmaker=sessionmaker,
            appointment_id=appointment_id,
        )
        if found is not None:
            _apply_view_to_state(state, found)
            view = found
        else:
            state["appointment_id"] = None
            if state.get("held_appointment_id") == appointment_id:
                state["held_appointment_id"] = None

    if not view:
        if pending_question != PENDING_Q_RC_ASK_PHONE:
            return _finalize_response(
                state,
                "I can help with that. What phone number is the appointment under?",
                pending_question=PENDING_Q_RC_ASK_PHONE,
                pending_intent=_pending_intent_for_flow(state),
            )
        phone = normalize_phone(user_text) or normalize_phone(appointment.get("phone"))
        if not phone:
            return _finalize_response(
                state,
                "Please share the phone number linked to your appointment.",
                pending_question=PENDING_Q_RC_ASK_PHONE,
                pending_intent=_pending_intent_for_flow(state),
            )
        appointment["phone"] = phone
        matches = await _lookup_appointments_by_phone(
            sessionmaker=sessionmaker,
            phone=phone,
            now=now,
        )
        if not matches:
            return _finalize_response(
                state,
                "I could not find an upcoming appointment with that number. Can you repeat the number?",
                pending_question=PENDING_Q_RC_ASK_PHONE,
                pending_intent=_pending_intent_for_flow(state),
            )
        _apply_view_to_state(state, matches[0])
        view = matches[0]

    if pending_question == PENDING_Q_RC_CANCEL_CONFIRM:
        text_action = _action_from_text(user_text)
        if text_action == "cancel":
            state["update_action"] = "cancel"
            return _finalize_response(
                state,
                "",
                route_to_update=True,
                speak=False,
                pending_question=None,
                pending_intent=None,
            )
        if text_action == "reschedule":
            state["update_action"] = "reschedule"
            return _finalize_response(
                state,
                "Okay, we will keep it active. What date and time would you like instead?",
                pending_question=PENDING_Q_RC_ASK_DATETIME,
                pending_intent=ClinicIntent.RESCHEDULE,
            )

        confirm_intent = await _classify_confirmation_intent(
            user_text=user_text,
            appointment=appointment,
            pending_question=PENDING_Q_RC_CANCEL_CONFIRM,
            prior_assistant_text=state.get("prev_assistant_text"),
        )
        if confirm_intent == "confirm":
            state["update_action"] = "cancel"
            return _finalize_response(
                state,
                "",
                route_to_update=True,
                speak=False,
                pending_question=None,
                pending_intent=None,
            )
        if confirm_intent == "revise":
            return _finalize_response(
                state,
                _found_appointment_text(view),
                pending_question=PENDING_Q_RC_CHOOSE_ACTION,
                pending_intent=_pending_intent_for_flow(state),
            )
        when = format_date(parse_date(view.get("start_at"))) if view else "that time"
        return _finalize_response(
            state,
            f"Please confirm if you want me to cancel the appointment on {when}.",
            pending_question=PENDING_Q_RC_CANCEL_CONFIRM,
            pending_intent=ClinicIntent.CANCEL,
        )

    # If the caller already stated a concrete action, skip the generic
    # "change date or cancel?" prompt and jump directly to that branch.
    if state.get("update_action") == "cancel" and pending_question != PENDING_Q_RC_CANCEL_CONFIRM:
        when = format_date(parse_date(view.get("start_at"))) if view else "that time"
        return _finalize_response(
            state,
            f"Okay, do you want me to cancel the appointment on {when}?",
            pending_question=PENDING_Q_RC_CANCEL_CONFIRM,
            pending_intent=ClinicIntent.CANCEL,
        )

    if state.get("update_action") == "reschedule" and pending_question not in {
        PENDING_Q_RC_ASK_DATETIME,
        PENDING_Q_RC_SLOT_CONFIRM,
    }:
        return _finalize_response(
            state,
            "Sure, what date and time would you like instead?",
            pending_question=PENDING_Q_RC_ASK_DATETIME,
            pending_intent=ClinicIntent.RESCHEDULE,
        )

    if state.get("update_action") == "reschedule" and pending_question in {
        PENDING_Q_RC_ASK_DATETIME,
        PENDING_Q_RC_SLOT_CONFIRM,
    }:
        return await _handle_reschedule_datetime(
            state,
            sessionmaker=sessionmaker,
            user_text=user_text,
            now=now,
        )

    if pending_question == PENDING_Q_RC_CHOOSE_ACTION:
        chosen = _action_from_text(user_text)
        if chosen is None:
            confirm_intent = await _classify_confirmation_intent(
                user_text=user_text,
                appointment=appointment,
                pending_question=PENDING_Q_RC_CHOOSE_ACTION,
                prior_assistant_text=state.get("prev_assistant_text"),
            )
            if confirm_intent == "confirm" and state.get("update_action") in {"reschedule", "cancel"}:
                chosen = state["update_action"]
        if chosen == "reschedule":
            state["update_action"] = "reschedule"
            return _finalize_response(
                state,
                "Sure, what date and time would you like instead?",
                pending_question=PENDING_Q_RC_ASK_DATETIME,
                pending_intent=ClinicIntent.RESCHEDULE,
            )
        if chosen == "cancel":
            state["update_action"] = "cancel"
            when = format_date(parse_date(view.get("start_at"))) if view else "that time"
            return _finalize_response(
                state,
                f"Okay, do you want me to cancel the appointment on {when}?",
                pending_question=PENDING_Q_RC_CANCEL_CONFIRM,
                pending_intent=ClinicIntent.CANCEL,
            )
        return _finalize_response(
            state,
            "Please tell me if you want to change the date or cancel it.",
            pending_question=PENDING_Q_RC_CHOOSE_ACTION,
            pending_intent=_pending_intent_for_flow(state),
        )

    return _finalize_response(
        state,
        _found_appointment_text(view),
        pending_question=PENDING_Q_RC_CHOOSE_ACTION,
        pending_intent=_pending_intent_for_flow(state),
    )


async def node_update_appointment_node(
    state: CallState,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> CallState:
    state["ready_to_update"] = False

    action = state.get("update_action")
    appointment_id = _candidate_appointment_id(state)
    appointment = state.setdefault("appointment_draft", {})

    if not appointment_id:
        state["appointment_view"] = {}
        state["appointment_id"] = None
        return _finalize_response(
            state,
            "I could not find the appointment to update. What phone number is it under?",
            pending_question=PENDING_Q_RC_ASK_PHONE,
            pending_intent=_pending_intent_for_flow(state),
        )

    if action == "cancel":
        try:
            async with sessionmaker() as session:
                uow = SqlAlchemyUnitOfWork(session)
                view = await cancel_appointment(uow, appointment_id=int(appointment_id))
            _apply_view_to_state(state, view)
            _clear_update_context(state)
            when = format_date(parse_date(view.get("start_at")))
            return _finalize_response(
                state,
                f"Done. I canceled your appointment for {when}.",
                pending_question=None,
                pending_intent=None,
            )
        except NotFound:
            state["appointment_view"] = {}
            state["appointment_id"] = None
            return _finalize_response(
                state,
                "I could not find an active appointment to cancel. What phone number is it under?",
                pending_question=PENDING_Q_RC_ASK_PHONE,
                pending_intent=ClinicIntent.CANCEL,
            )
        except Exception:
            logger.exception("cancel update failed for appointment %s", appointment_id)
            return _finalize_response(
                state,
                "I hit a technical issue while canceling that appointment. Please confirm again.",
                pending_question=PENDING_Q_RC_CANCEL_CONFIRM,
                pending_intent=ClinicIntent.CANCEL,
            )

    if action == "reschedule":
        start_at = parse_date(appointment.get("start_at"))
        if not start_at:
            return _finalize_response(
                state,
                "I still need the new appointment date and time.",
                pending_question=PENDING_Q_RC_ASK_DATETIME,
                pending_intent=ClinicIntent.RESCHEDULE,
            )
        try:
            async with sessionmaker() as session:
                uow = SqlAlchemyUnitOfWork(session)
                view = await reschedule_appointment(
                    uow,
                    appointment_id=int(appointment_id),
                    slot_start=start_at,
                )
            _apply_view_to_state(state, view)
            _clear_update_context(state)
            when = format_date(parse_date(view.get("start_at")))
            return _finalize_response(
                state,
                f"Done. I moved your appointment to {when}.",
                pending_question=None,
                pending_intent=None,
            )
        except SlotNotAvailable:
            appointment.pop("start_at", None)
            appointment.pop("end_at", None)
            return _finalize_response(
                state,
                "That time was just taken. Please share another date and time.",
                pending_question=PENDING_Q_RC_ASK_DATETIME,
                pending_intent=ClinicIntent.RESCHEDULE,
            )
        except NotFound:
            state["appointment_view"] = {}
            state["appointment_id"] = None
            return _finalize_response(
                state,
                "I could not find an active appointment to reschedule. What phone number is it under?",
                pending_question=PENDING_Q_RC_ASK_PHONE,
                pending_intent=ClinicIntent.RESCHEDULE,
            )
        except Exception:
            logger.exception("reschedule update failed for appointment %s", appointment_id)
            return _finalize_response(
                state,
                "I hit a technical issue while updating that appointment. Please confirm the new time again.",
                pending_question=PENDING_Q_RC_SLOT_CONFIRM,
                pending_intent=ClinicIntent.RESCHEDULE,
            )

    return _finalize_response(
        state,
        "Would you like to change the date or cancel the appointment?",
        pending_question=PENDING_Q_RC_CHOOSE_ACTION,
        pending_intent=_pending_intent_for_flow(state),
    )
