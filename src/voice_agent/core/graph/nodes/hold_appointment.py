from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.graph.utils import run_non_interruptible
from voice_agent.core.services.appointments import (
    list_free_slots,
    hold_appointment,
)
from voice_agent.core.types import CallState, AppointmentView
from voice_agent.core.settings import settings

logger = logging.getLogger(__name__)


def _parse_dt(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


async def node_hold_appointment(
    state: CallState,
    *,
    sessionmaker,
    search_days: int = 14,
) -> dict:
    """
    Finds the first free slot starting from state['slot_start'] and holds it
    on the current held/pending appointment.

    Rules:
    - If slot_start missing -> no-op
    - If held_appointment_id missing -> fallback to appointment_id
    - If no appointment id -> no-op
    - Search free slots from slot_start forward
    - Hold the first available slot
    """

    appointment_draft = state.get("appointment_draft") or {}

    raw_slot_start = appointment_draft.get("requested_time")
    slot_start = _parse_dt(raw_slot_start)

    appointment_id = state.get("held_appointment_id")

    if not slot_start:
        logger.warning("hold_appointment_node: skipped, slot_start missing/invalid")
        return {}

    if not appointment_id:
        logger.warning("hold_appointment_node: skipped, appointment id missing")
        return {}

    # Optional: never search in the past
    now = datetime.now(slot_start.tzinfo)
    if slot_start < now:
        slot_start = now

    end_range = slot_start + timedelta(days=search_days)

    async def _find_and_hold() -> AppointmentView:
        async with sessionmaker() as session:
            uow = SqlAlchemyUnitOfWork(session)

            free_slots = await list_free_slots(
                uow,
                start_range=slot_start,
                end_range=end_range,
            )

            if not free_slots:
                raise ValueError("No available slots found in search window")

            first_slot = free_slots[0]

            held_appt_view = await hold_appointment(
                uow,
                appointment_id=int(appointment_id),
                slot_start=first_slot.start_at,
            )
            return held_appt_view

    try:
        held_view = await run_non_interruptible(state, _find_and_hold)
    except ValueError as e:
        logger.warning("hold_appointment_node: %s", e)
        return {
            "held_appointment_view": {},
            "held_appointment_id": None,
            "last_offered_slot_start_at": None,
            "slot_found": False,
        }
    except Exception:
        logger.exception("hold_appointment_node: failed")
        return {
            "slot_found": False,
        }

    appointment_draft["last_offered_slot_start_at"]=held_view.get("start_at") if isinstance(held_view, dict) else None,

    local_state: dict = {
        "held_appointment_view": held_view if isinstance(held_view, dict) else {},
        "appointment_draft": appointment_draft,
    }

    logger.warning(
        "hold_appointment_node: held appointment_id=%s start_at=%s status=%s",
        local_state.get("held_appointment_id", "N/A"),
        held_view.get("start_at") if isinstance(held_view, dict) else None,
        held_view.get("status") if isinstance(held_view, dict) else None,
    )

    return local_state