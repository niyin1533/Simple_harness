"""@input Alembic configuration and application schema. @output Async MySQL migrations.
@position Schema tooling. @doc-sync Update INDEX.md on changes.
"""

import asyncio
from alembic import context
from app.db import Base, engine
from app.config import settings


def migrate(connection):
    context.configure(
        connection=connection, target_metadata=Base.metadata, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()


async def online():
    async with engine.connect() as connection:
        await connection.run_sync(migrate)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=settings.database_url, target_metadata=Base.metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online())
