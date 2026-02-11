from typing import Dict, Any, Annotated

from fastapi import APIRouter, HTTPException, Header,Request

from voice_agent.core.api.v1.session_store import _sid, get_public_state

router = APIRouter(prefix="/dashboard", tags=["dashboard"])





@router.get("/session/state")
async def get_session_state(
    request: Request,
    x_session_id: Annotated[str, Header(alias="X-Session-Id")] = "",
):
    sid = _sid(x_session_id)
    return await get_public_state(request.app, sid)