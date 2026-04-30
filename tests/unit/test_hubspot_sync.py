from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import voice_agent.core.services.appointments as appointment_services
import voice_agent.core.services.hubspot_sync as hubspot_sync
from voice_agent.core.services.hubspot_sync import HubSpotSyncIds
from voice_agent.core.types import AppointmentStatus, HubSpotObjectType


UTC = timezone.utc


def _appointment_record(
    *,
    appointment_id: int,
    status: AppointmentStatus,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    name: str = "Jane Doe",
    phone: str = "+1 (555) 123-4567",
    reason_for_visit: str = "Annual checkup",
    notes: list[str] | None = None,
    hubspot_contact_id: str | None = None,
    hubspot_deal_id: str | None = None,
    hubspot_ticket_id: str | None = None,
    hubspot_note_id: str | None = None,
) -> SimpleNamespace:
    now = datetime(2099, 4, 20, 9, 0, tzinfo=UTC)
    return SimpleNamespace(
        id=appointment_id,
        name=name,
        phone=phone,
        reason_for_visit=reason_for_visit,
        notes=list(notes or ["Bring insurance card", "Needs wheelchair access"]),
        start_at=start_at,
        end_at=end_at,
        status=status,
        created_at=now,
        updated_at=now,
        hubspot_contact_id=hubspot_contact_id,
        hubspot_deal_id=hubspot_deal_id,
        hubspot_ticket_id=hubspot_ticket_id,
        hubspot_note_id=hubspot_note_id,
        hubspot_last_synced_at=None,
        hubspot_sync_error=None,
    )


class _FakeAppointmentRepo:
    def __init__(self, *appointments: SimpleNamespace) -> None:
        self.rows = {appointment.id: appointment for appointment in appointments}
        self.deleted_ids: list[int] = []

    async def get(self, appointment_id: int) -> SimpleNamespace | None:
        return self.rows.get(appointment_id)

    async def delete(self, appointment_id: int) -> bool:
        self.deleted_ids.append(appointment_id)
        self.rows.pop(appointment_id, None)
        return True

    async def update_fields(self, appointment_id: int, **fields) -> SimpleNamespace | None:
        appointment = self.rows.get(appointment_id)
        if appointment is None:
            return None
        for key, value in fields.items():
            setattr(appointment, key, value)
        appointment.updated_at = datetime(2099, 4, 20, 9, 5, tzinfo=UTC)
        return appointment

    async def set_status(self, appointment_id: int, status: AppointmentStatus) -> SimpleNamespace | None:
        return await self.update_fields(appointment_id, status=status)


class _FakeCrmSyncRepo:
    def __init__(self) -> None:
        self.enqueued: list[dict] = []

    async def enqueue(self, **kwargs):
        self.enqueued.append(kwargs)
        return SimpleNamespace(id=len(self.enqueued), **kwargs)


class _FakeUnitOfWork:
    def __init__(self, appointment_repo: _FakeAppointmentRepo, crm_repo: _FakeCrmSyncRepo) -> None:
        self.appointments = appointment_repo
        self.crm_sync_events = crm_repo

    async def __aenter__(self) -> "_FakeUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _DummySessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _sessionmaker():
    return _DummySessionContext()


class _FakeHubSpotClient:
    def __init__(
        self,
        *,
        search_contact_result: str | None = None,
        created_contact_id: str = "contact-1",
        created_deal_id: str = "deal-1",
        created_ticket_id: str = "ticket-1",
        created_note_id: str = "note-1",
    ) -> None:
        self.search_contact_result = search_contact_result
        self.created_contact_id = created_contact_id
        self.created_deal_id = created_deal_id
        self.created_ticket_id = created_ticket_id
        self.created_note_id = created_note_id
        self.calls: list[tuple] = []

    async def open(self):
        self.calls.append(("open",))
        return self

    async def aclose(self) -> None:
        self.calls.append(("aclose",))

    async def search_contact_by_phone(self, *, phone: str) -> str | None:
        self.calls.append(("search_contact_by_phone", phone))
        return self.search_contact_result

    async def create_contact(self, *, name: str | None, phone: str) -> str:
        self.calls.append(("create_contact", name, phone))
        return self.created_contact_id

    async def update_contact(self, *, contact_id: str, name: str | None, phone: str) -> None:
        self.calls.append(("update_contact", contact_id, name, phone))

    async def create_deal(self, *, appointment, stage: str) -> str:
        self.calls.append(("create_deal", appointment.id, stage))
        return self.created_deal_id

    async def update_deal(self, *, deal_id: str, appointment, stage: str) -> None:
        self.calls.append(("update_deal", deal_id, appointment.id, stage))

    async def create_ticket(self, *, appointment, stage: str) -> str:
        self.calls.append(("create_ticket", appointment.id, stage))
        return self.created_ticket_id

    async def update_ticket(self, *, ticket_id: str, appointment, stage: str) -> None:
        self.calls.append(("update_ticket", ticket_id, appointment.id, stage))

    async def create_note(self, *, appointment) -> str:
        self.calls.append(("create_note", appointment.id))
        return self.created_note_id

    async def update_note(self, *, note_id: str, appointment) -> None:
        self.calls.append(("update_note", note_id, appointment.id))

    async def associate(self, *, from_type: str, from_id: str, to_type: str, to_id: str) -> None:
        self.calls.append(("associate", from_type, from_id, to_type, to_id))


@pytest.mark.asyncio
async def test_schedule_held_appointment_cancels_old_and_enqueues_two_crm_events(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(hubspot_sync.settings, "HUBSPOT_CRM_OBJECT_TYPE", HubSpotObjectType.DEAL)

    start_at = datetime(2099, 4, 21, 10, 0, tzinfo=UTC)
    held_appointment = _appointment_record(
        appointment_id=11,
        status=AppointmentStatus.HELD,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
    )
    old_scheduled = _appointment_record(
        appointment_id=7,
        status=AppointmentStatus.SCHEDULED,
        start_at=start_at - timedelta(days=1),
        end_at=start_at - timedelta(days=1) + timedelta(minutes=30),
        hubspot_contact_id="contact-old",
        hubspot_deal_id="deal-old",
        hubspot_note_id="note-old",
    )
    appointment_repo = _FakeAppointmentRepo(held_appointment, old_scheduled)
    crm_repo = _FakeCrmSyncRepo()
    uow = _FakeUnitOfWork(appointment_repo, crm_repo)

    result = await appointment_services.schedule_held_appointment(
        uow,
        held_appointment_id=held_appointment.id,
        scheduled_appointment_id=old_scheduled.id,
    )

    assert result.scheduled_view["id"] == held_appointment.id
    assert result.scheduled_view["status"] == AppointmentStatus.SCHEDULED
    assert result.cancelled_scheduled_view is not None
    assert result.cancelled_scheduled_view["id"] == old_scheduled.id
    assert result.cancelled_scheduled_view["status"] == AppointmentStatus.CANCELLED
    assert old_scheduled.status == AppointmentStatus.CANCELLED
    assert appointment_repo.deleted_ids == []

    assert [event["event_type"] for event in crm_repo.enqueued] == [
        hubspot_sync.HUBSPOT_EVENT_APPOINTMENT_CANCELLED,
        hubspot_sync.HUBSPOT_EVENT_APPOINTMENT_SCHEDULED,
    ]
    assert crm_repo.enqueued[0]["appointment_id"] == old_scheduled.id
    assert crm_repo.enqueued[1]["appointment_id"] == held_appointment.id

    expected_cancellation_attempt = datetime.now(tz=UTC)
    expected_schedule_attempt = expected_cancellation_attempt + timedelta(
        seconds=hubspot_sync.settings.HUBSPOT_SYNC_INITIAL_DELAY_SECONDS
    )
    assert abs((crm_repo.enqueued[0]["next_attempt_at"] - expected_cancellation_attempt).total_seconds()) <= 2
    assert abs((crm_repo.enqueued[1]["next_attempt_at"] - expected_schedule_attempt).total_seconds()) <= 2


@pytest.mark.asyncio
async def test_update_appointment_notes_enqueues_notes_updated_event(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(hubspot_sync.settings, "HUBSPOT_CRM_OBJECT_TYPE", HubSpotObjectType.DEAL)

    appointment = _appointment_record(
        appointment_id=11,
        status=AppointmentStatus.SCHEDULED,
        start_at=datetime(2099, 4, 21, 10, 0, tzinfo=UTC),
        end_at=datetime(2099, 4, 21, 10, 30, tzinfo=UTC),
        hubspot_contact_id="contact-1",
        hubspot_deal_id="deal-1",
        hubspot_note_id="note-1",
    )
    appointment_repo = _FakeAppointmentRepo(appointment)
    crm_repo = _FakeCrmSyncRepo()
    uow = _FakeUnitOfWork(appointment_repo, crm_repo)

    result = await appointment_services.update_appointment_notes(
        uow,
        appointment_id=appointment.id,
        notes=["Patient requested a translator"],
    )

    assert result["notes"] == ["Patient requested a translator"]
    assert len(crm_repo.enqueued) == 1
    queued_event = crm_repo.enqueued[0]
    assert queued_event["appointment_id"] == appointment.id
    assert queued_event["event_type"] == hubspot_sync.HUBSPOT_EVENT_APPOINTMENT_NOTES_UPDATED
    assert abs((queued_event["next_attempt_at"] - datetime.now(tz=UTC)).total_seconds()) <= 2


@pytest.mark.asyncio
async def test_initial_booking_sync_creates_crm_records(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(hubspot_sync.settings, "HUBSPOT_DEAL_STAGE", "appointmentscheduled")

    appointment = _appointment_record(
        appointment_id=11,
        status=AppointmentStatus.SCHEDULED,
        start_at=datetime(2099, 4, 21, 10, 0, tzinfo=UTC),
        end_at=datetime(2099, 4, 21, 10, 30, tzinfo=UTC),
    )
    fake_client = _FakeHubSpotClient()

    sync_ids = await hubspot_sync.sync_appointment_to_hubspot(
        appointment=appointment,
        client=fake_client,
        object_type=HubSpotObjectType.DEAL,
    )

    assert sync_ids == HubSpotSyncIds(
        contact_id="contact-1",
        deal_id="deal-1",
        ticket_id=None,
        note_id="note-1",
    )
    assert fake_client.calls == [
        ("open",),
        ("search_contact_by_phone", "+1 (555) 123-4567"),
        ("create_contact", "Jane Doe", "+1 (555) 123-4567"),
        ("create_deal", 11, "appointmentscheduled"),
        ("create_note", 11),
        ("associate", "contact", "contact-1", "deal", "deal-1"),
        ("associate", "contact", "contact-1", "note", "note-1"),
        ("associate", "deal", "deal-1", "note", "note-1"),
    ]


@pytest.mark.asyncio
async def test_notes_added_after_booking_update_existing_hubspot_note(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(hubspot_sync.settings, "HUBSPOT_DEAL_STAGE", "appointmentscheduled")

    appointment = _appointment_record(
        appointment_id=11,
        status=AppointmentStatus.SCHEDULED,
        start_at=datetime(2099, 4, 21, 10, 0, tzinfo=UTC),
        end_at=datetime(2099, 4, 21, 10, 30, tzinfo=UTC),
        hubspot_contact_id="contact-1",
        hubspot_deal_id="deal-1",
        hubspot_note_id="note-1",
        notes=["Add interpreter"],
    )
    fake_client = _FakeHubSpotClient()

    sync_ids = await hubspot_sync.sync_appointment_event_to_hubspot(
        appointment=appointment,
        event_type=hubspot_sync.HUBSPOT_EVENT_APPOINTMENT_NOTES_UPDATED,
        client=fake_client,
        object_type=HubSpotObjectType.DEAL,
    )

    assert sync_ids == HubSpotSyncIds(
        contact_id="contact-1",
        deal_id="deal-1",
        ticket_id=None,
        note_id="note-1",
    )
    assert fake_client.calls == [
        ("open",),
        ("update_contact", "contact-1", "Jane Doe", "+1 (555) 123-4567"),
        ("update_deal", "deal-1", 11, "appointmentscheduled"),
        ("update_note", "note-1", 11),
        ("associate", "contact", "contact-1", "deal", "deal-1"),
        ("associate", "contact", "contact-1", "note", "note-1"),
        ("associate", "deal", "deal-1", "note", "note-1"),
    ]


@pytest.mark.asyncio
async def test_notes_updated_creates_note_when_one_is_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(hubspot_sync.settings, "HUBSPOT_DEAL_STAGE", "appointmentscheduled")

    appointment = _appointment_record(
        appointment_id=12,
        status=AppointmentStatus.SCHEDULED,
        start_at=datetime(2099, 4, 21, 11, 0, tzinfo=UTC),
        end_at=datetime(2099, 4, 21, 11, 30, tzinfo=UTC),
        hubspot_contact_id="contact-1",
        hubspot_deal_id="deal-1",
        hubspot_note_id=None,
        notes=["Needs callback"],
    )
    fake_client = _FakeHubSpotClient(created_note_id="note-new")

    sync_ids = await hubspot_sync.sync_appointment_event_to_hubspot(
        appointment=appointment,
        event_type=hubspot_sync.HUBSPOT_EVENT_APPOINTMENT_NOTES_UPDATED,
        client=fake_client,
        object_type=HubSpotObjectType.DEAL,
    )

    assert sync_ids == HubSpotSyncIds(
        contact_id="contact-1",
        deal_id="deal-1",
        ticket_id=None,
        note_id="note-new",
    )
    assert fake_client.calls == [
        ("open",),
        ("update_contact", "contact-1", "Jane Doe", "+1 (555) 123-4567"),
        ("update_deal", "deal-1", 12, "appointmentscheduled"),
        ("create_note", 12),
        ("associate", "contact", "contact-1", "deal", "deal-1"),
        ("associate", "contact", "contact-1", "note", "note-new"),
        ("associate", "deal", "deal-1", "note", "note-new"),
    ]


@pytest.mark.asyncio
async def test_old_appointment_cancellation_updates_existing_hubspot_record(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(hubspot_sync.settings, "HUBSPOT_DEAL_CANCELLED_STAGE", "closedlost")

    appointment = _appointment_record(
        appointment_id=7,
        status=AppointmentStatus.CANCELLED,
        start_at=datetime(2099, 4, 20, 10, 0, tzinfo=UTC),
        end_at=datetime(2099, 4, 20, 10, 30, tzinfo=UTC),
        hubspot_contact_id="contact-1",
        hubspot_deal_id="deal-old",
        hubspot_note_id="note-old",
    )
    fake_client = _FakeHubSpotClient()

    sync_ids = await hubspot_sync.sync_appointment_event_to_hubspot(
        appointment=appointment,
        event_type=hubspot_sync.HUBSPOT_EVENT_APPOINTMENT_CANCELLED,
        client=fake_client,
        object_type=HubSpotObjectType.DEAL,
    )

    assert sync_ids == HubSpotSyncIds(
        contact_id="contact-1",
        deal_id="deal-old",
        ticket_id=None,
        note_id="note-old",
    )
    assert fake_client.calls == [
        ("open",),
        ("update_contact", "contact-1", "Jane Doe", "+1 (555) 123-4567"),
        ("update_deal", "deal-old", 7, "closedlost"),
        ("update_note", "note-old", 7),
        ("associate", "contact", "contact-1", "deal", "deal-old"),
        ("associate", "contact", "contact-1", "note", "note-old"),
        ("associate", "deal", "deal-old", "note", "note-old"),
    ]


@pytest.mark.asyncio
async def test_new_appointment_creates_separate_crm_record_for_existing_contact(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(hubspot_sync.settings, "HUBSPOT_DEAL_STAGE", "appointmentscheduled")

    appointment = _appointment_record(
        appointment_id=22,
        status=AppointmentStatus.SCHEDULED,
        start_at=datetime(2099, 4, 23, 15, 0, tzinfo=UTC),
        end_at=datetime(2099, 4, 23, 15, 30, tzinfo=UTC),
    )
    fake_client = _FakeHubSpotClient(search_contact_result="contact-existing", created_deal_id="deal-new")

    sync_ids = await hubspot_sync.sync_appointment_to_hubspot(
        appointment=appointment,
        client=fake_client,
        object_type=HubSpotObjectType.DEAL,
    )

    assert sync_ids == HubSpotSyncIds(
        contact_id="contact-existing",
        deal_id="deal-new",
        ticket_id=None,
        note_id="note-1",
    )
    assert fake_client.calls == [
        ("open",),
        ("search_contact_by_phone", "+1 (555) 123-4567"),
        ("update_contact", "contact-existing", "Jane Doe", "+1 (555) 123-4567"),
        ("create_deal", 22, "appointmentscheduled"),
        ("create_note", 22),
        ("associate", "contact", "contact-existing", "deal", "deal-new"),
        ("associate", "contact", "contact-existing", "note", "note-1"),
        ("associate", "deal", "deal-new", "note", "note-1"),
    ]


@pytest.mark.asyncio
async def test_retry_of_scheduled_event_reuses_existing_hubspot_ids_without_duplicate_creates(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(hubspot_sync.settings, "HUBSPOT_DEAL_STAGE", "appointmentscheduled")

    appointment = _appointment_record(
        appointment_id=33,
        status=AppointmentStatus.SCHEDULED,
        start_at=datetime(2099, 4, 24, 11, 0, tzinfo=UTC),
        end_at=datetime(2099, 4, 24, 11, 30, tzinfo=UTC),
        hubspot_contact_id="contact-1",
        hubspot_deal_id="deal-1",
        hubspot_note_id="note-1",
    )
    fake_client = _FakeHubSpotClient()

    sync_ids = await hubspot_sync.sync_appointment_to_hubspot(
        appointment=appointment,
        client=fake_client,
        object_type=HubSpotObjectType.DEAL,
    )

    assert sync_ids == HubSpotSyncIds(
        contact_id="contact-1",
        deal_id="deal-1",
        ticket_id=None,
        note_id="note-1",
    )
    assert fake_client.calls == [
        ("open",),
        ("update_contact", "contact-1", "Jane Doe", "+1 (555) 123-4567"),
        ("update_deal", "deal-1", 33, "appointmentscheduled"),
        ("update_note", "note-1", 33),
        ("associate", "contact", "contact-1", "deal", "deal-1"),
        ("associate", "contact", "contact-1", "note", "note-1"),
        ("associate", "deal", "deal-1", "note", "note-1"),
    ]


@pytest.mark.asyncio
async def test_process_pending_hubspot_sync_events_claims_and_dispatches(
    monkeypatch: pytest.MonkeyPatch,
):
    claimed: dict = {}
    processed_ids: list[int] = []
    fake_events = [SimpleNamespace(id=1), SimpleNamespace(id=2)]

    class _FakeClaimRepo:
        async def claim_due(self, **kwargs):
            claimed.update(kwargs)
            return fake_events

    class _FakeClaimUow:
        def __init__(self, session) -> None:
            self.crm_sync_events = _FakeClaimRepo()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_process(*, sessionmaker, event_id):
        processed_ids.append(event_id)
        return True

    monkeypatch.setattr(hubspot_sync.settings, "HUBSPOT_ACCESS_TOKEN", "test-token")
    monkeypatch.setattr(hubspot_sync, "SqlAlchemyUnitOfWork", _FakeClaimUow)
    monkeypatch.setattr(hubspot_sync, "process_hubspot_sync_event", fake_process)

    processed_count = await hubspot_sync.process_pending_hubspot_sync_events(
        sessionmaker=_sessionmaker,
        limit=2,
    )

    assert processed_count == 2
    assert claimed["limit"] == 2
    assert claimed["provider"] == hubspot_sync.HUBSPOT_PROVIDER
    assert processed_ids == [1, 2]
