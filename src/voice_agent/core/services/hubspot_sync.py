from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from voice_agent.common import utcnow
from voice_agent.core.db.models import Appointment, CrmSyncEvent
from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.settings import settings
from voice_agent.core.types import AppointmentStatus, HubSpotObjectType

logger = logging.getLogger(__name__)

HUBSPOT_PROVIDER = "hubspot"
HUBSPOT_EVENT_APPOINTMENT_SCHEDULED = "appointment_scheduled"
HUBSPOT_EVENT_APPOINTMENT_CANCELLED = "appointment_cancelled"
HUBSPOT_EVENT_APPOINTMENT_NOTES_UPDATED = "appointment_notes_updated"

_HUBSPOT_ACTIVE_EVENT_TYPES = {
    HUBSPOT_EVENT_APPOINTMENT_SCHEDULED,
    HUBSPOT_EVENT_APPOINTMENT_NOTES_UPDATED,
}
_HUBSPOT_SUPPORTED_EVENT_TYPES = {
    HUBSPOT_EVENT_APPOINTMENT_SCHEDULED,
    HUBSPOT_EVENT_APPOINTMENT_CANCELLED,
    HUBSPOT_EVENT_APPOINTMENT_NOTES_UPDATED,
}


@dataclass(frozen=True, slots=True)
class HubSpotSyncIds:
    contact_id: str | None = None
    deal_id: str | None = None
    ticket_id: str | None = None
    note_id: str | None = None

    def merged(self, other: "HubSpotSyncIds | None") -> "HubSpotSyncIds":
        if other is None:
            return self
        return HubSpotSyncIds(
            contact_id=other.contact_id or self.contact_id,
            deal_id=other.deal_id or self.deal_id,
            ticket_id=other.ticket_id or self.ticket_id,
            note_id=other.note_id or self.note_id,
        )

    def primary_object_id(self, object_type: HubSpotObjectType) -> str | None:
        if object_type == HubSpotObjectType.TICKET:
            return self.ticket_id
        return self.deal_id

    def to_appointment_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if self.contact_id:
            fields["hubspot_contact_id"] = self.contact_id
        if self.deal_id:
            fields["hubspot_deal_id"] = self.deal_id
        if self.ticket_id:
            fields["hubspot_ticket_id"] = self.ticket_id
        if self.note_id:
            fields["hubspot_note_id"] = self.note_id
        return fields

    def to_log_dict(self) -> dict[str, str]:
        return {
            key: value
            for key, value in {
                "contact_id": self.contact_id,
                "deal_id": self.deal_id,
                "ticket_id": self.ticket_id,
                "note_id": self.note_id,
            }.items()
            if value
        }


class HubSpotSyncError(Exception):
    def __init__(
        self,
        message: str,
        *,
        ids: HubSpotSyncIds | None = None,
        retryable: bool = True,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.ids = ids or HubSpotSyncIds()
        self.retryable = retryable
        self.status_code = status_code


class HubSpotConfigurationError(HubSpotSyncError):
    def __init__(self, message: str, *, ids: HubSpotSyncIds | None = None) -> None:
        super().__init__(message, ids=ids, retryable=True)


class HubSpotClient:
    def __init__(
        self,
        access_token: str,
        *,
        base_url: str = "https://api.hubapi.com",
        timeout_seconds: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._access_token = access_token
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client = client
        self._owns_client = client is None

    async def open(self) -> "HubSpotClient":
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Content-Type": "application/json",
                },
            )
        return self

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
        self._client = None

    async def __aenter__(self) -> "HubSpotClient":
        return await self.open()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = self._client
        if client is None:
            raise RuntimeError("HubSpotClient.open() must be called before requests")

        try:
            response = await client.request(method, path, json=json)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            message = _extract_error_message(exc.response)
            raise HubSpotSyncError(
                f"HubSpot API {method} {path} failed: {message}",
                retryable=_is_retryable_status(exc.response.status_code),
                status_code=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise HubSpotSyncError(
                f"HubSpot API {method} {path} failed: {exc}",
                retryable=True,
            ) from exc

        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    async def search_contact_by_phone(self, *, phone: str) -> str | None:
        normalized_phone = _normalize_phone(phone)
        queries = [str(phone or "").strip()]
        if normalized_phone and normalized_phone not in queries:
            queries.append(normalized_phone)

        seen_ids: set[str] = set()
        for query in [value for value in queries if value]:
            payload = await self._request_json(
                "POST",
                "/crm/v3/objects/contacts/search",
                json={
                    "query": query,
                    "limit": 10,
                    "properties": ["phone", "mobilephone", "firstname", "lastname"],
                },
            )
            for result in payload.get("results") or []:
                result_id = str(result.get("id") or "").strip()
                if not result_id or result_id in seen_ids:
                    continue
                seen_ids.add(result_id)
                properties = result.get("properties") or {}
                if _phones_match(phone, properties.get("phone")) or _phones_match(phone, properties.get("mobilephone")):
                    return result_id
        return None

    async def create_contact(self, *, name: str | None, phone: str) -> str:
        payload = await self._request_json(
            "POST",
            "/crm/v3/objects/contacts",
            json={"properties": _build_contact_properties(name=name, phone=phone)},
        )
        return _required_id(payload, object_name="contact")

    async def update_contact(self, *, contact_id: str, name: str | None, phone: str) -> None:
        await self._request_json(
            "PATCH",
            f"/crm/v3/objects/contacts/{contact_id}",
            json={"properties": _build_contact_properties(name=name, phone=phone)},
        )

    async def create_deal(self, *, appointment: Appointment, stage: str) -> str:
        payload = await self._request_json(
            "POST",
            "/crm/v3/objects/deals",
            json={"properties": _build_deal_properties(appointment=appointment, stage=stage)},
        )
        return _required_id(payload, object_name="deal")

    async def update_deal(self, *, deal_id: str, appointment: Appointment, stage: str) -> None:
        await self._request_json(
            "PATCH",
            f"/crm/v3/objects/deals/{deal_id}",
            json={"properties": _build_deal_properties(appointment=appointment, stage=stage)},
        )

    async def create_ticket(self, *, appointment: Appointment, stage: str) -> str:
        payload = await self._request_json(
            "POST",
            "/crm/v3/objects/tickets",
            json={"properties": _build_ticket_properties(appointment=appointment, stage=stage)},
        )
        return _required_id(payload, object_name="ticket")

    async def update_ticket(self, *, ticket_id: str, appointment: Appointment, stage: str) -> None:
        await self._request_json(
            "PATCH",
            f"/crm/v3/objects/tickets/{ticket_id}",
            json={"properties": _build_ticket_properties(appointment=appointment, stage=stage)},
        )

    async def create_note(self, *, appointment: Appointment) -> str:
        payload = await self._request_json(
            "POST",
            "/crm/v3/objects/notes",
            json={"properties": _build_note_properties(appointment=appointment)},
        )
        return _required_id(payload, object_name="note")

    async def update_note(self, *, note_id: str, appointment: Appointment) -> None:
        await self._request_json(
            "PATCH",
            f"/crm/v3/objects/notes/{note_id}",
            json={"properties": _build_note_properties(appointment=appointment)},
        )

    async def associate(self, *, from_type: str, from_id: str, to_type: str, to_id: str) -> None:
        try:
            await self._request_json(
                "PUT",
                f"/crm/v4/objects/{from_type}/{from_id}/associations/default/{to_type}/{to_id}",
            )
        except HubSpotSyncError as exc:
            if exc.status_code == 409:
                return
            raise


def _coerce_object_type(value: HubSpotObjectType | str | None) -> HubSpotObjectType:
    if value is None:
        return settings.HUBSPOT_CRM_OBJECT_TYPE
    if isinstance(value, HubSpotObjectType):
        return value
    try:
        return HubSpotObjectType(value)
    except ValueError as exc:
        raise HubSpotConfigurationError(f"Unsupported HubSpot CRM object type: {value}") from exc


def _normalize_phone(phone: str | None) -> str:
    raw = str(phone or "").strip()
    if not raw:
        return ""
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits or raw


def _phones_match(left: str | None, right: str | None) -> bool:
    normalized_left = _normalize_phone(left)
    normalized_right = _normalize_phone(right)
    return bool(normalized_left) and normalized_left == normalized_right


def _split_name(name: str | None, *, fallback: str) -> tuple[str, str | None]:
    parts = [part for part in str(name or "").strip().split() if part]
    if not parts:
        return fallback, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def _appointment_title(appointment: Appointment) -> str:
    person = str(appointment.name or "").strip() or str(appointment.phone or "").strip() or f"Appointment {appointment.id}"
    return f"Appointment #{appointment.id} - {person}"


def _appointment_time_text(appointment: Appointment) -> str:
    if appointment.start_at is None or appointment.end_at is None:
        return "Pending schedule"
    return f"{appointment.start_at.isoformat()} to {appointment.end_at.isoformat()}"


def _build_note_body(appointment: Appointment) -> str:
    reason = str(appointment.reason_for_visit or "").strip() or "Not provided"
    lines = [
        f"Appointment ID: {appointment.id}",
        f"Status: {appointment.status.value}",
        f"Patient: {str(appointment.name or '').strip() or 'Not provided'}",
        f"Phone: {str(appointment.phone or '').strip() or 'Not provided'}",
        f"Appointment window: {_appointment_time_text(appointment)}",
        f"Reason for visit: {reason}",
    ]
    notes = [str(note).strip() for note in list(appointment.notes or []) if str(note).strip()]
    if notes:
        lines.append("Appointment notes:")
        lines.extend(f"- {note}" for note in notes)
    else:
        lines.append("Appointment notes: None")
    return "\n".join(lines)


def _build_contact_properties(*, name: str | None, phone: str) -> dict[str, str]:
    fallback = _normalize_phone(phone) or "Unknown"
    first_name, last_name = _split_name(name, fallback=fallback)
    properties = {
        "firstname": first_name,
        "phone": phone,
    }
    if last_name:
        properties["lastname"] = last_name
    return properties


def _build_deal_properties(*, appointment: Appointment, stage: str) -> dict[str, str]:
    properties = {
        "dealname": _appointment_title(appointment),
        "dealstage": stage,
        "description": _build_note_body(appointment),
    }
    if settings.HUBSPOT_DEAL_PIPELINE:
        properties["pipeline"] = settings.HUBSPOT_DEAL_PIPELINE
    return properties


def _build_ticket_properties(*, appointment: Appointment, stage: str) -> dict[str, str]:
    properties = {
        "subject": _appointment_title(appointment),
        "content": _build_note_body(appointment),
        "hs_pipeline_stage": stage,
    }
    if settings.HUBSPOT_TICKET_PIPELINE:
        properties["hs_pipeline"] = settings.HUBSPOT_TICKET_PIPELINE
    return properties


def _build_note_properties(*, appointment: Appointment) -> dict[str, str]:
    timestamp = appointment.updated_at or appointment.created_at or utcnow()
    return {
        "hs_timestamp": timestamp.isoformat(),
        "hs_note_body": _build_note_body(appointment),
    }


def _extract_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or f"HTTP {response.status_code}"

    if isinstance(payload, dict):
        for key in ("message", "detail", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return response.text.strip() or f"HTTP {response.status_code}"


def _is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


def _retry_error_message(message: str) -> str:
    return message[:2000]


def _required_id(payload: dict[str, Any], *, object_name: str) -> str:
    object_id = str(payload.get("id") or "").strip()
    if not object_id:
        raise HubSpotSyncError(f"HubSpot did not return an id for the {object_name}")
    return object_id


def _retry_at(*, attempt_count: int, now: datetime | None = None) -> datetime:
    current_time = now or utcnow()
    exponent = max(int(attempt_count) - 1, 0)
    delay_seconds = settings.HUBSPOT_SYNC_RETRY_BASE_SECONDS * (2 ** exponent)
    bounded_delay = min(delay_seconds, settings.HUBSPOT_SYNC_RETRY_MAX_SECONDS)
    return current_time + timedelta(seconds=bounded_delay)


def _scheduled_stage(object_type: HubSpotObjectType) -> str:
    if object_type == HubSpotObjectType.TICKET:
        if not settings.HUBSPOT_TICKET_STAGE:
            raise HubSpotConfigurationError("HUBSPOT_TICKET_STAGE is required when syncing appointments as tickets")
        return settings.HUBSPOT_TICKET_STAGE
    return settings.HUBSPOT_DEAL_STAGE


def _cancelled_stage(object_type: HubSpotObjectType) -> str:
    if object_type == HubSpotObjectType.TICKET:
        if not settings.HUBSPOT_TICKET_CANCELLED_STAGE:
            raise HubSpotConfigurationError(
                "HUBSPOT_TICKET_CANCELLED_STAGE is required when syncing appointment cancellations as tickets"
            )
        return settings.HUBSPOT_TICKET_CANCELLED_STAGE
    return settings.HUBSPOT_DEAL_CANCELLED_STAGE


def _default_delay_for_event(event_type: str) -> int:
    if event_type == HUBSPOT_EVENT_APPOINTMENT_SCHEDULED:
        return settings.HUBSPOT_SYNC_INITIAL_DELAY_SECONDS
    return 0


async def enqueue_hubspot_sync_event(
    uow: SqlAlchemyUnitOfWork,
    *,
    appointment_id: int,
    event_type: str,
    object_type: HubSpotObjectType | str | None = None,
    delay_seconds: int | None = None,
) -> None:
    if event_type not in _HUBSPOT_SUPPORTED_EVENT_TYPES:
        raise ValueError(f"Unsupported HubSpot event type: {event_type}")

    chosen_object_type = _coerce_object_type(object_type)
    effective_delay = _default_delay_for_event(event_type) if delay_seconds is None else max(delay_seconds, 0)
    next_attempt_at = utcnow() + timedelta(seconds=effective_delay)
    event = await uow.crm_sync_events.enqueue(
        appointment_id=appointment_id,
        provider=HUBSPOT_PROVIDER,
        event_type=event_type,
        payload={"object_type": chosen_object_type.value},
        next_attempt_at=next_attempt_at,
    )
    logger.info(
        "Queued HubSpot sync event appointment_id=%s event_type=%s event_id=%s object_type=%s next_attempt_at=%s",
        appointment_id,
        event_type,
        event.id,
        chosen_object_type.value,
        next_attempt_at.isoformat(),

    )


async def enqueue_hubspot_appointment_scheduled_event(
    uow: SqlAlchemyUnitOfWork,
    *,
    appointment_id: int,
    object_type: HubSpotObjectType | str | None = None,
    delay_seconds: int | None = None,
) -> None:
    await enqueue_hubspot_sync_event(
        uow,
        appointment_id=appointment_id,
        event_type=HUBSPOT_EVENT_APPOINTMENT_SCHEDULED,
        object_type=object_type,
        delay_seconds=delay_seconds,
    )


async def enqueue_hubspot_appointment_cancelled_event(
    uow: SqlAlchemyUnitOfWork,
    *,
    appointment_id: int,
    object_type: HubSpotObjectType | str | None = None,
    delay_seconds: int | None = None,
) -> None:
    await enqueue_hubspot_sync_event(
        uow,
        appointment_id=appointment_id,
        event_type=HUBSPOT_EVENT_APPOINTMENT_CANCELLED,
        object_type=object_type,
        delay_seconds=delay_seconds,
    )


async def enqueue_hubspot_appointment_notes_updated_event(
    uow: SqlAlchemyUnitOfWork,
    *,
    appointment_id: int,
    object_type: HubSpotObjectType | str | None = None,
    delay_seconds: int | None = None,
) -> None:
    await enqueue_hubspot_sync_event(
        uow,
        appointment_id=appointment_id,
        event_type=HUBSPOT_EVENT_APPOINTMENT_NOTES_UPDATED,
        object_type=object_type,
        delay_seconds=delay_seconds,
    )


async def _ensure_contact(
    *,
    appointment: Appointment,
    client: HubSpotClient,
    sync_ids: HubSpotSyncIds,
) -> HubSpotSyncIds:
    phone = str(appointment.phone or "").strip()
    if not phone:
        raise HubSpotSyncError(
            f"Appointment {appointment.id} cannot sync to HubSpot without a phone number",
            ids=sync_ids,
            retryable=False,
        )

    contact_id = sync_ids.contact_id
    if contact_id:
        try:
            await client.update_contact(contact_id=contact_id, name=appointment.name, phone=phone)
            return sync_ids
        except HubSpotSyncError as exc:
            if exc.status_code != 404:
                raise

    contact_id = await client.search_contact_by_phone(phone=phone)
    if contact_id:
        await client.update_contact(contact_id=contact_id, name=appointment.name, phone=phone)
    else:
        contact_id = await client.create_contact(name=appointment.name, phone=phone)

    return sync_ids.merged(HubSpotSyncIds(contact_id=contact_id))


async def _upsert_primary_object(
    *,
    appointment: Appointment,
    client: HubSpotClient,
    sync_ids: HubSpotSyncIds,
    object_type: HubSpotObjectType,
    cancelled: bool,
) -> HubSpotSyncIds:
    stage = _cancelled_stage(object_type) if cancelled else _scheduled_stage(object_type)
    object_id = sync_ids.primary_object_id(object_type)

    if object_type == HubSpotObjectType.TICKET:
        if object_id:
            try:
                await client.update_ticket(ticket_id=object_id, appointment=appointment, stage=stage)
                return sync_ids
            except HubSpotSyncError as exc:
                if exc.status_code != 404:
                    raise
        object_id = await client.create_ticket(appointment=appointment, stage=stage)
        return sync_ids.merged(HubSpotSyncIds(ticket_id=object_id))

    if object_id:
        try:
            await client.update_deal(deal_id=object_id, appointment=appointment, stage=stage)
            return sync_ids
        except HubSpotSyncError as exc:
            if exc.status_code != 404:
                raise
    object_id = await client.create_deal(appointment=appointment, stage=stage)
    return sync_ids.merged(HubSpotSyncIds(deal_id=object_id))


async def _upsert_note(
    *,
    appointment: Appointment,
    client: HubSpotClient,
    sync_ids: HubSpotSyncIds,
) -> HubSpotSyncIds:
    note_id = sync_ids.note_id
    if note_id:
        try:
            await client.update_note(note_id=note_id, appointment=appointment)
            return sync_ids
        except HubSpotSyncError as exc:
            if exc.status_code != 404:
                raise

    note_id = await client.create_note(appointment=appointment)
    return sync_ids.merged(HubSpotSyncIds(note_id=note_id))


async def _ensure_associations(
    *,
    client: HubSpotClient,
    sync_ids: HubSpotSyncIds,
    object_type: HubSpotObjectType,
) -> None:
    contact_id = sync_ids.contact_id
    object_id = sync_ids.primary_object_id(object_type)
    note_id = sync_ids.note_id
    if not contact_id or not object_id or not note_id:
        return

    await client.associate(
        from_type="contact",
        from_id=contact_id,
        to_type=object_type.value,
        to_id=object_id,
    )
    await client.associate(
        from_type="contact",
        from_id=contact_id,
        to_type="note",
        to_id=note_id,
    )
    await client.associate(
        from_type=object_type.value,
        from_id=object_id,
        to_type="note",
        to_id=note_id,
    )


async def _sync_active_appointment(
    *,
    appointment: Appointment,
    client: HubSpotClient | None = None,
    object_type: HubSpotObjectType | str | None = None,
) -> HubSpotSyncIds:
    existing_ids = HubSpotSyncIds(
        contact_id=appointment.hubspot_contact_id,
        deal_id=appointment.hubspot_deal_id,
        ticket_id=appointment.hubspot_ticket_id,
        note_id=appointment.hubspot_note_id,
    )

    access_token = settings.HUBSPOT_ACCESS_TOKEN
    if client is None and not access_token:
        raise HubSpotConfigurationError("HUBSPOT_ACCESS_TOKEN is not configured", ids=existing_ids)

    chosen_object_type = _coerce_object_type(object_type)
    partial_ids = existing_ids
    managed_client = client or HubSpotClient(access_token=access_token or "")

    try:
        await managed_client.open()
        partial_ids = await _ensure_contact(appointment=appointment, client=managed_client, sync_ids=partial_ids)
        partial_ids = await _upsert_primary_object(
            appointment=appointment,
            client=managed_client,
            sync_ids=partial_ids,
            object_type=chosen_object_type,
            cancelled=False,
        )
        partial_ids = await _upsert_note(appointment=appointment, client=managed_client, sync_ids=partial_ids)
        await _ensure_associations(client=managed_client, sync_ids=partial_ids, object_type=chosen_object_type)
        return partial_ids
    except HubSpotSyncError as exc:
        raise HubSpotSyncError(
            str(exc),
            ids=partial_ids.merged(exc.ids),
            retryable=exc.retryable,
            status_code=exc.status_code,
        ) from exc
    except Exception as exc:
        raise HubSpotSyncError(
            f"Unexpected HubSpot sync error: {exc}",
            ids=partial_ids,
            retryable=True,
        ) from exc
    finally:
        if client is None:
            await managed_client.aclose()


async def sync_appointment_to_hubspot(
    *,
    appointment: Appointment,
    client: HubSpotClient | None = None,
    object_type: HubSpotObjectType | str | None = None,
) -> HubSpotSyncIds:
    return await _sync_active_appointment(
        appointment=appointment,
        client=client,
        object_type=object_type,
    )


async def sync_cancelled_appointment_to_hubspot(
    *,
    appointment: Appointment,
    client: HubSpotClient | None = None,
    object_type: HubSpotObjectType | str | None = None,
) -> HubSpotSyncIds:
    existing_ids = HubSpotSyncIds(
        contact_id=appointment.hubspot_contact_id,
        deal_id=appointment.hubspot_deal_id,
        ticket_id=appointment.hubspot_ticket_id,
        note_id=appointment.hubspot_note_id,
    )

    access_token = settings.HUBSPOT_ACCESS_TOKEN
    if client is None and not access_token:
        raise HubSpotConfigurationError("HUBSPOT_ACCESS_TOKEN is not configured", ids=existing_ids)

    chosen_object_type = _coerce_object_type(object_type)
    partial_ids = existing_ids
    managed_client = client or HubSpotClient(access_token=access_token or "")

    try:
        await managed_client.open()
        phone = str(appointment.phone or "").strip()
        if phone or partial_ids.contact_id:
            partial_ids = await _ensure_contact(appointment=appointment, client=managed_client, sync_ids=partial_ids)
        partial_ids = await _upsert_primary_object(
            appointment=appointment,
            client=managed_client,
            sync_ids=partial_ids,
            object_type=chosen_object_type,
            cancelled=True,
        )
        partial_ids = await _upsert_note(appointment=appointment, client=managed_client, sync_ids=partial_ids)
        await _ensure_associations(client=managed_client, sync_ids=partial_ids, object_type=chosen_object_type)
        return partial_ids
    except HubSpotSyncError as exc:
        raise HubSpotSyncError(
            str(exc),
            ids=partial_ids.merged(exc.ids),
            retryable=exc.retryable,
            status_code=exc.status_code,
        ) from exc
    except Exception as exc:
        raise HubSpotSyncError(
            f"Unexpected HubSpot sync error: {exc}",
            ids=partial_ids,
            retryable=True,
        ) from exc
    finally:
        if client is None:
            await managed_client.aclose()


async def sync_appointment_event_to_hubspot(
    *,
    appointment: Appointment,
    event_type: str,
    client: HubSpotClient | None = None,
    object_type: HubSpotObjectType | str | None = None,
) -> HubSpotSyncIds:
    if event_type not in _HUBSPOT_SUPPORTED_EVENT_TYPES:
        raise HubSpotSyncError(f"Unsupported HubSpot sync event type: {event_type}", retryable=False)

    existing_ids = HubSpotSyncIds(
        contact_id=appointment.hubspot_contact_id,
        deal_id=appointment.hubspot_deal_id,
        ticket_id=appointment.hubspot_ticket_id,
        note_id=appointment.hubspot_note_id,
    )

    if appointment.status == AppointmentStatus.CANCELLED:
        return await sync_cancelled_appointment_to_hubspot(
            appointment=appointment,
            client=client,
            object_type=object_type,
        )

    if appointment.status != AppointmentStatus.SCHEDULED:
        logger.warning(
            "Skipping HubSpot sync appointment_id=%s event_type=%s because current_status=%s",
            appointment.id,
            event_type,
            appointment.status,
        )
        return existing_ids

    if event_type in _HUBSPOT_ACTIVE_EVENT_TYPES or event_type == HUBSPOT_EVENT_APPOINTMENT_CANCELLED:
        return await sync_appointment_to_hubspot(
            appointment=appointment,
            client=client,
            object_type=object_type,
        )

    raise HubSpotSyncError(f"Unsupported HubSpot sync event type: {event_type}", retryable=False)


async def _load_event_and_appointment(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    event_id: int,
) -> tuple[CrmSyncEvent | None, Appointment | None]:
    async with sessionmaker() as session:
        uow = SqlAlchemyUnitOfWork(session)
        event = await uow.crm_sync_events.get(event_id)
        if event is None:
            return None, None
        appointment = await uow.appointments.get(event.appointment_id)
        return event, appointment


async def _mark_sync_completed(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    event_id: int,
    appointment_id: int,
    sync_ids: HubSpotSyncIds,
) -> None:
    completed_at = utcnow()
    async with sessionmaker() as session:
        uow = SqlAlchemyUnitOfWork(session)
        async with uow:
            fields = sync_ids.to_appointment_fields()
            fields["hubspot_last_synced_at"] = completed_at
            fields["hubspot_sync_error"] = None
            await uow.appointments.update_fields(appointment_id, **fields)
            await uow.crm_sync_events.mark_completed(event_id, processed_at=completed_at)


async def _mark_sync_failed(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    event_id: int,
    appointment_id: int | None,
    sync_ids: HubSpotSyncIds,
    attempt_count: int,
    message: str,
) -> None:
    async with sessionmaker() as session:
        uow = SqlAlchemyUnitOfWork(session)
        async with uow:
            if appointment_id is not None:
                fields = sync_ids.to_appointment_fields()
                fields["hubspot_sync_error"] = _retry_error_message(message)
                await uow.appointments.update_fields(appointment_id, **fields)
            await uow.crm_sync_events.mark_failed(
                event_id,
                last_error=_retry_error_message(message),
                next_attempt_at=_retry_at(attempt_count=attempt_count),
            )


async def process_hubspot_sync_event(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    event_id: int,
) -> bool:
    event, appointment = await _load_event_and_appointment(sessionmaker, event_id=event_id)
    if event is None:
        logger.warning("HubSpot sync event missing event_id=%s", event_id)
        return False
    if appointment is None:
        message = f"Appointment {event.appointment_id} was not found for HubSpot sync"
        logger.warning(
            "HubSpot sync skipped missing appointment event_id=%s appointment_id=%s event_type=%s",
            event_id,
            event.appointment_id,
            event.event_type,
        )
        await _mark_sync_failed(
            sessionmaker,
            event_id=event_id,
            appointment_id=None,
            sync_ids=HubSpotSyncIds(),
            attempt_count=event.attempt_count,
            message=message,
        )
        return False

    requested_object_type = (event.payload or {}).get("object_type")
    try:
        sync_ids = await sync_appointment_event_to_hubspot(
            appointment=appointment,
            event_type=event.event_type,
            object_type=requested_object_type,
        )
    except HubSpotSyncError as exc:
        logger.warning(
            "HubSpot sync failed appointment_id=%s event_type=%s event_id=%s attempt=%s hubspot_ids=%s error=%s",
            appointment.id,
            event.event_type,
            event_id,
            event.attempt_count,
            exc.ids.to_log_dict(),
            exc,
        )
        await _mark_sync_failed(
            sessionmaker,
            event_id=event_id,
            appointment_id=appointment.id,
            sync_ids=exc.ids,
            attempt_count=event.attempt_count,
            message=str(exc),
        )
        return False

    await _mark_sync_completed(
        sessionmaker,
        event_id=event_id,
        appointment_id=appointment.id,
        sync_ids=sync_ids,
    )
    logger.info(
        "HubSpot sync completed appointment_id=%s event_type=%s event_id=%s attempt=%s hubspot_ids=%s",
        appointment.id,
        event.event_type,
        event_id,
        event.attempt_count,
        sync_ids.to_log_dict(),
    )
    return True


async def process_pending_hubspot_sync_events(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    limit: int | None = None,
) -> int:
    if not settings.HUBSPOT_ACCESS_TOKEN:
        return 0

    now = utcnow()
    stale_before = now - timedelta(seconds=settings.HUBSPOT_SYNC_STALE_LOCK_SECONDS)
    async with sessionmaker() as session:
        uow = SqlAlchemyUnitOfWork(session)
        async with uow:
            events = await uow.crm_sync_events.claim_due(
                now=now,
                limit=limit or settings.HUBSPOT_SYNC_BATCH_SIZE,
                stale_before=stale_before,
                provider=HUBSPOT_PROVIDER,
            )

    processed = 0
    for event in events:
        await process_hubspot_sync_event(sessionmaker=sessionmaker, event_id=event.id)
        processed += 1
    return processed


async def run_hubspot_sync_worker(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    logger.info("HubSpot sync worker started")
    try:
        while True:
            try:
                processed = await process_pending_hubspot_sync_events(sessionmaker=sessionmaker)
                if processed == 0:
                    await asyncio.sleep(settings.HUBSPOT_SYNC_POLL_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("HubSpot sync worker iteration failed")
                await asyncio.sleep(settings.HUBSPOT_SYNC_POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.warning("HubSpot sync worker stopped")
        raise
