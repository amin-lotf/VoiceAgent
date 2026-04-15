from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import voice_agent.core.graph.nodes.book_appointment as book_node
import voice_agent.core.graph.nodes.hold_appointment as hold_node
import voice_agent.core.graph.nodes.patch_resolver as patch_node
import voice_agent.core.services.appointments as appointment_services
from voice_agent.core.services.appointments import HoldAppointmentResult, ScheduleAppointmentResult
from voice_agent.core.types import AppointmentStatus, AssistantPhase, NextAction


TZ = ZoneInfo("Asia/Taipei")


def _view(
    *,
    appointment_id: int,
    status: AppointmentStatus,
    start_at: str | None,
    end_at: str | None,
    name: str = "Jane Doe",
    phone: str = "5551234567",
    reason_for_visit: str = "Checkup",
    notes: list[str] | None = None,
) -> dict:
    return {
        "id": appointment_id,
        "name": name,
        "phone": phone,
        "reason_for_visit": reason_for_visit,
        "start_at": start_at,
        "end_at": end_at,
        "notes": list(notes or []),
        "status": status,
        "created_at": "2099-04-15T09:00:00+08:00",
        "updated_at": "2099-04-15T09:00:00+08:00",
    }


class _DummySessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _sessionmaker():
    return _DummySessionContext()


class _BusyRepo:
    def __init__(self, busy_items: list[SimpleNamespace]) -> None:
        self._busy_items = busy_items

    async def list_busy_between(
        self,
        *,
        start_range,
        end_range,
        active_statuses,
        exclude_appointment_id=None,
    ):
        if exclude_appointment_id is None:
            return list(self._busy_items)
        return [item for item in self._busy_items if item.id != exclude_appointment_id]


class _BusyUow:
    def __init__(self, busy_items: list[SimpleNamespace]) -> None:
        self.appointments = _BusyRepo(busy_items)


@pytest.mark.asyncio
async def test_find_first_available_slot_returns_next_open_slot():
    requested_start = datetime(2099, 4, 16, 10, 0, tzinfo=TZ)
    busy_items = [
        SimpleNamespace(
            id=1,
            start_at=requested_start,
            end_at=requested_start + timedelta(minutes=30),
        ),
        SimpleNamespace(
            id=2,
            start_at=requested_start + timedelta(minutes=30),
            end_at=requested_start + timedelta(minutes=60),
        ),
    ]

    slot = await appointment_services._find_first_available_slot(
        _BusyUow(busy_items),
        requested_start=requested_start,
    )

    assert slot.start_at == requested_start + timedelta(minutes=60)
    assert slot.end_at == requested_start + timedelta(minutes=90)


@pytest.mark.asyncio
async def test_find_first_available_slot_excludes_existing_held_appointment():
    requested_start = datetime(2099, 4, 16, 10, 0, tzinfo=TZ)
    busy_items = [
        SimpleNamespace(
            id=1,
            start_at=requested_start,
            end_at=requested_start + timedelta(minutes=30),
        ),
        SimpleNamespace(
            id=2,
            start_at=requested_start + timedelta(minutes=30),
            end_at=requested_start + timedelta(minutes=60),
        ),
    ]

    slot = await appointment_services._find_first_available_slot(
        _BusyUow(busy_items),
        requested_start=requested_start,
        exclude_appointment_id=1,
    )

    assert slot.start_at == requested_start
    assert slot.end_at == requested_start + timedelta(minutes=30)


@pytest.mark.asyncio
async def test_node_hold_appointment_persists_hold_and_tracks_views(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}
    held_view = _view(
        appointment_id=11,
        status=AppointmentStatus.HELD,
        start_at="2099-04-16T10:30:00+08:00",
        end_at="2099-04-16T11:00:00+08:00",
        notes=["Bring insurance card"],
    )
    scheduled_view = _view(
        appointment_id=7,
        status=AppointmentStatus.SCHEDULED,
        start_at="2099-04-15T09:00:00+08:00",
        end_at="2099-04-15T09:30:00+08:00",
        notes=["Existing note"],
    )

    async def fake_run_non_interruptible(state, fn):
        captured["used_non_interruptible"] = True
        return await fn()

    async def fake_hold_requested_appointment(uow, **kwargs):
        captured["hold_kwargs"] = kwargs
        return HoldAppointmentResult(
            held_view=held_view,
            scheduled_view=scheduled_view,
        )

    monkeypatch.setattr(hold_node, "run_non_interruptible", fake_run_non_interruptible)
    monkeypatch.setattr(hold_node, "hold_requested_appointment", fake_hold_requested_appointment)

    state = {
        "appointment_draft": {
            "name": "Jane Doe",
            "phone": "5551234567",
            "reason_for_visit": "Checkup",
            "requested_time_iso": "2099-04-16T10:00:00+08:00",
            "notes": [],
        }
    }

    local_state = await hold_node.node_hold_appointment(state, sessionmaker=_sessionmaker)

    assert captured["used_non_interruptible"] is True
    assert captured["hold_kwargs"]["requested_slot_start"].isoformat() == "2099-04-16T10:00:00+08:00"
    assert local_state["held_appointment_view"] == held_view
    assert local_state["scheduled_appointment_view"] == scheduled_view
    assert local_state["appointment_draft"]["requested_time_iso"] == "2099-04-16T10:00:00+08:00"
    assert local_state["appointment_draft"]["last_offered_slot_start_at"] == held_view["start_at"]
    assert local_state["appointment_draft"]["notes"] == ["Bring insurance card"]
    assert local_state["appointment_draft"]["status"] == AppointmentStatus.HELD
    assert local_state["assistant_phase"] == AssistantPhase.HOLDING_APPOINTMENT
    assert local_state["next_action"] == NextAction.CALL_OPERATOR
    assert local_state["current_appointment_id"] == 11


@pytest.mark.asyncio
async def test_node_book_appointment_promotes_held_and_clears_held_view(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}
    scheduled_view = _view(
        appointment_id=11,
        status=AppointmentStatus.SCHEDULED,
        start_at="2099-04-16T10:30:00+08:00",
        end_at="2099-04-16T11:00:00+08:00",
        notes=["Bring insurance card"],
    )

    async def fake_run_non_interruptible(state, fn):
        captured["used_non_interruptible"] = True
        return await fn()

    async def fake_schedule_held_appointment(uow, *, held_appointment_id, scheduled_appointment_id):
        captured["held_appointment_id"] = held_appointment_id
        captured["scheduled_appointment_id"] = scheduled_appointment_id
        return ScheduleAppointmentResult(
            scheduled_view=scheduled_view,
            deleted_scheduled_view=_view(
                appointment_id=7,
                status=AppointmentStatus.SCHEDULED,
                start_at="2099-04-15T09:00:00+08:00",
                end_at="2099-04-15T09:30:00+08:00",
            ),
        )

    monkeypatch.setattr(book_node, "run_non_interruptible", fake_run_non_interruptible)
    monkeypatch.setattr(book_node, "schedule_held_appointment", fake_schedule_held_appointment)

    state = {
        "appointment_draft": {
            "name": "Jane Doe",
            "phone": "5551234567",
            "reason_for_visit": "Checkup",
            "status": AppointmentStatus.HELD,
            "last_offered_slot_start_at": "2099-04-16T10:30:00+08:00",
            "notes": [],
        },
        "held_appointment_view": _view(
            appointment_id=11,
            status=AppointmentStatus.HELD,
            start_at="2099-04-16T10:30:00+08:00",
            end_at="2099-04-16T11:00:00+08:00",
        ),
        "scheduled_appointment_view": _view(
            appointment_id=7,
            status=AppointmentStatus.SCHEDULED,
            start_at="2099-04-15T09:00:00+08:00",
            end_at="2099-04-15T09:30:00+08:00",
        ),
    }

    local_state = await book_node.node_book_appointment(state, sessionmaker=_sessionmaker)

    assert captured["used_non_interruptible"] is True
    assert captured["held_appointment_id"] == 11
    assert captured["scheduled_appointment_id"] == 7
    assert local_state["scheduled_appointment_view"] == scheduled_view
    assert local_state["held_appointment_view"] == {}
    assert local_state["appointment_draft"]["status"] == AppointmentStatus.SCHEDULED
    assert local_state["appointment_draft"]["offered_time_confirmed"] is True
    assert local_state["appointment_draft"]["notes"] == ["Bring insurance card"]
    assert local_state["assistant_phase"] == AssistantPhase.POST_APPOINTMENT
    assert local_state["next_action"] == NextAction.CALL_OPERATOR
    assert local_state["current_appointment_id"] == 11


def test_build_sync_plan_respects_held_vs_scheduled_targets():
    assert patch_node._build_sync_plan(
        appointment_status=AppointmentStatus.HELD,
        held_id=11,
        scheduled_id=7,
    ) == [
        ("held_appointment_view", 11, True),
        ("scheduled_appointment_view", 7, False),
    ]
    assert patch_node._build_sync_plan(
        appointment_status=AppointmentStatus.SCHEDULED,
        held_id=11,
        scheduled_id=7,
    ) == [
        ("scheduled_appointment_view", 7, True),
    ]


@pytest.mark.asyncio
async def test_node_patch_resolver_syncs_both_views_during_held_reschedule(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}

    async def fake_sync_views_from_draft(state, *, sessionmaker, sync_plan, appointment_draft):
        captured["sync_plan"] = sync_plan
        captured["appointment_draft"] = appointment_draft
        return {
            "held_appointment_view": _view(
                appointment_id=11,
                status=AppointmentStatus.HELD,
                start_at="2099-04-16T10:30:00+08:00",
                end_at="2099-04-16T11:00:00+08:00",
                name="Janet Doe",
                notes=["Existing note", "Call ahead"],
            ),
            "scheduled_appointment_view": _view(
                appointment_id=7,
                status=AppointmentStatus.SCHEDULED,
                start_at="2099-04-15T09:00:00+08:00",
                end_at="2099-04-15T09:30:00+08:00",
                name="Janet Doe",
                notes=["Existing note"],
            ),
        }

    monkeypatch.setattr(patch_node, "_sync_views_from_draft", fake_sync_views_from_draft)

    state = {
        "appointment_draft": {
            "name": "Jane Doe",
            "phone": "5551234567",
            "reason_for_visit": "Checkup",
            "notes": ["Existing note"],
            "status": AppointmentStatus.HELD,
        },
        "appointment_patch": {
            "name": "Janet Doe",
            "notes": ["Call ahead"],
        },
        "held_appointment_view": _view(
            appointment_id=11,
            status=AppointmentStatus.HELD,
            start_at="2099-04-16T10:30:00+08:00",
            end_at="2099-04-16T11:00:00+08:00",
        ),
        "scheduled_appointment_view": _view(
            appointment_id=7,
            status=AppointmentStatus.SCHEDULED,
            start_at="2099-04-15T09:00:00+08:00",
            end_at="2099-04-15T09:30:00+08:00",
        ),
    }

    local_state = await patch_node.node_patch_resolver(state, sessionmaker=None)

    assert captured["sync_plan"] == [
        ("held_appointment_view", 11, True),
        ("scheduled_appointment_view", 7, False),
    ]
    assert local_state["appointment_draft"]["name"] == "Janet Doe"
    assert local_state["appointment_draft"]["notes"] == ["Existing note", "Call ahead"]
    assert local_state["held_appointment_view"]["name"] == "Janet Doe"
    assert local_state["scheduled_appointment_view"]["name"] == "Janet Doe"
    assert local_state["current_appointment_id"] == 11
