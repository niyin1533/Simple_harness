"""@input Isolated MySQL fixtures, real Redis and mocked model completions.
@output Publication version, credential, principal, replay and execution security regression.
@position Publication integration acceptance. @doc-sync Update INDEX.md on changes.
"""

import json
import asyncio
from types import SimpleNamespace
import httpx
import pytest
from sqlalchemy import select, delete
from app.db import DB, engine, User, Resource, Login, Run, Session, Memory, Message, Event, ToolCall, Approval, Checkpoint, uid, now
from app.publication_models import PublishedApp, PublishedVersion, AppKey, EndUser, AppSession, Invocation, PublicEvent, PublicationAudit, Idempotency
from app.main import app
from app import runtime
from app.security import digest, encrypt
from app.invocation import acting_as
from app.publication import tool_allowed, risk, keyed
from app.config import settings


@pytest.mark.asyncio
async def test_publication_migration_is_idempotent():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).parents[1] / "migrations/versions/0004_publication.py"
    spec = importlib.util.spec_from_file_location("publication_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    def upgrade(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
    async with engine.begin() as connection:
        await connection.run_sync(upgrade)
    await engine.dispose()


def test_tool_publication_intersection_and_scope(tmp_path):
    snap = {"definition": {"permission_preset": "danger-full-access", "workspace_path": str(tmp_path)},
            "publication": {"channel": "WEB_APP", "grants": {"builtin.process.exec": {"commands": [{"executable": "git", "args": ["status"]}]},
            "builtin.fs.read": {}, "builtin.http.fetch": {"hosts": ["learn.microsoft.com"]}}}}
    cap = {"id": "builtin.process.exec", "operation_class": "MUTATE_SCOPED"}
    assert risk(cap) == "HIGH"
    assert not tool_allowed(snap, cap, {"executable": "git", "args": ["status"]})
    snap["publication"]["channel"] = "SERVICE_API"
    assert tool_allowed(snap, cap, {"executable": "git", "args": ["status"]})
    assert not tool_allowed(snap, cap, {"executable": "git", "args": ["clean", "-fd"]})
    cap = {"id": "builtin.fs.read", "operation_class": "READ_SCOPED"}
    assert not tool_allowed(snap, cap, {"path": "../outside.txt"})
    assert tool_allowed(snap, cap, {"path": "inside.txt"})
    cap = {"id": "builtin.http.fetch", "operation_class": "READ_GLOBAL"}
    assert tool_allowed(snap, cap, {"url": "https://learn.microsoft.com/docs"})
    assert not tool_allowed(snap, cap, {"url": "https://learn.microsoft.com.evil.test/docs"})
    snap["definition"]["permission_preset"] = "read-only"
    assert not tool_allowed(snap, cap, {"url": "https://learn.microsoft.com/docs"})


@pytest.mark.asyncio
async def test_publication_lifecycle_and_isolation(monkeypatch, tmp_path):
    owner, model_id, agent_id = uid(), uid(), uid()
    login_token, csrf = uid(), uid()
    app_id = None
    secret = "test-secret-" + uid()

    async def reply(model, messages, **kwargs):
        assert model["secret"] == encrypted
        return {"content": "published-ok", "usage": {}}

    monkeypatch.setattr(runtime, "complete", reply)
    # The user's live Worker must never claim these integration-test runs.
    from app import publication_api
    original_create = publication_api.create_run
    async def create_test_run(*args, **kwargs):
        run = await original_create(*args, **kwargs)
        run.status = "TEST_QUEUED"
        return run
    monkeypatch.setattr(publication_api, "create_run", create_test_run)
    encrypted = encrypt(secret)

    async def finish(id):
        async with DB.begin() as db:
            run = await db.get(Run, id, with_for_update=True)
            run.status, run.lease_owner, run.lease_until = "RUNNING", "publication-test", now() + 30000
            await runtime.event(db, run, "RUN_STARTED")
        await runtime.run_loop(id, "publication-test")

    try:
        async with DB.begin() as db:
            db.add(User(id=owner, username="publication-test-" + owner, password="unused", admin=True))
            db.add(Login(token=digest(login_token), user_id=owner, csrf=csrf, expires=now() + 600000))
            db.add(Resource(id=model_id, kind="model", name="mock model", config={"model": "mock"}, secret=encrypted))
            db.add(Resource(id=agent_id, kind="agent", name="test published agent", config={"model_id": model_id, "loop_enabled": False, "system_prompt": "version-one"}))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:5173", cookies={"agent_session": login_token}, headers={"X-CSRF-Token": csrf}) as console:
            response = await console.post("/api/v1/publications", json={"agent_id": agent_id, "web_enabled": True, "acknowledge_warnings": True})
            assert response.status_code == 200, response.text
            published = response.json(); app_id = published["id"]
            initial_check = (await console.get("/api/v1/publications/check/" + agent_id)).json()
            assert initial_check["saved_grants"] == {} and initial_check["current_version_id"] == published["current_version"]
            token_response = await console.post(f"/api/v1/publications/{app_id}/keys", json={"name": "test"})
            assert token_response.status_code == 200, token_response.text
            key = token_response.json()
            async with DB() as db:
                version = await db.get(PublishedVersion, published["current_version"])
                assert encrypted not in json.dumps(version.snapshot) and secret not in json.dumps(version.snapshot)
                stored_key = await db.get(AppKey, key["id"])
                assert stored_key.digest == keyed(key["key"]) and stored_key.digest != digest(key["key"])
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:5173", headers={"Authorization": "Bearer " + key["key"]}) as client:
                assert (await client.get("/api/v1/resources/agent")).status_code == 401
                body = {"query": "hello", "user": "customer-a"}
                first = await client.post("/service-api/v1/chat-messages", json=body, headers={"Idempotency-Key": "first"})
                assert first.status_code == 202, first.text
                first = first.json()
                await finish(first["run_id"])
                state = await client.get(f"/service-api/v1/runs/{first['run_id']}?user=customer-a")
                assert state.json()["answer"] == "published-ok", state.text
                assert (await client.get(f"/service-api/v1/runs/{first['run_id']}?user=customer-b")).status_code == 404
                assert (await client.get(f"/service-api/v1/runs/{first['run_id']}")).status_code == 400
                replay = await client.post("/service-api/v1/chat-messages", json=body, headers={"Idempotency-Key": "first"})
                assert replay.json()["run_id"] == first["run_id"]
                conflict = await client.post("/service-api/v1/chat-messages", json={**body, "query": "different"}, headers={"Idempotency-Key": "first"})
                assert conflict.status_code == 409
                wrong = await client.post("/service-api/v1/chat-messages", json={**body, "user": "customer-b", "conversation_id": first["conversation_id"]})
                assert wrong.status_code == 404
                events = await client.get(f"/service-api/v1/runs/{first['run_id']}/events?user=customer-a")
                assert "message_completed" in events.text and "version-one" not in events.text
                assert "MODEL_DECISION" not in events.text and encrypted not in events.text
                # Credential rotation resolves at execution without draft/version drift.
                encrypted = encrypt("rotated-" + secret)
                async with DB.begin() as db:
                    model = await db.get(Resource, model_id)
                    model.secret = encrypted
                    model.version += 1
                publication_status = (await console.get("/api/v1/publications")).json()
                assert publication_status[0]["changed"] is False
                async with DB.begin() as db:
                    model = await db.get(Resource, model_id)
                    model.enabled = False
                blocked = await client.post("/service-api/v1/chat-messages", json={**body, "user": "dependency-test"})
                assert blocked.status_code == 409 and blocked.json()["code"] == "DEPENDENCY_UNAVAILABLE"
                async with DB.begin() as db:
                    model = await db.get(Resource, model_id)
                    model.enabled = True
                replay_events = await client.get(f"/service-api/v1/runs/{first['run_id']}/events?user=customer-a", headers={"Last-Event-ID": "2"})
                assert "message_completed" not in replay_events.text and "done" in replay_events.text
                console_sessions = (await console.get("/api/v1/sessions")).json()
                assert first["conversation_id"] not in {s["id"] for s in console_sessions}
                assert (await console.get(f"/api/v1/sessions/{first['conversation_id']}/messages")).status_code == 404
                async with DB.begin() as db:
                    agent = await db.get(Resource, agent_id)
                    agent.config = {**agent.config, "system_prompt": "version-two"}
                    invocation = await db.get(Invocation, first["run_id"])
                    visitor_id = invocation.end_user_id
                    run = await db.get(Run, first["run_id"])
                    assert encrypted not in json.dumps(run.snapshot)
                    db.add(Memory(user_id=owner, content="owner-private", confirmed=True))
                with acting_as(visitor_id):
                    async with DB.begin() as db:
                        db.add(Memory(user_id=owner, content="visitor-private", confirmed=True))
                    async with DB() as db:
                        rows = (await db.scalars(select(Memory).where(Memory.user_id == owner))).all()
                        assert [r.content for r in rows] == ["visitor-private"]
                async with DB() as db:
                    rows = (await db.scalars(select(Memory).where(Memory.user_id == owner))).all()
                    assert [r.content for r in rows] == ["owner-private"]
                second_version = await console.post("/api/v1/publications", json={"agent_id": agent_id, "web_enabled": True, "acknowledge_warnings": True})
                assert second_version.json()["number"] == 2
                old = await client.post("/service-api/v1/chat-messages", json={**body, "conversation_id": first["conversation_id"]})
                assert old.json()["version"] == 1
                await finish(old.json()["run_id"])
                new = await client.post("/service-api/v1/chat-messages", json={**body, "user": "customer-b"})
                assert new.json()["version"] == 2
                await finish(new.json()["run_id"])
                # Serialized durable admission survives concurrent HTTP requests.
                parallel = await asyncio.gather(*[client.post("/service-api/v1/chat-messages", json={**body, "user": "parallel"}, headers={"Idempotency-Key": "parallel-same"}) for _ in range(4)])
                assert all(r.status_code == 202 for r in parallel), [r.text for r in parallel]
                assert len({r.json()["run_id"] for r in parallel}) == 1
                await finish(parallel[0].json()["run_id"])
                concurrent = await asyncio.gather(*[client.post("/service-api/v1/chat-messages", json={**body, "user": "concurrent"}) for _ in range(3)])
                assert sorted(r.status_code for r in concurrent) == [202, 202, 429], [r.text for r in concurrent]
                for r in concurrent:
                    if r.status_code == 202:
                        await finish(r.json()["run_id"])
                with monkeypatch.context() as patch:
                    patch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")
                    failed = await client.post("/service-api/v1/chat-messages", json={**body, "user": "redis-failure"})
                    assert failed.status_code == 503 and failed.json()["code"] == "TRAFFIC_SERVICE_UNAVAILABLE"
                    assert (await console.get("/api/v1/resources/agent")).status_code == 200
                # A deleted run is a tombstone for its idempotency key, never a new invocation.
                assert (await console.delete("/api/v1/runs/" + parallel[0].json()["run_id"])).status_code == 200
                tombstone = await client.post("/service-api/v1/chat-messages", json={**body, "user": "parallel"}, headers={"Idempotency-Key": "parallel-same"})
                assert tombstone.status_code == 410
                # Public Web does not reuse console credentials or caller-supplied API user.
                async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:5173") as web:
                    path = "/public-api/v1/apps/" + published["site_code"]
                    info = await web.get(path)
                    assert info.status_code == 200
                    assert "HttpOnly" in info.headers["set-cookie"] and "SameSite=strict" in info.headers["set-cookie"]
                    assert (await web.post(path + "/chat-messages", json=body)).status_code == 403
                    web.headers.update({"Origin": "http://127.0.0.1:5173", "X-Visitor-CSRF": info.json()["csrf"]})
                    web_run = await web.post(path + "/chat-messages", json=body)
                    assert web_run.status_code == 202, web_run.text
                    await finish(web_run.json()["run_id"])
                    assert (await web.get(path + "/runs/" + first["run_id"])).status_code == 404
                    assert (await web.get(path + "/runs/" + web_run.json()["run_id"])).status_code == 200
                    # History restores UI descriptors, never raw input; compatibility stays publisher-controlled.
                    from app import main as main_module, extensions
                    async def resource_stub(config, uri):
                        assert uri == "ui://cesium-map/mcp-app.html"
                        return {"contents": [{"mimeType": "text/html", "text": "<p>map fixture</p>"}]}
                    captured = []
                    def view_stub(data, body):
                        captured.append(body)
                        return {"url": "http://127.0.0.1:8011/test-only", "mode": "isolated-compatibility" if body["compatibility"] else "isolated-display"}
                    monkeypatch.setattr(extensions, "resource", resource_stub)
                    monkeypatch.setattr(main_module, "create_mcp_view", view_stub)
                    call_id = uid()
                    async with DB.begin() as db:
                        row = await db.get(Run, web_run.json()["run_id"])
                        snap = {**row.snapshot, "capabilities": [{"id": "map-fixture", "name": "Map", "server_id": "test-server", "server": {}, "ui_uri": "ui://cesium-map/mcp-app.html"}]}
                        snap["publication"] = {**snap["publication"], "grants": {"map-fixture": {}}}
                        row.snapshot = snap
                        db.add(ToolCall(id=call_id, run_id=row.id, capability_id="map-fixture", arguments={"label": "private-input"}, result={"data": {}}, status="SUCCEEDED"))
                    history_views = await web.get(path + "/conversations/" + web_run.json()["conversation_id"] + "/views")
                    assert history_views.json()[0]["call_id"] == call_id and "private-input" not in history_views.text
                    view_url = path + "/runs/" + web_run.json()["run_id"] + "/views/" + call_id
                    view_response = await web.post(view_url, json={"compatibility": True})
                    assert view_response.status_code == 200 and view_response.json()["compatibility_allowed"] is False
                    assert captured[-1]["compatibility"] is False
                    async with DB.begin() as db:
                        row = await db.get(Run, web_run.json()["run_id"])
                        row.snapshot = {**row.snapshot, "publication": {**row.snapshot["publication"], "grants": {"map-fixture": {"ui_compatibility": True}}}}
                    view_response = await web.post(view_url)
                    assert view_response.json()["mode"] == "isolated-compatibility" and captured[-1]["compatibility"] is True
                    assert (await web.get(path + "/conversations/" + first["conversation_id"] + "/views")).status_code == 404
                    cleared = await web.delete(path + "/visitor")
                    assert cleared.status_code == 200, cleared.text
                    await web.get(path)
                    assert (await web.get(path + "/conversations")).json() == []
                    assert (await web.get(path + "/runs/" + web_run.json()["run_id"])).status_code == 404
                    assert (await console.get("/api/v1/runs/" + web_run.json()["run_id"])).status_code == 200
                rolled = await console.post(f"/api/v1/publications/{app_id}/versions/{published['current_version']}/activate")
                assert rolled.status_code == 200
                rolled_run = await client.post("/service-api/v1/chat-messages", json={**body, "user": "rollback"})
                assert rolled_run.json()["version"] == 1
                await finish(rolled_run.json()["run_id"])
                async with DB.begin() as db:
                    agent = await db.get(Resource, agent_id)
                    agent.config = {**agent.config, "loop_enabled": True, "workspace_path": str(tmp_path), "permission_preset": "workspace-write"}
                async def tool_reply(model, messages, **kwargs):
                    if any("工具结果" in m["content"] or "工具被发布授权策略拒绝" in m["content"] for m in messages):
                        return {"content": json.dumps({"action": "final", "answer": "checked tool result"}), "usage": {}}
                    return {"content": json.dumps({"action": "tool_call", "toolId": "builtin.fs.write", "arguments": {"path": "public.txt", "content": "granted"}}), "usage": {}}
                monkeypatch.setattr(runtime, "complete", tool_reply)
                allowed_version = await console.post("/api/v1/publications", json={"agent_id": agent_id, "web_enabled": True, "acknowledge_warnings": True, "grants": {"builtin.fs.write": {}}})
                assert allowed_version.status_code == 200, allowed_version.text
                saved_check = (await console.get("/api/v1/publications/check/" + agent_id)).json()
                assert saved_check["saved_grants"] == {"builtin.fs.write": {}}
                allowed_run = await client.post("/service-api/v1/chat-messages", json={**body, "user": "tool-allowed"})
                await finish(allowed_run.json()["run_id"])
                assert (tmp_path / "public.txt").read_text() == "granted"
                async with DB() as db:
                    assert await db.scalar(select(Approval.id).where(Approval.run_id == allowed_run.json()["run_id"])) is None
                await console.post("/api/v1/publications", json={"agent_id": agent_id, "web_enabled": True, "acknowledge_warnings": True})
                denied_run = await client.post("/service-api/v1/chat-messages", json={**body, "user": "tool-denied"})
                await finish(denied_run.json()["run_id"])
                async with DB() as db:
                    denied_call = await db.scalar(select(ToolCall).where(ToolCall.run_id == denied_run.json()["run_id"]))
                    assert denied_call.status == "FAILED" and denied_call.result["code"] == "PUBLICATION_PERMISSION_DENIED"
                    assert await db.scalar(select(Approval.id).where(Approval.run_id == denied_run.json()["run_id"])) is None
                assert (await console.delete("/api/v1/resources/agent/" + agent_id)).status_code == 409
                await console.patch(f"/api/v1/publications/{app_id}", json={"enabled": False, "web_enabled": True, "api_enabled": True})
                assert (await client.post("/service-api/v1/chat-messages", json=body)).status_code == 403
                assert (await client.get(f"/service-api/v1/runs/{first['run_id']}?user=customer-a")).status_code == 200
                await console.delete(f"/api/v1/publications/{app_id}/keys/{key['id']}")
                assert (await client.get(f"/service-api/v1/runs/{first['run_id']}?user=customer-a")).status_code == 401
    finally:
        async with DB.begin() as db:
            runs = list((await db.scalars(select(Invocation.run_id).where(Invocation.app_id == app_id))).all()) if app_id else []
            sessions = list((await db.scalars(select(AppSession.session_id).where(AppSession.app_id == app_id))).all()) if app_id else []
            visitor_ids = list((await db.scalars(select(EndUser.id).where(EndUser.app_id == app_id))).all()) if app_id else []
            for cls in (Event, ToolCall, Approval, PublicEvent, Invocation, Idempotency):
                await db.execute(delete(cls).where(cls.run_id.in_(runs)))
            for cls in (Message, Checkpoint, AppSession):
                await db.execute(delete(cls).where(cls.session_id.in_(sessions)))
            for visitor_id in visitor_ids:
                with acting_as(visitor_id):
                    await db.execute(delete(Memory).where(Memory.user_id == owner))
            for cls in (Run, Session, Memory, Login):
                await db.execute(delete(cls).where(cls.user_id == owner))
            if app_id:
                for cls in (PublishedVersion, AppKey, EndUser, PublicationAudit):
                    await db.execute(delete(cls).where(cls.app_id == app_id))
                await db.execute(delete(PublishedApp).where(PublishedApp.id == app_id))
            await db.execute(delete(Resource).where(Resource.id.in_([agent_id, model_id])))
            await db.execute(delete(User).where(User.id == owner))
        await engine.dispose()
