from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated

import redis.asyncio as redis
from fastapi import FastAPI, Header,Request

from voice_agent.core.api.v1.router import api_router
from voice_agent.core.api.v1.session_store import init_session_store, get_public_state, _sid
from voice_agent.core.api.v1.exception_handlers import register_exception_handlers
from voice_agent.core.db.session import AsyncSessionLocal
from voice_agent.core.graph.engine import InterviewEngine
from voice_agent.core.graph.input_buffer import CallInputBuffer
from voice_agent.core.store.redis_store import RedisStateStore

logger = logging.getLogger('voice_agent')

def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(f_app: FastAPI):
        r = redis.Redis(
            host="localhost",
            port=6379,
            decode_responses=True,
        )
        store = RedisStateStore(r, ttl_seconds=60 * 60)
        engine = InterviewEngine(store=store,sessionmaker=AsyncSessionLocal)



        f_app.state.redis = r
        f_app.state.store = store
        f_app.state.engine = engine

        try:
            yield
        finally:
            # Cancel active generation tasks (clean deploy)
            for active in list(engine._active.values()):
                if active and not active.task.done():
                    active.task.cancel()
            await r.aclose()

    f_app = FastAPI(
        title="Voice Agent API",
        description="Voice Agent API",
        version="0.1.0",
        lifespan=lifespan,
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

