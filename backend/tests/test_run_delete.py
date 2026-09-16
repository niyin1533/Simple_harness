"""@input Independent MySQL fixtures. @output Ownership, terminal-state and atomic cleanup checks.
@position Task deletion regression. @doc-sync Update INDEX.md on changes.
"""

from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from app.db import DB, Run, Event, ToolCall, Approval, Message, uid, engine
from app.main import delete_run_records


@pytest.mark.asyncio
async def test_run_deletion_is_atomic_private_and_preserves_chat():
    owner, other, session = uid(), uid(), uid()
    ids = [uid() for _ in range(3)]
    call_id = uid()
    try:
        async with DB.begin() as db:
            for id, user, status in [
                (ids[0], owner, "SUCCEEDED"),
                (ids[1], owner, "PAUSED"),
                (ids[2], other, "FAILED"),
            ]:
                db.add(
                    Run(
                        id=id,
                        user_id=user,
                        session_id=session,
                        agent_id="fixture",
                        task="fixture",
                        snapshot={},
                        status=status,
                    )
                )
            db.add(Event(run_id=ids[0], seq=1, name="RUN_SUCCEEDED"))
            db.add(
                ToolCall(
                    id=call_id, run_id=ids[0], capability_id="fixture", arguments={}
                )
            )
            db.add(Approval(run_id=ids[0], call_id=call_id, request_hash="fixture"))
            db.add(Message(session_id=session, role="assistant", content="preserved"))
        for pair, status in [([ids[0], ids[2]], 404), ([ids[0], ids[1]], 409)]:
            with pytest.raises(HTTPException) as exc:
                await delete_run_records(pair, SimpleNamespace(id=owner))
            assert exc.value.status_code == status
            async with DB() as db:
                assert await db.get(Run, ids[0]) is not None
        assert await delete_run_records(
            [ids[0], ids[0]], SimpleNamespace(id=owner)
        ) == {"deleted": 1}
        async with DB() as db:
            assert await db.get(Run, ids[0]) is None
            for cls in (Event, ToolCall, Approval):
                assert await db.scalar(select(cls).where(cls.run_id == ids[0])) is None
            assert (
                await db.scalar(select(Message).where(Message.session_id == session))
                is not None
            )
    finally:
        async with DB.begin() as db:
            for cls in (Approval, ToolCall, Event):
                await db.execute(delete(cls).where(cls.run_id.in_(ids)))
            await db.execute(delete(Run).where(Run.id.in_(ids)))
            await db.execute(delete(Message).where(Message.session_id == session))
        await engine.dispose()
