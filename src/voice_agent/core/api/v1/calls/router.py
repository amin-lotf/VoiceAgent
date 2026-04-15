from __future__ import annotations

from datetime import datetime
from typing import Any, Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from voice_agent.core.db.session import AsyncSessionLocal
from voice_agent.core.db.uow import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/calls", tags=["calls"])


class CallTurnOut(BaseModel):
    role: str
    content: str
    created_at: str | None = None


class CallSummaryOut(BaseModel):
    call_id: str
    started_at: str
    ended_at: str | None = None
    duration_seconds: int | None = None
    final_status: str | None = None


class CallDetailOut(CallSummaryOut):
    turns: list[CallTurnOut]


def _to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _duration_seconds(started_at: datetime, ended_at: datetime | None) -> int | None:
    if ended_at is None:
        return None
    return max(0, int((ended_at - started_at).total_seconds()))


def _to_turn_out(turn: dict[str, Any]) -> CallTurnOut:
    return CallTurnOut(
        role=str(turn.get("role") or ""),
        content=str(turn.get("content") or ""),
        created_at=turn.get("created_at"),
    )


def _to_summary_out(call: Any) -> CallSummaryOut:
    return CallSummaryOut(
        call_id=call.call_id,
        started_at=_to_iso(call.started_at) or "",
        ended_at=_to_iso(call.ended_at),
        duration_seconds=_duration_seconds(call.started_at, call.ended_at),
        final_status=call.final_status,
    )


def _to_detail_out(call: Any) -> CallDetailOut:
    summary = _to_summary_out(call)
    return CallDetailOut(
        **summary.model_dump(),
        turns=[_to_turn_out(turn) for turn in (call.turns or [])],
    )


@router.get("", response_model=list[CallSummaryOut])
async def list_calls(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[CallSummaryOut]:
    async with AsyncSessionLocal() as session:
        uow = SqlAlchemyUnitOfWork(session)
        calls = await uow.calls.list_recent(limit=limit)
    return [_to_summary_out(call) for call in calls]


@router.get("/{call_id}", response_model=CallDetailOut)
async def get_call(call_id: str) -> CallDetailOut:
    async with AsyncSessionLocal() as session:
        uow = SqlAlchemyUnitOfWork(session)
        call = await uow.calls.get_by_call_id(call_id)

    if call is None:
        raise HTTPException(status_code=404, detail=f"Call not found: {call_id}")

    return _to_detail_out(call)
