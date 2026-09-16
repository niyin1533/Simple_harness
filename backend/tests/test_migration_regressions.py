"""@input Real MySQL API and isolated MCP view tickets; no live model calls.
@output Regression checks for migrated resource creation, approval recovery and CSP.
@position Migration regression suite. @doc-sync Update tests/INDEX.md on changes.
"""

import json
import httpx
import pytest
from sqlalchemy import delete
from app import main, app_host
from app.config import settings
from app.db import (
    DB,
    engine,
    User,
    Resource,
    AgentVersion,
    Run,
    ToolCall,
    Approval,
    Event,
    Login,
    uid,
    now,
)
from app.security import hasher
from app import governance
from app import extensions
from app.db import Memory, Deployment
from types import SimpleNamespace


@pytest.mark.asyncio
async def test_create_agent_api_and_resume_approval():
    user_id, model_id, run_id, call_id, approval_id = [uid() for _ in range(5)]
    agent_id = None
    mcp_id = uid()
    password = uid()
    username = "migration-" + user_id
    try:
        async with DB.begin() as db:
            db.add(
                User(
                    id=user_id,
                    username=username,
                    password=hasher.hash(password),
                    admin=True,
                )
            )
            db.add(
                Resource(
                    id=model_id,
                    kind="model",
                    name="Migration fixture",
                    config={"model": "fixture"},
                )
            )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://test"
        ) as client:
            login = await client.post(
                "/api/v1/auth/login", json={"username": username, "password": password}
            )
            assert login.status_code == 200, login.text
            client.headers["X-CSRF-Token"] = login.json()["csrf"]
            mcp = await client.post(
                "/api/v1/resources/mcp",
                json={
                    "id": mcp_id,
                    "name": "Microsoft Learn fixture",
                    "enabled": False,
                    "config": {
                        "mcpServers": {
                            "microsoft-learn": {
                                "transport": "streamable-http",
                                "url": "https://learn.microsoft.com/api/mcp?maxTokenBudget=2000",
                            }
                        }
                    },
                },
            )
            assert mcp.status_code == 200, mcp.text
            assert mcp.json()["config"]["url"].startswith(
                "https://learn.microsoft.com/"
            )
            assert "mcpServers" not in mcp.json()["config"]
            response = await client.post(
                "/api/v1/resources/agent",
                json={
                    "name": "Migration agent",
                    "config": {"model_id": model_id, "system_prompt": "test"},
                },
            )
            assert response.status_code == 200, response.text
            agent = response.json()
            agent_id = agent["id"]
            assert agent["name"] == "Migration agent" and agent["version"] == 1
            response = await client.put(
                "/api/v1/resources/agent/" + agent_id,
                json={"name": "Renamed", "version": 1, "config": agent["config"]},
            )
            assert response.status_code == 200 and response.json()["version"] == 2
            stale = await client.put(
                "/api/v1/resources/agent/" + agent_id,
                json={"name": "stale", "version": 1, "config": agent["config"]},
            )
            assert stale.status_code == 409
            async with DB.begin() as db:
                db.add(
                    Run(
                        id=run_id,
                        user_id=user_id,
                        session_id=uid(),
                        agent_id=agent_id,
                        task="fixture",
                        snapshot={},
                        status="PAUSED",
                        state={
                            "deadline": now() + 60000,
                            "suspended_at": now(),
                            "pending": {"call_id": call_id},
                        },
                    )
                )
                db.add(
                    ToolCall(
                        id=call_id,
                        run_id=run_id,
                        capability_id="builtin.fs.write",
                        arguments={},
                    )
                )
                db.add(
                    Approval(
                        id=approval_id,
                        run_id=run_id,
                        call_id=call_id,
                        request_hash="fixture",
                    )
                )
            response = await client.post("/api/v1/runs/" + run_id + "/resume")
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "WAITING_APPROVAL"
            # Reject: never queue a test run for the user's running worker.
            rejected = await client.post(
                "/api/v1/approvals/" + approval_id, json={"approved": False}
            )
            assert rejected.status_code == 200
    finally:
        async with DB.begin() as db:
            for cls, condition in [
                (Event, Event.run_id == run_id),
                (Approval, Approval.id == approval_id),
                (ToolCall, ToolCall.id == call_id),
                (Run, Run.id == run_id),
                (AgentVersion, AgentVersion.agent_id == agent_id),
                (Resource, Resource.id.in_([model_id, agent_id or "", mcp_id])),
                (Login, Login.user_id == user_id),
                (User, User.id == user_id),
            ]:
                await db.execute(delete(cls).where(condition))
        await engine.dispose()


@pytest.mark.asyncio
async def test_mcp_csp_compatibility_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    async def resource(*args):
        return {
            "contents": [
                {
                    "mimeType": "text/html",
                    "text": '<html><body><script src="https://cesium.com/downloads/cesiumjs/releases/1.123/Build/Cesium/Cesium.js"></script></body></html>',
                    "_meta": {
                        "ui": {
                            "csp": {
                                "resourceDomains": [
                                    "https://cesium.com",
                                    "https://*.cesium.com",
                                    "https://evil.test; script-src *",
                                ],
                                "connectDomains": ["https://*.openstreetmap.org"],
                            }
                        }
                    },
                }
            ]
        }

    monkeypatch.setattr(main, "mcp_resource", resource)
    for compatible in [False, True]:
        result = await main.mcp_view(
            "fixture", {"uri": "ui://test", "compatibility": compatible}, object()
        )
        ticket = result["url"].rsplit("/", 1)[1]
        stored = json.loads(
            (tmp_path / "app-views" / (ticket + ".json")).read_text(encoding="utf-8")
        )
        assert stored["resource_domains"] == [
            "https://cesium.com",
            "https://*.cesium.com",
        ]
        response = await app_host.view(ticket)
        csp = response.headers["content-security-policy"]
        assert "https://cesium.com" in csp and "https://*.openstreetmap.org" in csp
        assert ("unsafe-eval" in csp) == compatible
        assert ("allow-same-origin" in response.body.decode()) == compatible
        assert "worker-src blob:" in csp
        if compatible:
            assert "/Cesium/Cesium.js" in response.body.decode()
            assert "CompatibleWorker" in response.body.decode()


@pytest.mark.asyncio
async def test_unconfirmed_memory_is_not_retrieved():
    user_id = uid()
    try:
        async with DB.begin() as db:
            db.add_all(
                [
                    Memory(user_id=user_id, content="pending", confirmed=False),
                    Memory(user_id=user_id, content="confirmed", confirmed=True),
                ]
            )
        async with DB() as db:
            results = await governance.retrieve(db, user_id, None, "memory", ["user"])
            assert [r["content"] for r in results] == ["confirmed"]
    finally:
        async with DB.begin() as db:
            await db.execute(delete(Memory).where(Memory.user_id == user_id))
        await engine.dispose()


@pytest.mark.asyncio
async def test_pending_deployment_stop_does_not_grant_approval():
    user = SimpleNamespace(id=uid(), admin=False)
    deployment_id = uid()
    try:
        async with DB.begin() as db:
            db.add(
                Deployment(
                    id=deployment_id,
                    user_id=user.id,
                    name="migration approval fixture",
                    status="PENDING",
                    config={"template_id": "nonexistent-test-only"},
                )
            )
        await main.deployment_action(deployment_id, "stop", {}, user)
        with pytest.raises(ValueError, match="审核"):
            await main.deployment_action(deployment_id, "start", {}, user)
    finally:
        async with DB.begin() as db:
            await db.execute(delete(Deployment).where(Deployment.id == deployment_id))
        await engine.dispose()


@pytest.mark.asyncio
async def test_mcp_read_retries_exception_group(monkeypatch):
    attempts = []

    async def flaky(*args):
        attempts.append(1)
        if len(attempts) < 2:
            raise ExceptionGroup(
                "SDK task group", [httpx.ConnectError("private transport diagnostic")]
            )
        return {"contents": []}

    monkeypatch.setattr(extensions, "_resource", flaky)
    assert await extensions.resource({}, "ui://test") == {"contents": []}
    assert len(attempts) == 2


@pytest.mark.asyncio
async def test_mcp_mutation_not_replayed_and_error_is_sanitized(monkeypatch):
    attempts = []

    async def failed(*args):
        attempts.append(1)
        raise ExceptionGroup(
            "SDK task group", [httpx.ConnectError("secret diagnostic")]
        )

    monkeypatch.setattr(extensions, "_call", failed)
    with pytest.raises(extensions.McpTransportError) as error:
        await extensions.call({}, "write", {})
    assert len(attempts) == 1 and "secret diagnostic" not in str(error.value)
    assert (await main.mcp_unavailable(None, error.value)).status_code == 502
