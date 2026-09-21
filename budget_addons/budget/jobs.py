import os

from core.db import get_sessionmaker
from core.jobs import periodic_job

from .watch_services import run_once


def _minutes() -> set[int]:
    try:
        interval = int(os.environ.get("WATCH_INTERVAL_MINUTES", "15"))
    except ValueError:
        interval = 15
    return set(range(0, 60, interval if 1 <= interval <= 60 and 60 % interval == 0 else 15))


@periodic_job(minute=_minutes())
async def poll_public_watch_sources(ctx) -> None:
    async with get_sessionmaker()() as session:
        await run_once(session)
        await session.commit()
