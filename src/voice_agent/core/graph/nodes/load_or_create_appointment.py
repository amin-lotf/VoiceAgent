from __future__ import annotations

import logging
from typing import Tuple

from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.graph.utils import run_non_interruptible
from voice_agent.core.types import CallState, AppointmentDraft, AppointmentView, AppointmentStatus
from voice_agent.core.services.appointments import (
    list_future_appointments_by_phone,
    create_appointment,
)

logger = logging.getLogger(__name__)


def _is_empty_appointment_view(view: object) -> bool:
    return not isinstance(view, dict) or not view.get("id")


async def node_load_or_create_appointment(
    state: CallState,
    *,
    sessionmaker,
) -> dict:
    """
    Ensures state['current_appointment_view'] exists once phone is known.

    Rules:
    - If phone is missing -> no-op
    - If current_appointment_view already exists -> no-op
    - Else:
        1) Look for earliest future active appointment by phone
        2) If found, load it into state
        3) If not found, create a new PENDING appointment
    """
    appointment_draft: AppointmentDraft = state.get("appointment_draft") or {}
    current_appointment_view: AppointmentView = state.get("current_appointment_view") or {}

    phone = (appointment_draft.get("phone") or "").strip()
    name = (appointment_draft.get("name") or "").strip()
    reason = (appointment_draft.get("reason_for_visit") or "").strip()

    # 1) No phone yet -> cannot load/create
    if not phone:
        logger.warning("load_or_create_appointment: skipped, phone missing")
        return {}

    # 2) Already have current_appointment_view -> no-op
    if not _is_empty_appointment_view(current_appointment_view):
        logger.warning(
            "load_or_create_appointment: skipped, current_appointment_view already exists id=%s",
            current_appointment_view.get("id"),
        )
        return {}

    async def _db_get_or_create() -> Tuple[AppointmentView,AppointmentView]:
        async with sessionmaker() as session:
            uow = SqlAlchemyUnitOfWork(session)
            
            existing_scheduled = await list_future_appointments_by_phone(
                uow,
                phone=phone,
                include_statuses=(AppointmentStatus.SCHEDULED,),
            )

            scheduled = existing_scheduled[0] if existing_scheduled else {}


            # Reuse earliest future active appointment for this phone
            existing_held = await list_future_appointments_by_phone(
                uow,
                phone=phone,
                include_statuses=(AppointmentStatus.HELD,),
            )

            if existing_held:
                # service returns ascending=True, so first one is earliest
                return existing_held[0],scheduled

            # No existing active future appointment -> create new PENDING
            # Guard required fields for creation
            if not name or not reason:
                raise ValueError(
                    "Cannot create appointment yet: name and reason_for_visit are required"
                )

            created = await create_appointment(
                uow,
                name=name,
                phone=phone,
                reason_for_visit=reason,
                notes=[],
            )
            return created,scheduled

    try:
        held_view,scheduled_view = await run_non_interruptible(state, _db_get_or_create)
    except ValueError as e:
        logger.warning("load_or_create_appointment: deferred create: %s", e)
        return {}
    except Exception:
        logger.exception("load_or_create_appointment: failed")
        return {}

    local_state: dict = {
        "current_appointment_view": held_view if isinstance(held_view, dict) else {},
        "scheduled_appointment_view": scheduled_view if isinstance(scheduled_view, dict) else {},
        "current_appointment_id": int(held_view["id"]) if isinstance(held_view, dict) and held_view.get("id") else None,
    }

    logger.warning(
        "load_or_create_appointment: ready id=%s status=%s",
        local_state.get("current_appointment_id"),
        held_view.get("status") if isinstance(held_view, dict) else None,
    )
    return local_state