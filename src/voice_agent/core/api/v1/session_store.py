from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, TypedDict

from fastapi import FastAPI, HTTPException


# -------------------------
# Session record
# -------------------------
class SessionRecord(TypedDict):
    st: Dict[str, Any]          # private/internal (LangGraph state later)
    created_at: float
    updated_at: float


def _sid(x_session_id: str) -> str:
    sid = (x_session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="Missing session id (send header: X-Session-Id)")
    return sid


def _public_state(st: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert internal session state -> public UI-safe state.
    Keep this as the ONLY place that decides what is exposed.
    """
    return {
        "status": "ok",
        # later:
        # "phase": st.get("phase"),
        # "summary_available": bool(st.get("summary")),
        # "last_error": st.get("last_error"),
    }


def _get_lock(app: FastAPI, sid: str) -> asyncio.Lock:
    locks: Dict[str, asyncio.Lock] = app.state.session_locks
    lock = locks.get(sid)
    if lock is None:
        lock = asyncio.Lock()
        locks[sid] = lock
    return lock


def init_session_store(app: FastAPI) -> None:
    """
    Call once in app startup / app factory.
    """
    app.state.sessions_by_id: Dict[str, SessionRecord] = {}
    app.state.session_locks: Dict[str, asyncio.Lock] = {}


async def ensure_session_initialized(app: FastAPI, sid: str) -> SessionRecord:
    """
    Ensures a session record exists and returns it.
    Safe under concurrency.
    """
    lock = _get_lock(app, sid)
    async with lock:
        sessions: Dict[str, SessionRecord] = app.state.sessions_by_id
        rec = sessions.get(sid)
        if rec is not None:
            return rec

        now = time.time()
        rec = {
            "st": {},  # later: LangGraph state
            "created_at": now,
            "updated_at": now,
        }
        sessions[sid] = rec
        return rec


async def get_public_state(app: FastAPI, sid: str) -> Dict[str, Any]:
    rec = await ensure_session_initialized(app, sid)
    return _public_state(rec["st"])
