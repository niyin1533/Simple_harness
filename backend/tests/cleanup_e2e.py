"""@input Test-only resource markers in the independent database. @output Removal of E2E fixture records.
@position Test hygiene; never matches ordinary tasks. @doc-sync Update INDEX.md on changes.
"""

import asyncio
from sqlalchemy import select, delete
from app.db import (
    DB,
    engine,
    Run,
    Resource,
    Session,
    Message,
    Checkpoint,
    Approval,
    ToolCall,
    Event,
    Memory,
)
from app.config import settings


async def clean():
    assert "/agent_harness" in settings.database_url
    async with DB.begin() as db:
        runs = list(
            (
                await db.scalars(
                    select(Run).where(Run.task == "e2e: verify independent harness")
                )
            ).all()
        )
        runs = [
            r
            for r in runs
            if r.snapshot.get("model", {}).get("config", {}).get("endpoint")
            == "http://127.0.0.1:18991/v1"
        ]
        ids = [r.id for r in runs]
        sessions = [r.session_id for r in runs]
        for cls in (Approval, ToolCall, Event):
            await db.execute(delete(cls).where(cls.run_id.in_(ids)))
        for cls in (Message, Checkpoint):
            await db.execute(delete(cls).where(cls.session_id.in_(sessions)))
        await db.execute(delete(Run).where(Run.id.in_(ids)))
        await db.execute(delete(Session).where(Session.id.in_(sessions)))
        resources = list(
            (
                await db.scalars(
                    select(Resource).where(
                        Resource.kind == "model",
                        Resource.name.like("E2E temporary model %"),
                    )
                )
            ).all()
        )
        for row in resources:
            if row.config.get("endpoint") == "http://127.0.0.1:18991/v1":
                await db.delete(row)
        await db.execute(
            delete(Memory).where(Memory.content == "e2e-test: prefer concise responses")
        )
    await engine.dispose()
    print("Removed only marked E2E fixture records; user records preserved.")


if __name__ == "__main__":
    asyncio.run(clean())
