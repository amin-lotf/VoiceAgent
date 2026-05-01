from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from contextlib import asynccontextmanager, suppress
from typing import Annotated

import redis.asyncio as redis
from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware

from voice_agent.core.api.v1.exception_handlers import register_exception_handlers
from voice_agent.core.api.v1.router import api_router
from voice_agent.core.api.v1.session_store import _sid, get_public_state, init_session_store
from voice_agent.core.db.session import AsyncSessionLocal
from voice_agent.core.graph.engine import InterviewEngine
from voice_agent.core.services.call_history import CallHistoryRecorder
from voice_agent.core.services.hubspot_sync import run_hubspot_sync_worker
from voice_agent.core.settings import settings
from voice_agent.core.store.redis_store import RedisStateStore
from voice_agent.logging import (
    LiveLogEvent,
    clear_live_log_persistence,
    configure_live_log_persistence,
    serialize_live_log_event,
    setup_logging,
)

logger = logging.getLogger("voice_agent")

_LOG_PERSIST_QUEUE_SIZE = 1000
_LOG_PERSIST_BATCH_SIZE = 100


def _enqueue_live_log_for_persistence(
    queue: asyncio.Queue[LiveLogEvent | None],
    event: LiveLogEvent,
) -> None:
    if queue.full():
        with suppress(asyncio.QueueEmpty):
            queue.get_nowait()
    with suppress(asyncio.QueueFull):
        queue.put_nowait(event)


async def _persist_live_log_batches(
    queue: asyncio.Queue[LiveLogEvent | None],
) -> None:
    recorder = CallHistoryRecorder(AsyncSessionLocal)

    while True:
        item = await queue.get()
        if item is None:
            break

        batch = [item]
        while len(batch) < _LOG_PERSIST_BATCH_SIZE:
            try:
                queued_item = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            if queued_item is None:
                await queue.put(None)
                break

            batch.append(queued_item)

        logs_by_call_id: dict[str, list[dict[str, object]]] = defaultdict(list)
        for event in batch:
            logs_by_call_id[event.call_id].append(serialize_live_log_event(event))

        for call_id, logs in logs_by_call_id.items():
            try:
                await recorder.record_logs(call_id=call_id, logs=logs)
            except Exception:
                logger.exception(
                    "Call log persistence failed | call_id=%s | count=%s",
                    call_id,
                    len(logs),
                )


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(f_app: FastAPI):
        r = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
        store = RedisStateStore(r, ttl_seconds=60 * 60)
        engine = InterviewEngine(store=store, sessionmaker=AsyncSessionLocal)
        hubspot_worker_task: asyncio.Task[None] | None = None
        live_log_persist_queue: asyncio.Queue[LiveLogEvent | None] = asyncio.Queue(
            maxsize=_LOG_PERSIST_QUEUE_SIZE,
        )
        live_log_persist_task = asyncio.create_task(
            _persist_live_log_batches(live_log_persist_queue),
            name="live-log-persist",
        )
        loop = asyncio.get_running_loop()

        def _schedule_live_log_persist(event: LiveLogEvent) -> None:
            try:
                loop.call_soon_threadsafe(
                    _enqueue_live_log_for_persistence,
                    live_log_persist_queue,
                    event,
                )
            except RuntimeError:
                return

        configure_live_log_persistence(_schedule_live_log_persist)

        if settings.HUBSPOT_ACCESS_TOKEN:
            hubspot_worker_task = asyncio.create_task(
                run_hubspot_sync_worker(sessionmaker=AsyncSessionLocal),
                name="hubspot-sync-worker",
            )
        else:
            logger.warning("HubSpot sync worker disabled because HUBSPOT_ACCESS_TOKEN is not configured")

        f_app.state.redis = r
        f_app.state.store = store
        f_app.state.engine = engine
        f_app.state.hubspot_worker_task = hubspot_worker_task
        f_app.state.live_log_persist_task = live_log_persist_task

        try:
            yield
        finally:
            clear_live_log_persistence()
            await live_log_persist_queue.put(None)
            with suppress(asyncio.CancelledError):
                await live_log_persist_task
            if hubspot_worker_task is not None:
                hubspot_worker_task.cancel()
                with suppress(asyncio.CancelledError):
                    await hubspot_worker_task
            for active in list(engine._active.values()):
                if active and not active.task.done():
                    active.task.cancel()
            await r.aclose()

    setup_logging()
    f_app = FastAPI(
        title="Voice Agent API",
        description="Voice Agent API",
        version="0.1.0",
        lifespan=lifespan,
    )
    f_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    init_session_store(f_app)
    f_app.include_router(api_router, prefix="/api/v1")

    @f_app.get("/")
    async def root():
        return {"status": "ok", "service": "Voice Agent", "version": "0.1.0"}

    @f_app.get("/api/v1/session/state")
    async def get_session_state(
        request: Request,
        x_session_id: Annotated[str, Header(alias="X-Session-Id")] = "",
    ):
        sid = _sid(x_session_id)
        return await get_public_state(request.app, sid)

    register_exception_handlers(f_app)
    return f_app


fastapi_app = create_app()
