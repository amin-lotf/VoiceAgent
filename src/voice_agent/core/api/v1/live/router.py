from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import suppress
from typing import Any

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from starlette.websockets import WebSocket, WebSocketDisconnect

from voice_agent.common import utcnow
from voice_agent.core.api.v1.live.schemas import (
    LiveAppointmentUpdatedOut,
    LiveAssistantCancelledOut,
    LiveAssistantCompletedOut,
    LiveAssistantDeltaOut,
    LiveAssistantStartedOut,
    LiveCallStateOut,
    LiveClientEvent,
    LiveErrorOut,
    LiveInternalEventOut,
    LiveLogOut,
    LiveMessageOut,
    LivePhaseChangedOut,
    LivePingIn,
    LivePongOut,
    LiveSessionReadyOut,
    LiveSnapshotRequestIn,
    LiveStateSnapshotOut,
    LiveUserMessageIn,
    LiveUserMessageOut,
    LiveCancelIn,
)
from voice_agent.core.api.v1.live.state import (
    build_live_turn_metrics,
    serialize_live_call_state,
)
from voice_agent.core.db.session import AsyncSessionLocal
from voice_agent.core.graph.engine import InterviewEngine
from voice_agent.core.graph.node_timing import build_recorded_turn_metrics
from voice_agent.core.services.call_history import CallHistoryRecorder
from voice_agent.core.types import CallEvent, ChunkKind
from voice_agent.logging import get_live_log_broker

router = APIRouter(prefix="/live", tags=["live"])

logger = logging.getLogger(__name__)


def _parse_client_event(payload: dict[str, Any]) -> LiveClientEvent:
    event_type = payload.get("type")
    if event_type == "user.message":
        return LiveUserMessageIn.model_validate(payload)
    if event_type == "assistant.cancel":
        return LiveCancelIn.model_validate(payload)
    if event_type == "ping":
        return LivePingIn.model_validate(payload)
    if event_type == "session.snapshot":
        return LiveSnapshotRequestIn.model_validate(payload)
    raise ValueError(f"Unknown live event type: {event_type}")


async def _ws_send(websocket: WebSocket, obj: BaseModel) -> None:
    await websocket.send_text(obj.model_dump_json())


def _ts() -> str:
    return utcnow().isoformat()


def _log_level_for_ui(value: str) -> str:
    normalized = str(value or "info").strip().lower()
    if normalized == "critical":
        return "error"
    if normalized in {"debug", "info", "warning", "error"}:
        return normalized
    return "info"


def _assistant_message(
    *,
    call_id: str,
    response_id: int,
    content: str,
    created_at: str | None = None,
) -> LiveMessageOut:
    return LiveMessageOut(
        id=f"{call_id}:assistant:{response_id}",
        role="assistant",
        content=content,
        created_at=created_at,
        response_id=response_id,
    )


def _user_message(
    *,
    call_id: str,
    index: int,
    content: str,
    created_at: str | None = None,
) -> LiveMessageOut:
    return LiveMessageOut(
        id=f"{call_id}:user:{index}",
        role="user",
        content=content,
        created_at=created_at,
    )


async def _safe_record(
    action: str,
    call_id: str,
    operation,
) -> None:
    try:
        await operation
    except Exception:
        logger.exception(
            "Call history write failed | action=%s | call_id=%s",
            action,
            call_id,
            extra={"call_id": call_id},
        )
        raise


def _derive_status(state: dict[str, Any] | None) -> str | None:
    payload = state or {}
    if payload.get("scheduled_appointment_view"):
        return "scheduled"
    if payload.get("held_appointment_view"):
        return "held"
    if bool(payload.get("end_call")):
        return "completed"
    phase = str(payload.get("phase") or "").strip()
    assistant_phase = str(payload.get("assistant_phase") or "").strip()
    if phase == "done" or assistant_phase == "done":
        return "completed"
    return None


def _derive_final_status(state: dict[str, Any]) -> str:
    return _derive_status(state) or "completed"


def _derive_disconnect_status(state: dict[str, Any] | None) -> str:
    return _derive_status(state) or "disconnected"


def _extract_scheduled_appointment_snapshot(state: dict[str, Any] | None) -> dict[str, Any] | None:
    payload = state or {}
    scheduled = payload.get("scheduled_appointment_view")
    if not isinstance(scheduled, dict):
        return None
    if scheduled.get("id") is None:
        return None
    return dict(jsonable_encoder(scheduled))


async def _emit_state_events(
    *,
    websocket: WebSocket,
    previous_state: LiveCallStateOut | None,
    current_state: LiveCallStateOut,
) -> None:
    if previous_state is None or (
        previous_state.phase != current_state.phase
        or previous_state.assistant_phase != current_state.assistant_phase
        or previous_state.next_action != current_state.next_action
        or previous_state.current_node != current_state.current_node
    ):
        await _ws_send(
            websocket,
            LivePhaseChangedOut(
                timestamp=_ts(),
                phase=current_state.phase,
                assistant_phase=current_state.assistant_phase,
                next_action=current_state.next_action,
                current_node=current_state.current_node,
            ),
        )

    if previous_state is None or (
        previous_state.appointment_draft.model_dump(mode="json")
        != current_state.appointment_draft.model_dump(mode="json")
        or (
            previous_state.held_appointment.model_dump(mode="json")
            if previous_state.held_appointment
            else None
        )
        != (
            current_state.held_appointment.model_dump(mode="json")
            if current_state.held_appointment
            else None
        )
        or (
            previous_state.scheduled_appointment.model_dump(mode="json")
            if previous_state.scheduled_appointment
            else None
        )
        != (
            current_state.scheduled_appointment.model_dump(mode="json")
            if current_state.scheduled_appointment
            else None
        )
    ):
        await _ws_send(
            websocket,
            LiveAppointmentUpdatedOut(
                timestamp=_ts(),
                appointment_draft=current_state.appointment_draft,
                held_appointment=current_state.held_appointment,
                scheduled_appointment=current_state.scheduled_appointment,
            ),
        )

    await _ws_send(
        websocket,
        LiveStateSnapshotOut(
            timestamp=_ts(),
            state=current_state,
        ),
    )


async def _stream_engine_to_live(
    *,
    websocket: WebSocket,
    engine: InterviewEngine,
    recorder: CallHistoryRecorder,
    call_id: str,
    response_id: int,
    event: CallEvent,
    user_text: str | None,
    meta: dict[str, Any] | None,
    cancel_guard: asyncio.Event,
    trigger: str,
    previous_public_state: LiveCallStateOut | None,
) -> LiveCallStateOut | None:
    await _ws_send(
        websocket,
        LiveAssistantStartedOut(
            timestamp=_ts(),
            response_id=response_id,
            trigger=trigger,
        ),
    )

    full_text_parts: list[str] = []
    final_state: dict[str, Any] = {}
    first_token_delay_s: float | None = None
    turn_started_at = time.perf_counter()
    response_created_at = _ts()

    async for chunk in engine.stream_event(
        call_id=call_id,
        event=event,
        user_text=user_text,
        meta=meta,
    ):
        if cancel_guard.is_set():
            break

        if chunk.kind == ChunkKind.TOKEN:
            token_text = str(chunk.data or "")
            if not token_text:
                continue

            if first_token_delay_s is None:
                first_token_delay_s = time.perf_counter() - turn_started_at

            full_text_parts.append(token_text)
            await _ws_send(
                websocket,
                LiveAssistantDeltaOut(
                    timestamp=_ts(),
                    response_id=response_id,
                    delta=token_text,
                ),
            )
            continue

        if chunk.kind == ChunkKind.DEBUG:
            raw_event = chunk.data
            event_name = "debug"
            payload: dict[str, Any] = {}
            if isinstance(raw_event, tuple) and len(raw_event) == 2:
                event_name = str(raw_event[0])
                maybe_payload = jsonable_encoder(raw_event[1])
                if isinstance(maybe_payload, dict):
                    payload = maybe_payload
                else:
                    payload = {"value": maybe_payload}
            else:
                payload = {"value": jsonable_encoder(raw_event)}

            await _ws_send(
                websocket,
                LiveInternalEventOut(
                    timestamp=_ts(),
                    event_name=event_name,
                    node=str(payload.get("node")) if payload.get("node") else None,
                    payload=payload,
                ),
            )
            continue

        if chunk.kind == ChunkKind.FINAL:
            final_state = chunk.data or {}

    if cancel_guard.is_set():
        return previous_public_state

    full_text = "".join(full_text_parts).strip()
    end_call = bool(final_state.get("end_call", False))

    recorded_metrics = build_recorded_turn_metrics(
        state=final_state,
        total_delay_s=time.perf_counter() - turn_started_at,
        first_token_delay_s=first_token_delay_s,
    )

    if full_text:
        await _safe_record(
            "assistant_turn",
            call_id,
            recorder.record_turn(
                call_id=call_id,
                role="assistant",
                content=full_text,
                created_at=utcnow(),
                total_tokens=recorded_metrics["total_tokens"],
                total_delay_s=recorded_metrics["total_delay_s"],
                first_token_delay_s=recorded_metrics["first_token_delay_s"],
            ),
        )

    derived_status = _derive_status(final_state)
    scheduled_appointment = _extract_scheduled_appointment_snapshot(final_state)
    if derived_status:
        await _safe_record(
            "call_status",
            call_id,
            recorder.record_status(
                call_id=call_id,
                final_status=derived_status,
                scheduled_appointment=scheduled_appointment,
                overwrite_existing=True,
            ),
        )

    if end_call:
        await _safe_record(
            "finish_call",
            call_id,
            recorder.finish_call(
                call_id=call_id,
                final_status=_derive_final_status(final_state),
                scheduled_appointment=scheduled_appointment,
                ended_at=utcnow(),
                overwrite_existing=True,
            ),
        )

    public_state = serialize_live_call_state(call_id, final_state)
    await _ws_send(
        websocket,
        LiveAssistantCompletedOut(
            timestamp=_ts(),
            response_id=response_id,
            message=_assistant_message(
                call_id=call_id,
                response_id=response_id,
                content=full_text,
                created_at=response_created_at,
            ),
            metrics=build_live_turn_metrics(
                final_state,
                total_latency_s=recorded_metrics["total_delay_s"],
                first_token_delay_s=recorded_metrics["first_token_delay_s"],
            ),
            end_call=end_call,
            state=public_state,
        ),
    )
    await _emit_state_events(
        websocket=websocket,
        previous_state=previous_public_state,
        current_state=public_state,
    )
    return public_state


@router.websocket("/ws/{call_id}")
async def live_ui_ws(websocket: WebSocket, call_id: str) -> None:
    await websocket.accept()

    engine: InterviewEngine = websocket.app.state.engine
    store = websocket.app.state.store
    recorder = CallHistoryRecorder(AsyncSessionLocal)
    log_broker = get_live_log_broker()
    log_subscriber, log_backlog = log_broker.subscribe(call_id)
    log_forward_task: asyncio.Task[None] | None = None

    async def _forward_logs() -> None:
        while True:
            event = await log_subscriber.queue.get()
            details = {
                "logger": event.logger_name,
                "call_id": event.call_id,
            }
            if event.node:
                details["node"] = event.node
            if event.phase:
                details["phase"] = event.phase

            await _ws_send(
                websocket,
                LiveLogOut(
                    timestamp=event.timestamp,
                    level=_log_level_for_ui(event.level),
                    message=event.message,
                    details=details,
                ),
            )

    await _safe_record(
        "ensure_call_started",
        call_id,
        recorder.ensure_call_started(
            call_id=call_id,
            started_at=utcnow(),
        ),
    )

    stored_state = await store.get(call_id)
    current_public_state = serialize_live_call_state(call_id, stored_state)
    await _ws_send(
        websocket,
        LiveSessionReadyOut(
            timestamp=_ts(),
            call_id=call_id,
            state=current_public_state,
        ),
    )
    for event in log_backlog:
        details = {
            "logger": event.logger_name,
            "call_id": event.call_id,
        }
        if event.node:
            details["node"] = event.node
        if event.phase:
            details["phase"] = event.phase
        await _ws_send(
            websocket,
            LiveLogOut(
                timestamp=event.timestamp,
                level=_log_level_for_ui(event.level),
                message=event.message,
                details=details,
            ),
        )
    log_forward_task = asyncio.create_task(_forward_logs())
    await _emit_state_events(
        websocket=websocket,
        previous_state=None,
        current_state=current_public_state,
    )

    active_stream_cancel: asyncio.Event | None = None
    active_stream_task: asyncio.Task[LiveCallStateOut | None] | None = None
    active_response_id: int | None = None
    user_message_count = sum(message.role == "user" for message in current_public_state.messages)
    response_counter = 0

    async def _start_stream(
        *,
        response_id: int,
        event: CallEvent,
        user_text: str | None,
        trigger: str,
        meta: dict[str, Any] | None,
    ) -> None:
        nonlocal active_stream_cancel, active_stream_task, active_response_id

        active_stream_cancel = asyncio.Event()
        active_response_id = response_id

        async def _runner() -> LiveCallStateOut | None:
            return await _stream_engine_to_live(
                websocket=websocket,
                engine=engine,
                recorder=recorder,
                call_id=call_id,
                response_id=response_id,
                event=event,
                user_text=user_text,
                meta=meta,
                cancel_guard=active_stream_cancel,
                trigger=trigger,
                previous_public_state=current_public_state,
            )

        active_stream_task = asyncio.create_task(_runner())

    async def _sync_completed_stream_task() -> None:
        nonlocal active_stream_cancel, active_stream_task, active_response_id, current_public_state

        if active_stream_task is None or not active_stream_task.done():
            return

        try:
            maybe_state = await active_stream_task
            if maybe_state is not None:
                current_public_state = maybe_state
        except asyncio.CancelledError:
            pass
        finally:
            active_stream_task = None
            active_stream_cancel = None
            active_response_id = None

    async def _cancel_active_response(*, reason: str) -> None:
        nonlocal active_stream_cancel, active_stream_task, active_response_id

        await _sync_completed_stream_task()

        if active_stream_cancel is not None:
            active_stream_cancel.set()
        if active_stream_task is not None and not active_stream_task.done():
            active_stream_task.cancel()
        if active_response_id is not None:
            await _ws_send(
                websocket,
                LiveAssistantCancelledOut(
                    timestamp=_ts(),
                    response_id=active_response_id,
                    reason=reason,
                ),
            )

        await engine.cancel_active(call_id=call_id)
        active_stream_cancel = None
        active_stream_task = None
        active_response_id = None

    if not current_public_state.messages:
        await _start_stream(
            response_id=response_counter,
            event=CallEvent.CALL_STARTED,
            user_text=None,
            trigger="greeting",
            meta={"source": "react_live"},
        )
        response_counter += 1

    try:
        while True:
            await _sync_completed_stream_task()

            raw = await websocket.receive_text()
            await _sync_completed_stream_task()
            payload = json.loads(raw)
            event_in = _parse_client_event(payload)

            if isinstance(event_in, LivePingIn):
                await _ws_send(
                    websocket,
                    LivePongOut(
                        timestamp=_ts(),
                        client_timestamp=event_in.timestamp,
                    ),
                )
                continue

            if isinstance(event_in, LiveSnapshotRequestIn):
                latest_state = await store.get(call_id)
                current_public_state = serialize_live_call_state(call_id, latest_state)
                await _ws_send(
                    websocket,
                    LiveStateSnapshotOut(
                        timestamp=_ts(),
                        state=current_public_state,
                    ),
                )
                continue

            if isinstance(event_in, LiveCancelIn):
                await _cancel_active_response(reason="user_cancelled")
                continue

            if isinstance(event_in, LiveUserMessageIn):
                text = event_in.text.strip()
                if not text:
                    await _ws_send(
                        websocket,
                        LiveErrorOut(
                            timestamp=_ts(),
                            message="User message cannot be empty.",
                        ),
                    )
                    continue

                if active_stream_task is not None:
                    await _cancel_active_response(reason="barge_in")

                user_created_at = _ts()
                await _safe_record(
                    "user_turn",
                    call_id,
                    recorder.record_turn(
                        call_id=call_id,
                        role="user",
                        content=text,
                        created_at=utcnow(),
                    ),
                )

                user_message_count += 1
                await _ws_send(
                    websocket,
                    LiveUserMessageOut(
                        timestamp=user_created_at,
                        message=_user_message(
                            call_id=call_id,
                            index=user_message_count,
                            content=text,
                            created_at=user_created_at,
                        ),
                    ),
                )

                await _start_stream(
                    response_id=response_counter,
                    event=CallEvent.USER_TURN,
                    user_text=text,
                    trigger="user_message",
                    meta={"source": "react_live", "response_id": response_counter},
                )
                response_counter += 1
                continue

    except WebSocketDisconnect:
        return
    except Exception as exc:
        await _ws_send(
            websocket,
            LiveErrorOut(
                timestamp=_ts(),
                message=str(exc),
            ),
        )
        raise
    finally:
        if log_forward_task is not None:
            log_forward_task.cancel()
            with suppress(asyncio.CancelledError):
                await log_forward_task
        if active_stream_cancel is not None:
            active_stream_cancel.set()
        if active_stream_task is not None and not active_stream_task.done():
            active_stream_task.cancel()
        log_broker.unsubscribe(call_id, log_subscriber)

        latest_state: dict[str, Any] | None = None
        try:
            latest_state = await store.get(call_id)
        except Exception:
            logger.exception("Call state read failed on disconnect", extra={"call_id": call_id})

        scheduled_appointment = _extract_scheduled_appointment_snapshot(latest_state)
        await _safe_record(
            "disconnect_call",
            call_id,
            recorder.finish_call(
                call_id=call_id,
                final_status=_derive_disconnect_status(latest_state),
                scheduled_appointment=scheduled_appointment,
                ended_at=utcnow(),
            ),
        )
