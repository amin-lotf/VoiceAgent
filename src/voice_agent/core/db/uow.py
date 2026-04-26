from sqlalchemy.ext.asyncio import AsyncSession

from voice_agent.core.db.repository import (
    SqlAlchemyAppointmentRepository,
    SqlAlchemyCallRepository,
    SqlAlchemyCrmSyncEventRepository,
)


class SqlAlchemyUnitOfWork:
    def __init__(self, session: AsyncSession):
        self._session = session
        self.appointments = SqlAlchemyAppointmentRepository(session)
        self.calls = SqlAlchemyCallRepository(session)
        self.crm_sync_events = SqlAlchemyCrmSyncEventRepository(session)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc:
            await self.rollback()
        else:
            await self.commit()
