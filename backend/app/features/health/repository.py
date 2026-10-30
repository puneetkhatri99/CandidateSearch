from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def ping_database(session: AsyncSession) -> None:
    await session.execute(text("SELECT 1"))


async def pgvector_installed(session: AsyncSession) -> bool:
    result = await session.scalar(
        text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
    )
    return bool(result)
