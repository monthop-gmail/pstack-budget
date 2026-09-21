from sqlalchemy.ext.asyncio import AsyncSession

from .watch_services import seed_initial_source


async def on_install(session: AsyncSession) -> None:
    await seed_initial_source(session)
    await session.commit()


async def on_upgrade(session: AsyncSession, from_version: str) -> None:
    await seed_initial_source(session)
    await session.commit()
