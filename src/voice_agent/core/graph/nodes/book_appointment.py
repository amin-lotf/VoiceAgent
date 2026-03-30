from __future__ import annotations

import logging
from typing import Any

from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.graph.utils import run_non_interruptible
from voice_agent.core.services.appointments import (
    confirm_appointment,
    cancel_appointment,
)
from voice_agent.core.types import CallState, AppointmentView

logger = logging.getLogger(__name__)


def _get_appointment_id(view: object) -> int | None:
    if not isinstance(view, dict):
        return None

    raw_id = view.get("id")
    if raw_id in (None, ""):
        return None

    try:
        return int(raw_id)
    except (TypeError, ValueError):
        return None


async def node_book_appointment(
    state: CallState,
    *,
    sessionmaker,
) -> dict[str, Any]:
    """
    Confirm the currently held appointment.

    Flow:
    1) Confirm current_appointment_id -> SCHEDULED
    2) If state already has a scheduled_appointment_view, cancel that old appointment
    3) Assign the newly confirmed appointment to scheduled_appointment_view

    Rules:
    - If current_appointment_id is missing -> no-op
    - If old scheduled appointment has same id as held one -> do not cancel it
    - Runs DB writes in non-interruptible sections
    """

    held_id = state.get("current_appointment_id")
    if not held_id:
        logger.info("node_book_appointment: no current_appointment_id, skipping")
        return {}

    old_scheduled_view: AppointmentView = state.get("scheduled_appointment_view") or {}
    old_scheduled_id = _get_appointment_id(old_scheduled_view)

    async def _confirm() -> AppointmentView:
        async with sessionmaker() as session:
            uow = SqlAlchemyUnitOfWork(session)
            return await confirm_appointment(
                uow,
                appointment_id=int(held_id),
            )

    try:
        new_scheduled_view = await run_non_interruptible(state, _confirm)
    except Exception:
        logger.exception(
            "node_book_appointment: failed to confirm held appointment_id=%s",
            held_id,
        )
        return {}

    new_scheduled_id = _get_appointment_id(new_scheduled_view)

    # Cancel previous scheduled appointment only if it is different
    if old_scheduled_id and old_scheduled_id != new_scheduled_id:

        async def _cancel_old() -> AppointmentView:
            async with sessionmaker() as session:
                uow = SqlAlchemyUnitOfWork(session)
                return await cancel_appointment(
                    uow,
                    appointment_id=old_scheduled_id,
                )

        try:
            await run_non_interruptible(state, _cancel_old)
        except Exception:
            logger.exception(
                "node_book_appointment: confirmed new appointment_id=%s but failed to cancel old scheduled appointment_id=%s",
                new_scheduled_id,
                old_scheduled_id,
            )
            # keep the newly scheduled appointment in state anyway
            return {
                "scheduled_appointment_view": new_scheduled_view if isinstance(new_scheduled_view, dict) else {},
                "current_appointment_id": None,
                "pending_question": None,
                "is_pending_question": False,
            }
    return {
        "scheduled_appointment_view": new_scheduled_view if isinstance(new_scheduled_view, dict) else {},
        "current_appointment_id": None,
        "pending_question": None,
        "is_pending_question": False,
    }