import asyncio
import json
import logging
import time
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel
from starlette.websockets import WebSocket, WebSocketDisconnect
import logging

from voice_agent.core.api.v1.schemas import RetellResponseRequiredIn, RetellUpdateOnlyIn, RetellPingPongIn, \
    RetellResponseOut, RetellConfigOut, RetellConfig, RetellInbound, RetellPingPongOut
from voice_agent.core.graph.engine import InterviewEngine
from voice_agent.core.types import CallEvent, ChunkKind

router = APIRouter(prefix="/retell", tags=["retell"])

logger = logging.getLogger(__name__)
def parse_retell_inbound(payload: dict[str, Any]) -> RetellInbound:
    t = payload.get("interaction_type")
    if t == "ping_pong":
        return RetellPingPongIn.model_validate(payload)
    if t == "update_only":
        return RetellUpdateOnlyIn.model_validate(payload)
    if t in ("response_required", "reminder_required"):
        return RetellResponseRequiredIn.model_validate(payload)
    raise ValueError(f"Unknown interaction_type: {t}")


async def ws_send(websocket: WebSocket, obj: BaseModel) -> None:
    # Retell uses text frames that contain stringified JSON
    await websocket.send_text(obj.model_dump_json())


def _last_user_text(transcript: list[dict[str, Any]]) -> str:
    # Retell transcript items are dicts; user messages typically have role="user"
    for item in reversed(transcript):
        if item.get("role") == "user":
            return item.get("content", "") or ""
    return ""

async def run_engine_to_retell(
    *,
    websocket: WebSocket,
    engine: InterviewEngine,
    call_id: str,
    response_id: int,
    event: CallEvent,
    user_text: str | None,
    meta: dict[str, Any] | None,
) -> None:
    """
    Non-streaming: run engine once and send a single RetellResponseOut with content_complete=True.
    """
    result = await engine.run_event(
        call_id=call_id,
        event=event,
        user_text=user_text,
        meta=meta,
    )

    final_state = result.state or {}
    end_call_flag = bool(final_state.get("end_call", False))

    await ws_send(
        websocket,
        RetellResponseOut(
            response_id=response_id,
            content=result.assistant_text or "",
            content_complete=True,
            end_call=True if end_call_flag else None,
        ),
    )



async def stream_engine_to_retell(
    *,
    websocket: WebSocket,
    engine: InterviewEngine,
    call_id: str,
    response_id: int,
    event: CallEvent,
    user_text: str | None,
    meta: dict[str, Any] | None,
    cancel_guard: asyncio.Event,
) -> None:
    end_call_flag = False
    full_text_parts: list[str] = []

    async for chunk in engine.stream_event(
        call_id=call_id,
        event=event,
        user_text=user_text,
        meta=meta,
    ):
        if cancel_guard.is_set():
            logger.warning(
                "RETELL STREAM CANCELLED | call_id=%s | response_id=%s | partial=%r",
                call_id,
                response_id,
                "".join(full_text_parts),
            )
            break

        if chunk.kind == ChunkKind.TOKEN:
            token_text = str(chunk.data)
            full_text_parts.append(token_text)

            # logger.warning(
            #     "RETELL TOKEN | call_id=%s | response_id=%s | token=%r",
            #     call_id,
            #     response_id,
            #     token_text,
            # )

            await ws_send(
                websocket,
                RetellResponseOut(
                    response_id=response_id,
                    content=token_text,
                    content_complete=False,
                ),
            )

        elif chunk.kind == ChunkKind.FINAL:
            final_state = chunk.data or {}
            end_call_flag = bool(final_state.get("end_call", False))

    full_text = "".join(full_text_parts)
    logger.warning(
        "RETELL FULL ASSISTANT | call_id=%s | response_id=%s | text=%r",
        call_id,
        response_id,
        full_text,
    )

    await ws_send(
        websocket,
        RetellResponseOut(
            response_id=response_id,
            content="",
            content_complete=True,
            end_call=True if end_call_flag else None,
        ),
    )


@router.websocket("/llm/{call_id}")
async def retell_llm_ws(websocket: WebSocket, call_id: str):
    await websocket.accept()
    engine: InterviewEngine = websocket.app.state.engine

    # 1) Optional config on connect (Retell supports it)
    await ws_send(
        websocket,
        RetellConfigOut(
            config=RetellConfig(
                auto_reconnect=True,
                call_details=False,
                transcript_with_tool_calls=False,
            )
        ),
    )
    # begin = await engine.run_event(
    #     call_id=call_id,
    #     event=CallEvent.CALL_STARTED,
    #     user_text=None,
    #     meta={"retell_phase": "call_started"},
    # )
    #
    # await ws_send(
    #     websocket,
    #     RetellResponseOut(
    #         response_id=0,
    #         content=begin.assistant_text or "",
    #         content_complete=True,
    #     ),
    # )

    await ws_send(
        websocket,
        RetellResponseOut(
            response_id=0,
            content="",
            content_complete=False,
        ),
    )

    # 2) Keepalive (Retell uses ping/pong with auto_reconnect) :contentReference[oaicite:1]{index=1}
    stop_ping = asyncio.Event()

    async def _ping_loop() -> None:
        while not stop_ping.is_set():
            await ws_send(websocket, RetellPingPongOut(timestamp=int(time.time() * 1000)))
            try:
                await asyncio.wait_for(stop_ping.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

    # Agent speaks first: stream greeting under response_id=0
    greeting_cancel = asyncio.Event()
    greeting_task = asyncio.create_task(
        stream_engine_to_retell(
            websocket=websocket,
            engine=engine,
            call_id=call_id,
            response_id=0,
            event=CallEvent.CALL_STARTED,
            user_text=None,
            meta={"retell_phase": "call_started"},
            cancel_guard=greeting_cancel,
        )
    )

    ping_task = asyncio.create_task(_ping_loop())


    # 4) Handle Retell inbound events
    # When response_required arrives, barge-in: cancel greeting + cancel engine + stream new response_id
    active_stream_cancel: Optional[asyncio.Event] = None
    active_stream_task: Optional[asyncio.Task] = None

    try:
        while True:

            raw = await websocket.receive_text()
            payload = json.loads(raw)
            inbound = parse_retell_inbound(payload)
            if isinstance(inbound, RetellPingPongIn):
                await ws_send(websocket, RetellPingPongOut(timestamp=int(time.time() * 1000)))
                continue

            if isinstance(inbound, RetellUpdateOnlyIn):
                # You can optionally store inbound.turntaking/transcript in redis for debugging/analytics
                continue

            if isinstance(inbound, RetellResponseRequiredIn):
                # Barge-in: stop greeting + stop any active stream
                if greeting_task is not None and not greeting_task.done():
                    greeting_cancel.set()
                    greeting_task.cancel()

                if active_stream_cancel is not None:
                    active_stream_cancel.set()
                if active_stream_task is not None and not active_stream_task.done():
                    active_stream_task.cancel()

                await engine.cancel_active(call_id=call_id)

                user_text = _last_user_text(inbound.transcript)

                # Start a fresh stream for THIS response_id
                active_stream_cancel = asyncio.Event()
                active_stream_task = asyncio.create_task(
                    stream_engine_to_retell(
                        websocket=websocket,
                        engine=engine,
                        call_id=call_id,
                        response_id=inbound.response_id,
                        event=CallEvent.USER_TURN,
                        user_text=user_text,
                        meta={
                            "retell_response_id": inbound.response_id,
                            "interaction_type": inbound.interaction_type,
                        },
                        cancel_guard=active_stream_cancel,
                    )
                )

    except WebSocketDisconnect:
        return
    finally:
        stop_ping.set()
        ping_task.cancel()
        if active_stream_cancel is not None:
            active_stream_cancel.set()
        if active_stream_task is not None:
            active_stream_task.cancel()
        if greeting_task is not None and not greeting_task.done():
            greeting_cancel.set()
            greeting_task.cancel()