from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from voice_agent.core.db.uow import SqlAlchemyUnitOfWork


class CallHistoryRecorder:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def ensure_call_started(
        self,
        *,
        call_id: str,
        started_at: datetime | None = None,
    ) -> None:
        async with self._sessionmaker() as session:
            async with SqlAlchemyUnitOfWork(session) as uow:
                await uow.calls.create_or_get(call_id=call_id, started_at=started_at)

    async def record_turn(
        self,
        *,
        call_id: str,
        role: str,
        content: str,
        created_at: datetime | None = None,
        total_tokens: int | None = None,
        total_delay_s: float | None = None,
        first_token_delay_s: float | None = None,
    ) -> None:
        async with self._sessionmaker() as session:
            async with SqlAlchemyUnitOfWork(session) as uow:
                await uow.calls.append_turn(
                    call_id=call_id,
                    role=role,
                    content=content,
                    created_at=created_at,
                    total_tokens=total_tokens,
                    total_delay_s=total_delay_s,
                    first_token_delay_s=first_token_delay_s,
                )

    async def finish_call(
        self,
        *,
        call_id: str,
        final_status: str | None = None,
        ended_at: datetime | None = None,
        overwrite_existing: bool = False,
    ) -> None:
        async with self._sessionmaker() as session:
            async with SqlAlchemyUnitOfWork(session) as uow:
                await uow.calls.finish(
                    call_id=call_id,
                    final_status=final_status,
                    ended_at=ended_at,
                    overwrite_existing=overwrite_existing,
                )

    async def record_status(
        self,
        *,
        call_id: str,
        final_status: str | None,
        overwrite_existing: bool = False,
    ) -> None:
        async with self._sessionmaker() as session:
            async with SqlAlchemyUnitOfWork(session) as uow:
                await uow.calls.update_status(
                    call_id=call_id,
                    final_status=final_status,
                    overwrite_existing=overwrite_existing,
                )
