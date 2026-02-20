from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from voice_agent.core.settings import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)