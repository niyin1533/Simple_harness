"""@input Real MCP transports and independent deployment processes. @output Adapter regression tests.
@position Integration verification. @doc-sync Update INDEX.md on changes.
"""

import asyncio
import os
import subprocess
import sys
import json
from contextlib import asynccontextmanager
from pathlib import Path
import httpx
import pytest
from sqlalchemy import delete
from app import extensions, deployments
from app.db import DB, engine, User, Resource, Deployment, Artifact, uid


@pytest.mark.asyncio
async def test_mcp_initialize_reconnect_without_replaying_tool(monkeypatch):
    attempts, calls = [], []

    class Client:
        async def call_tool(self, *args):
            calls.append(True)
            return type(
                "Result", (), {"model_dump": lambda self, **kw: {"isError": False}}
            )()

    @asynccontextmanager
    async def flaky(config):
        attempts.append(True)
        if len(attempts) < 3:
            raise ExceptionGroup(
                "connect", [httpx.ConnectError("secret must not leak")]
            )
        yield Client()

    monkeypatch.setattr(extensions, "_session", flaky)
    assert await extensions.call({}, "show-map", {}) == {"isError": False}
    assert len(attempts) == 3 and len(calls) == 1


@pytest.mark.asyncio
async def test_mcp_no_replay_after_dispatch(monkeypatch):
    calls = []

    class Client:
        async def call_tool(self, *args):
            calls.append(True)
            raise httpx.ReadError("private endpoint")

    @asynccontextmanager
    async def connected(config):
        yield Client()

    monkeypatch.setattr(extensions, "_session", connected)
    with pytest.raises(extensions.McpTransportError):
        await extensions.call({}, "show-map", {})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_stdio_mcp():
    config = {
        "command": sys.executable,
        "args": [str(Path(__file__).with_name("fixture_mcp.py"))],
    }
    found = await extensions.discover(config)
    assert (
        found[0]["name"] == "echo"
        and found[0]["_meta"]["ui"]["resourceUri"] == "ui://fixture/result"
    )
    result = await extensions.call(config, "echo", {"text": "hello"})
    assert (
        not result["isError"]
        and json.loads(result["content"][0]["text"])["text"] == "hello"
    )
    resource = await extensions.resource(config, "ui://fixture/result")
    assert "Fixture MCP App" in resource["contents"][0]["text"]


@pytest.mark.asyncio
async def test_http_mcp():
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("fixture_mcp.py")), "--http"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(40):
                try:
                    await client.get("http://127.0.0.1:18992/mcp")
                    break
                except httpx.ConnectError:
                    await asyncio.sleep(0.1)
            else:
                pytest.fail("MCP fixture did not start")
        config = {"transport": "streamable-http", "url": "http://127.0.0.1:18992/mcp"}
        assert (await extensions.discover(config))[0]["name"] == "echo"
        result = await extensions.call(config, "echo", {"text": "http"})
        assert (
            not result["isError"]
            and json.loads(result["content"][0]["text"])["text"] == "http"
        )
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.mark.asyncio
async def test_deployment_lifecycle(tmp_path):
    user_id, template_id, deployment_id, artifact_id = uid(), uid(), uid(), uid()
    tool_id = None
    weight = tmp_path / "weight.bin"
    weight.write_bytes(b"test fixture only")
    try:
        async with DB.begin() as db:
            db.add(
                User(
                    id=user_id,
                    username="fixture-" + user_id,
                    password="not-a-login-hash",
                )
            )
            db.add(
                Resource(
                    id=template_id,
                    kind="template",
                    name="fixture",
                    config={
                        "runtime": "custom",
                        "script": str(Path(__file__).with_name("fixture_inference.py")),
                        "python": sys.executable,
                    },
                )
            )
            db.add(
                Artifact(
                    id=artifact_id,
                    user_id=user_id,
                    name="weight",
                    path=str(weight),
                    kind="weight",
                    digest="0" * 64,
                    size=1,
                )
            )
            db.add(
                Deployment(
                    id=deployment_id,
                    user_id=user_id,
                    name="fixture",
                    config={"template_id": template_id, "weight_id": artifact_id},
                    status="QUEUED",
                )
            )
        await deployments.start(deployment_id)
        async with DB.begin() as db:
            row = await db.get(Deployment, deployment_id)
            assert row.status == "RUNNING", row.error
            tool = await deployments.register(db, row)
            tool_id = tool.id
            assert "image_path" in tool.config["input_schema"]["properties"]
            assert tool.config["idempotent"] is False
            port = row.port
        async with httpx.AsyncClient(trust_env=False) as client:
            result = await client.post(
                f"http://127.0.0.1:{port}/detect", json={"image_path": str(weight)}
            )
            assert result.json()["input_exists"]
        async with DB.begin() as db:
            row = await db.get(Deployment, deployment_id)
            await deployments.stop(row)
            assert row.status == "STOPPED"
    finally:
        async with DB.begin() as db:
            row = await db.get(Deployment, deployment_id)
            if row:
                await deployments.stop(row)
            if tool_id:
                await db.execute(delete(Resource).where(Resource.id == tool_id))
            await db.execute(delete(Deployment).where(Deployment.id == deployment_id))
            await db.execute(delete(Artifact).where(Artifact.id == artifact_id))
            await db.execute(delete(Resource).where(Resource.id == template_id))
            await db.execute(delete(User).where(User.id == user_id))
        await engine.dispose()
