from __future__ import annotations

from datetime import datetime
from typing import Any, Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from voice_agent.core.db.session import AsyncSessionLocal
from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.graph.node_timing import (
    get_recorded_turn_metrics,
    summarize_recorded_turn_metrics,
)
from voice_agent.const import TOTAL_DELAY_KEY, TOTAL_TOKENS_KEY, FIRST_TOKEN_DELAY_KEY

router = APIRouter(prefix="/calls", tags=["calls"])


class CallTurnOut(BaseModel):
    role: str
    content: str
    created_at: str | None = None
    total_tokens: int | None = None
    total_delay_s: float | None = None
    first_token_delay_s: float | None = None


class CallLogOut(BaseModel):
    timestamp: str
    level: Literal["debug", "info", "warning", "error"]
    message: str
    details: dict[str, Any] | None = None


class CallSummaryOut(BaseModel):
    call_id: str
    started_at: str
    ended_at: str | None = None
    duration_seconds: int | None = None
    final_status: str | None = None
    total_tokens: int = 0
    avg_total_delay_s: float | None = None
    avg_first_token_delay_s: float | None = None


class ScheduledAppointmentOut(BaseModel):
    id: int
    name: str | None = None
    phone: str | None = None
    reason_for_visit: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    notes: list[str] = Field(default_factory=list)
    status: str | None = None
    patient_type: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class CallDetailOut(CallSummaryOut):
    turns: list[CallTurnOut]
    logs: list[CallLogOut] = Field(default_factory=list)
    scheduled_appointment: ScheduledAppointmentOut | None = None


def _to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _duration_seconds(started_at: datetime, ended_at: datetime | None) -> int | None:
    if ended_at is None:
        return None
    return max(0, int((ended_at - started_at).total_seconds()))


def _to_turn_out(turn: dict[str, Any]) -> CallTurnOut:
    metrics = get_recorded_turn_metrics(turn)
    return CallTurnOut(
        role=str(turn.get("role") or ""),
        content=str(turn.get("content") or ""),
        created_at=turn.get("created_at"),
        total_tokens=metrics[TOTAL_TOKENS_KEY],
        total_delay_s=metrics[TOTAL_DELAY_KEY],
        first_token_delay_s=metrics[FIRST_TOKEN_DELAY_KEY],
    )


def _to_log_level(value: Any) -> Literal["debug", "info", "warning", "error"]:
    normalized = str(value or "info").strip().lower()
    if normalized == "critical":
        return "error"
    if normalized in {"debug", "info", "warning", "error"}:
        return normalized
    return "info"


def _to_log_out(log: dict[str, Any]) -> CallLogOut:
    raw_details = log.get("details")
    if isinstance(raw_details, dict):
        details = dict(raw_details)
    else:
        details = {}
        if log.get("logger_name") is not None:
            details["logger"] = str(log.get("logger_name"))
        if log.get("call_id") is not None:
            details["call_id"] = str(log.get("call_id"))
        if log.get("node") is not None:
            details["node"] = str(log.get("node"))
        if log.get("phase") is not None:
            details["phase"] = str(log.get("phase"))
        if not details:
            details = None

    return CallLogOut(
        timestamp=str(log.get("timestamp") or ""),
        level=_to_log_level(log.get("level")),
        message=str(log.get("message") or ""),
        details=details,
    )


def _to_summary_out(call: Any) -> CallSummaryOut:
    metrics = summarize_recorded_turn_metrics(call.turns or [])
    return CallSummaryOut(
        call_id=call.call_id,
        started_at=_to_iso(call.started_at) or "",
        ended_at=_to_iso(call.ended_at),
        duration_seconds=_duration_seconds(call.started_at, call.ended_at),
        final_status=call.final_status,
        total_tokens=int(metrics[TOTAL_TOKENS_KEY] or 0),
        avg_total_delay_s=metrics["avg_total_delay_s"],
        avg_first_token_delay_s=metrics["avg_first_token_delay_s"],
    )


def _to_scheduled_appointment_out(snapshot: dict[str, Any] | None) -> ScheduledAppointmentOut | None:
    if not snapshot or snapshot.get("id") is None:
        return None
    return ScheduledAppointmentOut(
        id=int(snapshot["id"]),
        name=snapshot.get("name"),
        phone=snapshot.get("phone"),
        reason_for_visit=snapshot.get("reason_for_visit"),
        start_at=snapshot.get("start_at"),
        end_at=snapshot.get("end_at"),
        notes=list(snapshot.get("notes") or []),
        status=str(snapshot.get("status")) if snapshot.get("status") is not None else None,
        patient_type=str(snapshot.get("patient_type")) if snapshot.get("patient_type") is not None else None,
        created_at=snapshot.get("created_at"),
        updated_at=snapshot.get("updated_at"),
    )


def _to_detail_out(call: Any) -> CallDetailOut:
    summary = _to_summary_out(call)
    return CallDetailOut(
        **summary.model_dump(),
        turns=[_to_turn_out(turn) for turn in (call.turns or [])],
        logs=[_to_log_out(log) for log in (getattr(call, "logs", None) or [])],
        scheduled_appointment=_to_scheduled_appointment_out(
            getattr(call, "scheduled_appointment", None),
        ),
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
