"""@input Independent MySQL database and mock model responses. @output Runtime/API isolation regression.
@position Integration verification; creates and cleans only test-owned UUID rows. @doc-sync Update INDEX.md on changes.
"""

import asyncio
import json
import pytest
import httpx
from sqlalchemy import select, delete
from app import runtime
from app.config import settings
from app.db import (
    DB,
    engine,
    User,
    Resource,
    Run,
    Session,
    Message,
    Event,
    ToolCall,
    Approval,
    Memory,
    Preference,
    Login,
    Checkpoint,
    uid,
    now,
)
from app.main import app
from app.security import hasher


@pytest.mark.asyncio
async def test_durable_runtime_and_api_isolation(tmp_path, monkeypatch):
    assert "/agent_harness" in settings.database_url, (
        "Integration tests require the independent agent database"
    )
    user_ids = [uid(), uid()]
    resource_ids = [uid(), uid(), uid()]
    run_ids = []
    session_ids = []
    password = "Test-only-" + uid()

    repaired = False

    async def response(model, messages, *, json_mode=False):
        nonlocal repaired
        assert json_mode
        if any("工具结果" in m["content"] for m in messages):
            if not repaired:
                if not any("上一轮输出未通过" in m["content"] for m in messages):
                    return {"content": "finished without JSON", "usage": {}}
                repaired = True
            return {
                "content": json.dumps({"action": "final", "answer": "finished"}),
                "usage": {},
            }
        return {
            "content": json.dumps(
                {
                    "action": "tool_call",
                    "toolId": "builtin.fs.write",
                    "arguments": {"path": "result.txt", "content": "verified"},
                }
            ),
            "usage": {},
        }

    monkeypatch.setattr(runtime, "complete", response)

    async def claim(id):
        async with DB.begin() as db:
            r = await db.get(Run, id, with_for_update=True)
            r.status = "RUNNING"
            r.lease_owner = "test-owner"
            r.lease_until = now() + 15000
        await runtime.run_loop(id, "test-owner")

    async def make(target):
        async with DB.begin() as db:
            r = await runtime.create_run(db, user_ids[0], target, "write the result")
            run_ids.append(r.id)
            session_ids.append(r.session_id)
            return r.id

    try:
        async with DB.begin() as db:
            for i, id in enumerate(user_ids):
                db.add(
                    User(
                        id=id,
                        username="test-" + id,
                        password=hasher.hash(password),
                        admin=i == 0,
                    )
                )
            db.add(
                Resource(
                    id=resource_ids[0],
                    kind="model",
                    name="Test mock model",
                    config={"model": "mock"},
                )
            )
            db.add(
                Resource(
                    id=resource_ids[1],
                    kind="agent",
                    name="Test approved writer",
                    config={
                        "model_id": resource_ids[0],
                        "system_prompt": "test",
                        "workspace_path": str(tmp_path),
                        "permission_preset": "workspace-write",
                    },
                )
            )
            db.add(
                Resource(
                    id=resource_ids[2],
                    kind="agent",
                    name="Test blocked failures",
                    config={
                        "model_id": resource_ids[0],
                        "system_prompt": "test",
                        "workspace_path": str(tmp_path),
                        "permission_preset": "danger-full-access",
                        "limits": {"max_consecutive_failures": 1, "tool_retries": 0},
                    },
                )
            )
        id = await make(resource_ids[1])
        await claim(id)
        async with DB() as db:
            r = await db.get(Run, id)
            assert r.status == "WAITING_APPROVAL"
            approval = await db.scalar(select(Approval).where(Approval.run_id == id))
            approval_id = approval.id
            assert not (tmp_path / "result.txt").exists()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            login = await client.post(
                "/api/v1/auth/login",
                json={"username": "test-" + user_ids[0], "password": password},
            )
            assert login.status_code == 200
            csrf = login.json()["csrf"]
            assert (
                await client.post(
                    "/api/v1/approvals/" + approval_id, json={"approved": True}
                )
            ).status_code == 403
            client.headers["X-CSRF-Token"] = csrf
            assert (
                await client.post(
                    "/api/v1/approvals/" + approval_id, json={"approved": True}
                )
            ).status_code == 200
            assert (
                await client.post(
                    "/api/v1/approvals/" + approval_id, json={"approved": True}
                )
            ).status_code == 400
            await claim(id)
            detail = (await client.get("/api/v1/runs/" + id)).json()
            assert detail["run"]["status"] == "SUCCEEDED", detail
            assert (
                "snapshot" not in detail["run"] and detail["approvals"][0]["consumed"]
            )
            assert (tmp_path / "result.txt").read_text() == "verified"
            events = (await client.get("/api/v1/runs/" + id + "/events")).json()
            assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
            tail = (await client.get("/api/v1/runs/" + id + "/events?after=3")).json()
            assert all(e["seq"] > 3 for e in tail)
            memory = (
                await client.post(
                    "/api/v1/memories", json={"content": "test private memory"}
                )
            ).json()
            login = await client.post(
                "/api/v1/auth/login",
                json={"username": "test-" + user_ids[1], "password": password},
            )
            client.headers["X-CSRF-Token"] = login.json()["csrf"]
            assert (await client.get("/api/v1/runs/" + id)).status_code == 404
            assert (
                await client.get("/api/v1/sessions/" + session_ids[0] + "/messages")
            ).status_code == 404
            assert (
                await client.put(
                    "/api/v1/memories/" + memory["id"], json={"content": "intrusion"}
                )
            ).status_code == 404
            assert (
                await client.post("/api/v1/resources/model", json={"name": "forbidden"})
            ).status_code == 403

        # A failed side effect is durably recorded before the run reaches its failure budget.
        async def broken(*args):
            raise ValueError("deliberate tool error")

        monkeypatch.setattr(runtime, "execute", broken)
        id = await make(resource_ids[2])
        await claim(id)
        async with DB() as db:
            r = await db.get(Run, id)
            call = await db.scalar(select(ToolCall).where(ToolCall.run_id == id))
            assert (
                r.status == "FAILED"
                and call.status == "FAILED"
                and "pending" not in r.state
            )
            assert r.state["failures"] == 1
        # Unknown execution is never replayed on resume.
        async with DB.begin() as db:
            r = await db.get(Run, id)
            r.status = "PAUSED"
            call = await db.scalar(select(ToolCall).where(ToolCall.run_id == id))
            call.status = "UNKNOWN"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            login = await client.post(
                "/api/v1/auth/login",
                json={"username": "test-" + user_ids[0], "password": password},
            )
            client.headers["X-CSRF-Token"] = login.json()["csrf"]
            assert (
                await client.post("/api/v1/runs/" + id + "/resume")
            ).status_code == 400
        async with DB.begin() as db:
            row = await db.get(Run, id)
            row.status = "RUNNING"
            row.lease_owner = "test-owner"
            row.lease_until = now() + 15000
            row.state = {**row.state, "deadline": now() - 1}
        with pytest.raises(runtime.StopRun):
            await runtime.controlled(id, "test-owner", asyncio.sleep(2))
        async with DB() as db:
            assert (await db.get(Run, id)).status == "BLOCKED"
    finally:
        async with DB.begin() as db:
            for cls in (Approval, ToolCall, Event):
                await db.execute(delete(cls).where(cls.run_id.in_(run_ids)))
            for cls in (Message, Checkpoint):
                await db.execute(delete(cls).where(cls.session_id.in_(session_ids)))
            await db.execute(delete(Run).where(Run.id.in_(run_ids)))
            await db.execute(delete(Session).where(Session.id.in_(session_ids)))
            for cls in (Memory, Preference, Login):
                await db.execute(delete(cls).where(cls.user_id.in_(user_ids)))
            await db.execute(delete(User).where(User.id.in_(user_ids)))
            await db.execute(delete(Resource).where(Resource.id.in_(resource_ids)))
        await engine.dispose()
