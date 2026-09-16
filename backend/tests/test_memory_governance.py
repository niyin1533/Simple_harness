"""@input Independent MySQL and mock governance responses. @output Stable-slot and validation regressions.
@position Memory migration tests. @doc-sync Update INDEX.md on changes.
"""

import json
from types import SimpleNamespace
import pytest
from sqlalchemy import select, delete
from app import memory_governance as mg, providers
from app.db import DB, User, Resource, Preference, Memory, uid, engine
from app.deployments import interpreter_for, preflight


def operation(**overrides):
    return {
        "action": "create",
        "scope": "user",
        "type": "fact",
        "entity": "user",
        "attribute": "name",
        "value": "Ming",
        "content": "User name is Ming",
        "confidence": 0.9,
        **overrides,
    }


def test_validation_and_slots():
    assert mg.slot({"entity": " USER ", "attribute": "Name!"}) == ("user", "name")
    for op in [
        operation(confidence=0.2),
        operation(type="unknown"),
        operation(action="update", targetMemoryId="other"),
        operation(content=""),
    ]:
        with pytest.raises(ValueError):
            mg.validate_operations({"operations": [op]}, [], True)
    with pytest.raises(ValueError):
        mg.validate_operations(
            {"operations": [{"action": "delete", "targetMemoryId": "x"}]},
            [SimpleNamespace(id="x")],
            False,
        )


@pytest.mark.asyncio
async def test_structured_empty_retry(monkeypatch):
    calls = []

    async def reply(model, messages, *, json_mode):
        assert json_mode
        calls.append(messages)
        if len(calls) == 1:
            raise ValueError("empty")
        return {"content": '{"operations":[]}'}

    monkeypatch.setattr(providers, "complete", reply)
    assert await providers.structured(
        {}, [], lambda v: mg.validate_operations(v, [], True)
    ) == {"operations": []}
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_stable_update_duplicate_pending_and_isolation(monkeypatch):
    user_id, other_id, model_id = uid(), uid(), uid()
    outputs = [
        operation(),
        operation(),
        operation(content="User name is Hong", value="Hong"),
    ]

    async def structured(model, messages, validate):
        context = json.loads(messages[1]["content"])
        assert all(r["content"] != "Other private memory" for r in context["existing"])
        op = outputs.pop(0)
        value = {"operations": [op]}
        validate(value)
        return value

    monkeypatch.setattr(mg, "structured", structured)
    try:
        async with DB.begin() as db:
            db.add_all(
                [
                    User(id=user_id, username=user_id, password="unused"),
                    User(id=other_id, username=other_id, password="unused"),
                    Resource(id=model_id, kind="model", name="fixture", config={}),
                    Preference(
                        user_id=user_id, config={"governance_model_id": model_id}
                    ),
                    Memory(user_id=other_id, content="Other private memory"),
                ]
            )
        for _ in range(3):
            async with DB.begin() as db:
                await mg.govern(db, user_id, "agent", "request", True)
        async with DB() as db:
            rows = (
                await db.scalars(select(Memory).where(Memory.user_id == user_id))
            ).all()
            assert (
                len(rows) == 1
                and rows[0].content == "User name is Hong"
                and rows[0].confirmed
            )
            assert rows[0].agent_id is None and rows[0].meta["type"] == "fact"

        async def invalid(*args):
            raise ValueError("invalid output")

        monkeypatch.setattr(mg, "structured", invalid)
        for _ in range(2):
            async with DB.begin() as db:
                assert (await mg.govern(db, user_id, "agent", "pending request", True))[
                    "status"
                ] == "pending_review"
        async with DB() as db:
            rows = (
                await db.scalars(select(Memory).where(Memory.user_id == user_id))
            ).all()
            assert len(rows) == 2 and sum(not r.confirmed for r in rows) == 1
    finally:
        async with DB.begin() as db:
            for cls in (Memory, Preference):
                await db.execute(
                    delete(cls).where(cls.user_id.in_([user_id, other_id]))
                )
            await db.execute(delete(User).where(User.id.in_([user_id, other_id])))
            await db.execute(delete(Resource).where(Resource.id == model_id))
        await engine.dispose()


@pytest.mark.asyncio
async def test_template_dependency_error():
    import sys

    assert interpreter_for({"python": sys.executable}) == sys.executable
    # The backend intentionally does not install GPU/YOLO dependencies.
    import importlib.util

    if importlib.util.find_spec("ultralytics") is None:
        with pytest.raises(ValueError, match="ultralytics"):
            await preflight(sys.executable, {"runtime": "yolo"})
