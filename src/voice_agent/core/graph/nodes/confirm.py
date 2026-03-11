from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from voice_agent.core.db.uow import SqlAlchemyUnitOfWork

from voice_agent.const import DEFAULT_SEARCH_DAYS, EXPANDED_SEARCH_DAYS
from voice_agent.core.graph.const import PENDING_Q_ASK_DATETIME, PENDING_Q_SLOT_CONFIRM, PENDING_Q_FINAL_CONFIRM, \
    PENDING_Q_POST_BOOKING_NOTES
from voice_agent.core.graph.nodes.utils import parse_date, format_date
from voice_agent.core.graph.utils import run_non_interruptible
from voice_agent.core.services.appointments import delete_held_appointment, list_free_slots, hold_slot, \
    confirm_appointment
from voice_agent.core.services.exceptions import NotFound, SlotNotAvailable
from voice_agent.core.types import CallState, TimeSlot, ClinicIntent, AppointmentView


logger = logging.getLogger(__name__)


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
        route_to_reschedule: bool = False,
        speak: bool = True,
        pending_question: str | None ,
        pending_intent: ClinicIntent | None ,
) -> CallState:
    state["ready_to_confirm"] = route_to_booking
    state["ready_to_reschedule"] = route_to_reschedule

    if pending_intent is not None:
        state["pending_intent"] = pending_intent
    elif route_to_booking or route_to_reschedule:
        state["pending_intent"] = None

    if pending_question is not None:
        state["pending_question"] = pending_question

    if speak:
        _stream_response(state, text)
        state["assistant_text"] = text
    else:
        state["assistant_text"] = ""
        state["assistant_streamed"] = False

    return state

async def _release_held_slot(
        state: CallState,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    held_id = state.get("held_appointment_id")
    if not held_id:
        return

    async def _commit() -> None:
        async with sessionmaker() as session:
            uow = SqlAlchemyUnitOfWork(session)
            await delete_held_appointment(uow, appointment_id=int(held_id))

    try:
        run_non_interruptible(state, _commit)
    except NotFound:
        logger.info("release_held_slot skipped: appointment %s is not HELD", held_id)
    except Exception:
        logger.exception("release_held_slot failed for %s", held_id)
    state["held_appointment_id"] = None
    state["appointment_view"] = {}


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
            state["held_appointment_id"] = int((held_view or {}).get("id")) if isinstance(held_view,
                                                                                          dict) and held_view.get(
                "id") else None
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

    async def _commit() -> AppointmentView:
        async with sessionmaker() as session:
            uow = SqlAlchemyUnitOfWork(session)
            return await confirm_appointment(
                uow,
                appointment_id=int(held_id),
            )

    try:
        view = await run_non_interruptible(state, _commit)
        state["appointment_view"] = view if isinstance(view, dict) else {}
        state["appointment_id"] = int(view["id"]) if isinstance(view, dict) and view.get("id") else None
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
        f"I booked it for {format_date(start_at)}. Is there any condition or anything you want us to know?"
    )
    logger.warning("----------\nbooked confirmation: %s\n-----------", confirmation_text)
    return _finalize_response(
        state,
        confirmation_text,
        pending_question=PENDING_Q_POST_BOOKING_NOTES,
        pending_intent=ClinicIntent.POST_APPOINTMENT,
    )
