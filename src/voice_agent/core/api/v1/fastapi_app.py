from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Header,Request

from voice_agent.core.api.v1.router import api_router
from voice_agent.core.api.v1.session_store import init_session_store, get_public_state, _sid
from voice_agent.core.api.v1.exception_handlers import register_exception_handlers
from voice_agent.core.graph.engine import InterviewEngine

logger = logging.getLogger('voice_agent')

def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(f_app: FastAPI):
        f_app.state.engine = InterviewEngine()
        yield
    app = FastAPI(
        title="Voice Agent API",
        description="Voice Agent API",
        version="0.1.0",
        lifespan=lifespan,
    )
    init_session_store(app)
    app.include_router(api_router, prefix="/api/v1")
    @app.get("/")
    async def root():
        return {"status": "ok", "service": "Voice Agent", "version": "0.1.0"}

    @app.get("/api/v1/session/state")
    async def get_session_state(
            request: Request,
            x_session_id: Annotated[str, Header(alias="X-Session-Id")] = "",
    ):
        sid = _sid(x_session_id)
        return await get_public_state(request.app, sid)

    register_exception_handlers(app)
    return app
fastapi_app = create_app()

