"""@input Authenticated REST commands. @output Agent platform API, durable SSE and owner-scoped terminal task cleanup.
@position HTTP application. @doc-sync Update header and INDEX.md on changes.
"""

import asyncio
import hashlib
import json
import secrets
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from argon2.exceptions import VerificationError
from .config import settings
from .db import (
    DB,
    User,
    Login,
    Resource,
    AgentVersion,
    Session,
    Message,
    Run,
    Event,
    ToolCall,
    Approval,
    Memory,
    Preference,
    Artifact,
    Deployment,
    Schedule,
    Checkpoint,
    public,
    uid,
    now,
)
from .security import current_user, administrator, hasher, digest, encrypt
from .runtime import create_run, event, DEFAULT_LIMITS
from .providers import complete, embedding
from . import governance, extensions, deployments
from .scheduling import next_time

app = FastAPI(title="Agent Harness", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(extensions.McpTransportError)
async def mcp_unavailable(request, exc):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


@app.get("/api/v1/health")
async def health():
    async with DB() as db:
        await db.execute(select(1))
    return {"status": "ok"}


@app.post("/api/v1/auth/login")
async def login(body: Credentials, response: Response):
    async with DB.begin() as db:
        user = await db.scalar(select(User).where(User.username == body.username))
        try:
            if (
                not user
                or not user.active
                or not hasher.verify(user.password, body.password)
            ):
                raise ValueError()
        except (VerificationError, ValueError):
            raise HTTPException(401, "用户名或密码错误")
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        db.add(
            Login(
                token=digest(token),
                user_id=user.id,
                csrf=csrf,
                expires=now() + settings.session_hours * 3600000,
            )
        )
        response.set_cookie(
            "agent_session",
            token,
            httponly=True,
            secure=settings.secure_cookie,
            samesite="lax",
            max_age=settings.session_hours * 3600,
            path="/",
        )
        return {"user": public(user), "csrf": csrf}


@app.get("/api/v1/auth/me")
async def me(request: Request, user=Depends(current_user)):
    async with DB() as db:
        login = await db.get(Login, digest(request.cookies["agent_session"]))
        return {"user": public(user), "csrf": login.csrf}


@app.post("/api/v1/auth/logout")
async def logout(request: Request, response: Response, user=Depends(current_user)):
    async with DB.begin() as db:
        await db.execute(
            delete(Login).where(
                Login.token == digest(request.cookies.get("agent_session", ""))
            )
        )
    response.delete_cookie("agent_session")
    return {"ok": True}


@app.get("/api/v1/users")
async def users(user=Depends(administrator)):
    async with DB() as db:
        return [public(u) for u in (await db.scalars(select(User))).all()]


@app.post("/api/v1/users")
async def add_user(body: dict, user=Depends(administrator)):
    if len(body.get("password", "")) < 10:
        raise ValueError("密码至少 10 字符")
    async with DB.begin() as db:
        if await db.scalar(select(User).where(User.username == body["username"])):
            raise ValueError("用户名已存在")
        row = User(
            username=body["username"],
            password=hasher.hash(body["password"]),
            admin=bool(body.get("admin")),
        )
        db.add(row)
        await db.flush()
        return public(row)


@app.put("/api/v1/users/{id}")
async def change_user(id: str, body: dict, user=Depends(administrator)):
    async with DB.begin() as db:
        row = await db.get(User, id)
        if not row:
            raise HTTPException(404, "用户不存在")
        if id == user.id and (
            body.get("active") is False or body.get("admin") is False
        ):
            raise ValueError("不能停用自己或移除自己的管理员权限")
        if "active" in body:
            row.active = bool(body["active"])
        if "admin" in body:
            row.admin = bool(body["admin"])
        if body.get("password"):
            if len(body["password"]) < 10:
                raise ValueError("密码至少 10 字符")
            row.password = hasher.hash(body["password"])
            await db.execute(delete(Login).where(Login.user_id == id))
        return public(row)


KINDS = {
    "model",
    "knowledge",
    "prompt",
    "skill",
    "tool",
    "agent",
    "mcp",
    "plugin",
    "template",
}


class ResourceInput(BaseModel):
    id: str | None = Field(default=None, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=16384)
    content: str = Field(default="", max_length=1000000)
    config: dict = Field(default_factory=dict)
    enabled: bool = True
    api_key: str | None = None
    version: int | None = None


def resource_public(row):
    value = public(row)
    value["has_secret"] = bool(row.secret)
    return value


@app.get("/api/v1/resources/{kind}")
async def resources(kind: str, user=Depends(current_user)):
    if kind not in KINDS:
        raise HTTPException(404, "资源类型不存在")
    async with DB() as db:
        rows = (
            await db.scalars(
                select(Resource)
                .where(Resource.kind == kind)
                .order_by(Resource.updated.desc())
            )
        ).all()
        result = []
        for row in rows:
            value = resource_public(row)
            if not user.admin:
                if kind in {"mcp", "plugin", "template"}:
                    value["config"] = {}
                elif kind == "model":
                    value["config"] = {
                        k: v for k, v in value["config"].items() if k not in {"headers"}
                    }
            result.append(value)
        return result


async def save_resource(kind, body, user, id=None):
    if kind not in KINDS - {"plugin"}:
        raise ValueError("不支持此资源类型")
    config = dict(body.config)
    if kind in {"model", "tool", "template"} and any(
        k.lower() in {"api_key", "secret", "password", "authorization"} for k in config
    ):
        raise ValueError("凭据请填写独立密钥字段，不要放入公开配置 JSON")
    if kind == "model":
        from urllib.parse import urlparse

        url = urlparse(config.get("endpoint", ""))
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
        ):
            raise ValueError("模型 API 地址无效")
        if not config.get("model"):
            raise ValueError("需要模型标识")
        window = int(config.get("context_window", 32768))
        output = int(config.get("max_output_tokens", 2048))
        if not 1024 <= window <= 1000000 or not 1 <= output < window:
            raise ValueError("上下文容量和输出预算不合法")
    if kind == "agent":
        if not config.get("model_id") or not config.get("system_prompt", "").strip():
            raise ValueError("需要基础模型和系统提示词")
        if config.get("permission_preset", "workspace-write") not in {
            "read-only",
            "workspace-write",
            "danger-full-access",
        }:
            raise ValueError("权限预设无效")
        path = config.get("workspace_path", "").strip()
        if path:
            p = Path(path)
            if not p.is_absolute() or not p.is_dir():
                raise ValueError("工作目录必须是已存在的绝对目录")
            p = p.resolve()
            if p.parent == p or any(
                x.lower() in {"windows", "program files", "programdata"}
                for x in p.parts
            ):
                raise ValueError("不可使用系统目录")
            config["workspace_path"] = str(p)
        bounds = {
            "max_steps": (1, 50),
            "max_tool_calls": (1, 100),
            "max_run_seconds": (30, 3600),
            "max_consecutive_failures": (1, 5),
            "model_retries": (0, 3),
            "tool_retries": (0, 2),
        }
        limits = {**DEFAULT_LIMITS, **config.get("limits", {})}
        for key, (lo, hi) in bounds.items():
            if not lo <= int(limits[key]) <= hi:
                raise ValueError(key + " 超出范围")
        config["limits"] = limits
    if kind == "mcp":
        config = extensions.validate_server(config)
    if kind == "tool":
        if config.get("source", "http") == "http" and (
            not config.get("endpoint", "").startswith(("http://", "https://"))
            or not config.get("path", "").startswith("/")
        ):
            raise ValueError("工具需要固定 HTTP 地址和接口路径")
    async with DB.begin() as db:
        # Validate references before adding an incomplete pending Resource: queries autoflush.
        if kind == "agent":
            model = await db.get(Resource, config["model_id"])
            if not model or model.kind != "model" or not model.enabled:
                raise ValueError("基础模型不可用")
        row = await db.get(Resource, id, with_for_update=True) if id else None
        if id and (not row or row.kind != kind):
            raise HTTPException(404, "资源不存在")
        if not id:
            id = body.id or uid()
            if await db.get(Resource, id):
                raise ValueError("ID 已存在")
            row = Resource(id=id, kind=kind, version=0)
            db.add(row)
        elif body.version is not None and body.version != row.version:
            raise HTTPException(409, "资源已被修改，请刷新")
        row.name = body.name
        row.description = body.description
        row.content = body.content
        row.config = config
        row.enabled = body.enabled
        row.version += 1
        row.updated = now()
        if body.api_key is not None:
            row.secret = encrypt(body.api_key)
        if kind == "agent":
            db.add(AgentVersion(agent_id=id, version=row.version, snapshot=config))
        await db.flush()
        return resource_public(row)


@app.post("/api/v1/resources/{kind}")
async def new_resource(kind: str, body: ResourceInput, user=Depends(administrator)):
    return await save_resource(kind, body, user)


@app.put("/api/v1/resources/{kind}/{id}")
async def edit_resource(
    kind: str, id: str, body: ResourceInput, user=Depends(administrator)
):
    return await save_resource(kind, body, user, id)


@app.delete("/api/v1/resources/{kind}/{id}")
async def remove_resource(kind: str, id: str, user=Depends(administrator)):
    async with DB.begin() as db:
        row = await db.get(Resource, id)
        if not row or row.kind != kind:
            raise HTTPException(404, "资源不存在")
        children = list(
            (await db.scalars(select(Resource).where(Resource.parent_id == id))).all()
        )
        for child in children:
            await db.execute(delete(Resource).where(Resource.parent_id == child.id))
            await db.delete(child)
        await db.delete(row)
    return {"ok": True}


@app.post("/api/v1/models/{id}/test")
async def test_model(id: str, user=Depends(administrator)):
    async with DB() as db:
        row = await db.get(Resource, id)
        if not row or row.kind != "model":
            raise ValueError("模型不存在")
        return await complete(
            {**public(row), "secret": row.secret},
            [{"role": "user", "content": "请回复：连接成功"}],
        )


class RunInput(BaseModel):
    target_id: str
    task: str = Field(min_length=1, max_length=100000)
    session_id: str | None = None
    target_type: Literal["agent", "model"] = "agent"


@app.post("/api/v1/runs")
async def new_run(body: RunInput, user=Depends(current_user)):
    async with DB.begin() as db:
        run = await create_run(db, user.id, **body.model_dump())
        return {"id": run.id, "session_id": run.session_id}


def run_public(row):
    value = public(row)
    value.pop("snapshot", None)
    value.pop("state", None)
    value["agent_name"] = row.snapshot.get("agent_name")
    value["step"] = row.state.get("step", 0)
    return value


async def owned(db, cls, id, user):
    row = await db.get(cls, id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "记录不存在")
    return row


@app.get("/api/v1/runs")
async def runs(user=Depends(current_user)):
    async with DB() as db:
        return [
            run_public(r)
            for r in (
                await db.scalars(
                    select(Run)
                    .where(Run.user_id == user.id)
                    .order_by(Run.created.desc())
                    .limit(200)
                )
            ).all()
        ]


@app.get("/api/v1/runs/{id}")
async def run_detail(id: str, user=Depends(current_user)):
    async with DB() as db:
        row = await owned(db, Run, id, user)
        return {
            "run": run_public(row),
            "calls": [
                public(c)
                for c in (
                    await db.scalars(select(ToolCall).where(ToolCall.run_id == id))
                ).all()
            ],
            "approvals": [
                public(a)
                for a in (
                    await db.scalars(select(Approval).where(Approval.run_id == id))
                ).all()
            ],
        }


class RunDeleteInput(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)


async def delete_run_records(ids, user):
    ids = sorted(set(ids))
    async with DB.begin() as db:
        rows = list(
            (
                await db.scalars(
                    select(Run)
                    .where(Run.id.in_(ids))
                    .order_by(Run.id)
                    .with_for_update()
                )
            ).all()
        )
        if len(rows) != len(ids) or any(r.user_id != user.id for r in rows):
            raise HTTPException(404, "任务不存在")
        if any(
            r.status not in {"SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED"}
            for r in rows
        ):
            raise HTTPException(409, "请先取消未结束的任务，再删除记录")
        for cls in (Approval, ToolCall, Event):
            await db.execute(delete(cls).where(cls.run_id.in_(ids)))
        schedules = (
            await db.scalars(
                select(Schedule).where(
                    Schedule.user_id == user.id, Schedule.last_run.in_(ids)
                )
            )
        ).all()
        for schedule in schedules:
            schedule.last_run = None
        await db.execute(delete(Run).where(Run.id.in_(ids)))
    return {"deleted": len(ids)}


@app.post("/api/v1/runs/batch-delete")
async def delete_runs(body: RunDeleteInput, user=Depends(current_user)):
    return await delete_run_records(body.ids, user)


@app.delete("/api/v1/runs/{id}")
async def delete_run(id: str, user=Depends(current_user)):
    return await delete_run_records([id], user)


@app.get("/api/v1/runs/{id}/events")
async def events(id: str, after: int = 0, user=Depends(current_user)):
    async with DB() as db:
        await owned(db, Run, id, user)
        return [
            public(e)
            for e in (
                await db.scalars(
                    select(Event)
                    .where(Event.run_id == id, Event.seq > after)
                    .order_by(Event.seq)
                    .limit(1000)
                )
            ).all()
        ]


@app.get("/api/v1/runs/{id}/stream")
async def stream(id: str, request: Request, after: int = 0, user=Depends(current_user)):
    async with DB() as db:
        await owned(db, Run, id, user)

    async def generate():
        cursor = max(after, int(request.headers.get("last-event-id", "0")))
        heartbeat = now()
        while not await request.is_disconnected():
            async with DB() as db:
                rows = (
                    await db.scalars(
                        select(Event)
                        .where(Event.run_id == id, Event.seq > cursor)
                        .order_by(Event.seq)
                        .limit(200)
                    )
                ).all()
            for row in rows:
                cursor = row.seq
                yield f"id: {row.seq}\nevent: agent-run\ndata: {json.dumps(public(row), ensure_ascii=False)}\n\n"
            if now() - heartbeat > 15000:
                yield ": heartbeat\n\n"
                heartbeat = now()
            await asyncio.sleep(0.5)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/v1/runs/{id}/{action}")
async def control(
    id: str, action: Literal["pause", "resume", "cancel"], user=Depends(current_user)
):
    async with DB.begin() as db:
        await owned(db, Run, id, user)
        row = await db.get(Run, id, with_for_update=True)
        if action == "pause":
            if row.status not in {"QUEUED", "RUNNING", "WAITING_APPROVAL"}:
                raise ValueError("当前状态不可暂停")
            row.status = "PAUSE_REQUESTED" if row.status == "RUNNING" else "PAUSED"
            if row.status == "PAUSED" and row.state:
                row.state = {
                    **row.state,
                    "suspended_at": row.state.get("suspended_at", now()),
                }
        elif action == "cancel":
            if row.status in {"SUCCEEDED", "CANCELLED"}:
                raise ValueError("任务已结束")
            row.status = "CANCEL_REQUESTED" if row.status == "RUNNING" else "CANCELLED"
            for a in (
                await db.scalars(
                    select(Approval).where(
                        Approval.run_id == id, Approval.status == "PENDING"
                    )
                )
            ).all():
                a.status = "CANCELLED"
        else:
            if row.status not in {"PAUSED", "FAILED", "BLOCKED"}:
                raise ValueError("当前状态不可恢复")
            unknown = await db.scalar(
                select(ToolCall).where(
                    ToolCall.run_id == id, ToolCall.status == "UNKNOWN"
                )
            )
            if unknown:
                raise ValueError(
                    "存在执行结果未知的工具，请核查后取消任务；不会自动重放"
                )
            row.status = "QUEUED"
            row.error = ""
            pending_approval = await db.scalar(
                select(Approval.id)
                .where(Approval.run_id == id, Approval.status == "PENDING")
                .limit(1)
            )
            if pending_approval:
                row.status = "WAITING_APPROVAL"
            if row.status == "QUEUED" and row.state.get("suspended_at"):
                state = dict(row.state)
                state["deadline"] += now() - state.pop("suspended_at")
                row.state = state
        await event(db, row, "RUN_" + action.upper())
        return run_public(row)


@app.post("/api/v1/approvals/{id}")
async def approve(id: str, body: dict, user=Depends(current_user)):
    async with DB.begin() as db:
        approval = await db.get(Approval, id)
        if not approval:
            raise HTTPException(404, "审批不存在")
        await owned(db, Run, approval.run_id, user)
        run = await db.get(Run, approval.run_id, with_for_update=True)
        approval = await db.get(
            Approval, id, with_for_update=True, populate_existing=True
        )
        if approval.status != "PENDING" or run.status != "WAITING_APPROVAL":
            raise ValueError("审批已经处理或任务不在等待审批")
        approval.status = "APPROVED" if body.get("approved") is True else "REJECTED"
        run.status = "QUEUED" if approval.status == "APPROVED" else "BLOCKED"
        if approval.status == "APPROVED" and run.state.get("suspended_at"):
            state = dict(run.state)
            state["deadline"] += now() - state.pop("suspended_at")
            run.state = state
        await event(db, run, "APPROVAL_" + approval.status, {"approval_id": id})
    return {"ok": True}


@app.get("/api/v1/sessions")
async def sessions(user=Depends(current_user)):
    async with DB() as db:
        return [
            public(r)
            for r in (
                await db.scalars(
                    select(Session)
                    .where(Session.user_id == user.id)
                    .order_by(Session.created.desc())
                )
            ).all()
        ]


@app.get("/api/v1/sessions/{id}/messages")
async def messages(id: str, user=Depends(current_user)):
    async with DB() as db:
        await owned(db, Session, id, user)
        return {
            "messages": [
                public(r)
                for r in (
                    await db.scalars(
                        select(Message)
                        .where(Message.session_id == id)
                        .order_by(Message.id)
                    )
                ).all()
            ],
            "checkpoints": [
                public(r)
                for r in (
                    await db.scalars(
                        select(Checkpoint).where(Checkpoint.session_id == id)
                    )
                ).all()
            ],
        }


@app.delete("/api/v1/sessions/{id}")
async def clear_session(id: str, user=Depends(current_user)):
    async with DB.begin() as db:
        row = await owned(db, Session, id, user)
        if await db.scalar(
            select(Run.id).where(
                Run.session_id == id,
                Run.status.not_in(["SUCCEEDED", "FAILED", "CANCELLED"]),
            )
        ):
            raise ValueError("请先取消未完成任务")
        await db.execute(delete(Message).where(Message.session_id == id))
        await db.execute(delete(Checkpoint).where(Checkpoint.session_id == id))
        await db.delete(row)
    return {"ok": True}


@app.post("/api/v1/sessions/{id}/compact")
async def compact_session(id: str, user=Depends(current_user)):
    async with DB.begin() as db:
        session = await owned(db, Session, id, user)
        target = await db.get(Resource, session.target_id)
        if not target:
            raise ValueError("会话目标已删除")
        model = (
            target
            if session.target_type == "model"
            else await db.get(Resource, target.config["model_id"])
        )
        return await governance.compact(
            db, id, {**public(model), "secret": model.secret}
        )


@app.get("/api/v1/memories")
async def memories(user=Depends(current_user)):
    async with DB() as db:
        return [
            public(r)
            for r in (
                await db.scalars(
                    select(Memory)
                    .where(Memory.user_id == user.id)
                    .order_by(Memory.updated.desc())
                )
            ).all()
        ]


@app.post("/api/v1/memories")
async def memory_save(body: dict, user=Depends(current_user)):
    async with DB.begin() as db:
        return await governance.manage(db, user.id, body.get("agent_id"), body)


@app.put("/api/v1/memories/{id}")
async def memory_edit(id: str, body: dict, user=Depends(current_user)):
    async with DB.begin() as db:
        row = await owned(db, Memory, id, user)
        if "content" in body:
            await governance.manage(
                db,
                user.id,
                row.agent_id,
                {
                    "operation": "update",
                    "id": id,
                    "content": body["content"],
                    "type": body.get("type", (row.meta or {}).get("type", "fact")),
                },
            )
        if "enabled" in body:
            row.enabled = bool(body["enabled"])
        if "confirmed" in body:
            row.confirmed = bool(body["confirmed"])
        return public(row)


@app.delete("/api/v1/memories/{id}")
async def memory_delete(id: str, user=Depends(current_user)):
    async with DB.begin() as db:
        await db.delete(await owned(db, Memory, id, user))
    return {"ok": True}


@app.get("/api/v1/preferences")
async def preferences(user=Depends(current_user)):
    async with DB() as db:
        row = await db.get(Preference, user.id)
        return {
            "config": row.config if row else {},
            "has_secret": bool(row and row.secret),
        }


@app.put("/api/v1/preferences")
async def set_preferences(body: dict, user=Depends(current_user)):
    async with DB.begin() as db:
        row = await db.get(Preference, user.id)
        if not row:
            row = Preference(user_id=user.id)
            db.add(row)
        row.config = body.get("config", {})
        if body.get("api_key") is not None:
            row.secret = encrypt(body["api_key"])
    return {"ok": True}


@app.post("/api/v1/memories/reindex")
async def reindex(user=Depends(current_user)):
    async with DB.begin() as db:
        pref = await db.get(Preference, user.id)
        if not pref:
            raise ValueError("请配置 Embedding")
        rows = (await db.scalars(select(Memory).where(Memory.user_id == user.id))).all()
        for row in rows:
            row.vector = await embedding(pref.config, row.content, pref.secret)
        return {"count": len(rows)}


@app.post("/api/v1/memories/review")
async def review(user=Depends(current_user)):
    from .memory_governance import review as review_memories

    async with DB() as db:
        return await review_memories(db, user.id)


@app.post("/api/v1/uploads/{kind}")
async def upload(
    kind: Literal["weight", "attachment", "script"],
    file: UploadFile = File(...),
    user=Depends(current_user),
):
    if kind == "script" and not user.admin:
        raise HTTPException(403, "脚本上传需要管理员")
    name = Path(file.filename or "upload").name
    if kind == "script" and not name.endswith(".py"):
        raise ValueError("脚本需为 .py 文件")
    id = uid()
    directory = settings.data_dir / "uploads" / user.id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (id + Path(name).suffix)
    size = 0
    sha = hashlib.sha256()
    try:
        with path.open("wb") as output:
            while data := await file.read(1024 * 1024):
                size += len(data)
                if size > settings.upload_limit_mb * 1024 * 1024:
                    raise ValueError("上传超过限制")
                output.write(data)
                sha.update(data)
        async with DB.begin() as db:
            row = Artifact(
                id=id,
                user_id=user.id,
                name=name,
                path=str(path),
                kind=kind,
                digest=sha.hexdigest(),
                size=size,
            )
            db.add(row)
            await db.flush()
            return public(row)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


@app.get("/api/v1/artifacts")
async def artifacts(user=Depends(current_user)):
    async with DB() as db:
        return [
            public(r)
            for r in (
                await db.scalars(select(Artifact).where(Artifact.user_id == user.id))
            ).all()
        ]


@app.get("/api/v1/artifacts/{id}/file")
async def download(id: str, user=Depends(current_user)):
    async with DB() as db:
        row = await owned(db, Artifact, id, user)
    return FileResponse(row.path, filename=row.name)


@app.get("/api/v1/deployments")
async def deployment_list(user=Depends(current_user)):
    async with DB() as db:
        query = select(Deployment)
        if not user.admin:
            query = query.where(Deployment.user_id == user.id)
        return [public(r) for r in (await db.scalars(query)).all()]


@app.post("/api/v1/deployments")
async def deploy(body: dict, user=Depends(current_user)):
    async with DB.begin() as db:
        template = await db.get(Resource, body.get("template_id"))
        if not template or template.kind != "template" or not template.enabled:
            raise ValueError("推理模板不可用")
        if body.get("weight_id"):
            await owned(db, Artifact, body["weight_id"], user)
        row = Deployment(
            user_id=user.id,
            name=body.get("name", "新工具"),
            config={**body, "approved": bool(user.admin)},
            status="QUEUED" if user.admin else "PENDING",
        )
        db.add(row)
        await db.flush()
        return public(row)


@app.post("/api/v1/deployments/{id}/{action}")
async def deployment_action(
    id: str,
    action: Literal["approve", "start", "stop", "register", "test", "skill"],
    body: dict,
    user=Depends(current_user),
):
    async with DB.begin() as db:
        row = await db.get(Deployment, id, with_for_update=True)
        if not row or (row.user_id != user.id and not user.admin):
            raise HTTPException(404, "部署不存在")
        if action in {"approve", "register", "skill"} and not user.admin:
            raise HTTPException(403, "需要管理员")
        if action in {"approve", "start"}:
            if not user.admin and not row.config.get("approved"):
                raise ValueError("部署等待管理员审核")
            if row.status in {"STARTING", "RUNNING", "QUEUED"}:
                raise ValueError("部署已运行或正在启动")
            row.status = "QUEUED"
            row.error = ""
            if user.admin:
                row.config = {**row.config, "approved": True}
        elif action == "stop":
            await deployments.stop(row)
            for tool in (
                await db.scalars(select(Resource).where(Resource.parent_id == id))
            ).all():
                tool.enabled = False
        elif action == "register":
            return public(
                await deployments.register(db, row, body.get("path", "/detect"))
            )
        elif action == "test":
            if row.status != "RUNNING":
                raise ValueError("部署尚未运行")
            import httpx

            args = body.get("arguments", {})
            if body.get("artifact_id"):
                artifact = await owned(db, Artifact, body["artifact_id"], user)
                args = {**args, "image_path": artifact.path}
            async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
                result = await client.post(
                    f"http://127.0.0.1:{row.port}" + body.get("path", "/detect"),
                    json=args,
                )
                result.raise_for_status()
                value = result.json()
            output = (
                value.get("annotated_image_path")
                or value.get("audio_path")
                or value.get("image_path")
            )
            if output:
                path = Path(output).resolve()
                base = (settings.data_dir / "deployments" / id).resolve()
                if path.is_file() and path.is_relative_to(base):
                    artifact = Artifact(
                        id=uid(),
                        user_id=user.id,
                        name=path.name,
                        path=str(path),
                        kind="output",
                        size=path.stat().st_size,
                        digest=hashlib.sha256(path.read_bytes()).hexdigest(),
                    )
                    db.add(artifact)
                    value["artifact_id"] = artifact.id
            return value
        else:
            model = await db.get(Resource, body.get("model_id"))
            if not model or model.kind != "model":
                raise ValueError("请选择生成 Skill 的模型")
            return await complete(
                {**public(model), "secret": model.secret},
                [
                    {
                        "role": "system",
                        "content": "为该工具编写中文 SKILL.md，说明适用任务、输入、调用步骤、输出和失败处理。不要编造接口。",
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            row.config.get("openapi", {}), ensure_ascii=False
                        ),
                    },
                ],
            )
        return public(row)


@app.get("/api/v1/deployments/{id}/logs")
async def deployment_logs(id: str, user=Depends(current_user)):
    async with DB() as db:
        row = await db.get(Deployment, id)
        if not row or (row.user_id != user.id and not user.admin):
            raise HTTPException(404, "部署不存在")
    path = settings.data_dir / "deployments" / id / "process.log"
    if not path.exists():
        return {"content": ""}
    with path.open("rb") as file:
        file.seek(max(0, path.stat().st_size - 65536))
        return {"content": file.read().decode("utf-8", errors="replace")}


@app.post("/api/v1/mcp/import")
async def import_mcp(body: dict, user=Depends(administrator)):
    servers = body.get("mcpServers", {})
    if not servers:
        raise ValueError("JSON 需包含 mcpServers")
    result = []
    for name, config in servers.items():
        result.append(
            await save_resource(
                "mcp", ResourceInput(name=name, config=config, enabled=False), user
            )
        )
    return result


@app.post("/api/v1/mcp/{id}/discover")
async def discover_mcp(id: str, user=Depends(administrator)):
    async with DB.begin() as db:
        server = await db.get(Resource, id)
        if not server or server.kind != "mcp":
            raise ValueError("MCP Server 不存在")
        tools = await extensions.discover(server.config)
        seen = set()
        for spec in tools:
            tool_id = (
                "mcp."
                + id
                + "."
                + hashlib.sha256(spec["name"].encode()).hexdigest()[:16]
            )
            seen.add(tool_id)
            row = await db.get(Resource, tool_id)
            if not row:
                row = Resource(id=tool_id, kind="tool", parent_id=id)
                db.add(row)
            meta = spec.get("_meta", {})
            row.name = spec.get("title", spec["name"])[:255]
            row.description = spec.get("description", "")[:16384]
            row.config = {
                "source": "mcp",
                "tool_name": spec["name"],
                "input_schema": spec.get("inputSchema", {}),
                "operation_class": "MUTATE_SCOPED",
                "idempotent": False,
                "ui_uri": meta.get("ui/resourceUri")
                or meta.get("ui", {}).get("resourceUri"),
            }
            row.enabled = True
        for old in (
            await db.scalars(
                select(Resource).where(
                    Resource.parent_id == id, Resource.kind == "tool"
                )
            )
        ).all():
            if old.id not in seen:
                old.enabled = False
        server.enabled = True
        return {"count": len(tools), "tools": tools}


@app.get("/api/v1/mcp/{id}/resource")
async def mcp_resource(id: str, uri: str, user=Depends(current_user)):
    async with DB() as db:
        server = await db.get(Resource, id)
        if not server or not server.enabled:
            raise ValueError("MCP Server 不可用")
        tools = (
            await db.scalars(
                select(Resource).where(
                    Resource.parent_id == id,
                    Resource.kind == "tool",
                    Resource.enabled == True,
                )
            )
        ).all()
        if uri not in {t.config.get("ui_uri") for t in tools}:
            raise HTTPException(403, "资源未由工具声明")
        return await extensions.resource(server.config, uri)


@app.post("/api/v1/mcp/{id}/view")
async def mcp_view(id: str, body: dict, user=Depends(current_user)):
    import re

    data = await mcp_resource(id, str(body.get("uri", "")), user)
    contents = data.get("contents", [])
    item = next(
        (c for c in contents if "html" in c.get("mimeType", "") and c.get("text")), None
    )
    if not item:
        raise ValueError("资源未提供 HTML")
    meta = item.get("_meta", {}).get("ui", {})
    csp = meta.get("csp", {})

    def domains(key):
        values = csp.get(key, [])
        if not isinstance(values, list):
            return []
        return [
            x
            for x in values
            if isinstance(x, str)
            and len(x) <= 255
            and re.fullmatch(
                r"https://(?:\*\.)?[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?(?::[0-9]{1,5})?",
                x,
            )
        ][:20]

    ticket = secrets.token_hex(32)
    directory = settings.data_dir / "app-views"
    directory.mkdir(parents=True, exist_ok=True)
    value = {
        "html": item["text"],
        "arguments": body.get("arguments", {}),
        "result": body.get("result", {}),
        "expires": now() + 300000,
        "resource_domains": domains("resourceDomains"),
        "connect_domains": domains("connectDomains"),
        "compatibility": body.get("compatibility") is True,
    }
    (directory / (ticket + ".json")).write_text(
        json.dumps(value, ensure_ascii=False), encoding="utf-8"
    )
    return {
        "url": settings.app_origin.rstrip("/") + "/view/" + ticket,
        "mode": "isolated-compatibility"
        if value["compatibility"]
        else "isolated-display",
    }


@app.post("/api/v1/extensions/{action}")
async def extension_upload(
    action: Literal["preflight", "install"],
    file: UploadFile = File(...),
    user=Depends(administrator),
):
    raw = await file.read(20 * 1024 * 1024 + 1)
    archive = extensions.inspect_zip(raw)
    if action == "preflight":
        return archive
    async with DB.begin() as db:
        id = uid()
        manifest = archive["manifest"]
        db.add(
            Resource(
                id=id,
                kind="plugin",
                name=manifest["name"],
                description=manifest.get("description", ""),
                config=manifest,
                enabled=False,
            )
        )
        for name, config in archive["mcp"].items():
            db.add(
                Resource(
                    kind="mcp",
                    name=name,
                    config=extensions.validate_server(config),
                    parent_id=id,
                    enabled=False,
                )
            )
        for name, content in archive["skills"].items():
            db.add(
                Resource(
                    kind="skill",
                    name=name.split("/")[-2],
                    content=content,
                    parent_id=id,
                    enabled=False,
                )
            )
    return {"id": id, "status": "installed-disabled"}


@app.post("/api/v1/extensions/{id}/status")
async def extension_status(id: str, body: dict, user=Depends(administrator)):
    async with DB.begin() as db:
        parent = await db.get(Resource, id)
        if not parent or parent.kind not in {"mcp", "plugin"}:
            raise ValueError("扩展不存在")
        parent.enabled = bool(body.get("enabled"))
        children = list(
            (await db.scalars(select(Resource).where(Resource.parent_id == id))).all()
        )
        for child in children:
            child.enabled = parent.enabled
            for grandchild in (
                await db.scalars(select(Resource).where(Resource.parent_id == child.id))
            ).all():
                grandchild.enabled = parent.enabled
    return {"ok": True}


@app.get("/api/v1/schedules")
async def schedules(user=Depends(current_user)):
    async with DB() as db:
        return [
            public(s)
            for s in (
                await db.scalars(select(Schedule).where(Schedule.user_id == user.id))
            ).all()
        ]


@app.post("/api/v1/schedules")
async def schedule_create(body: dict, user=Depends(current_user)):
    async with DB.begin() as db:
        target = await db.get(Resource, body["agent_id"])
        if not target or target.kind != "agent":
            raise ValueError("智能体不存在")
        row = Schedule(
            user_id=user.id,
            name=body["name"],
            agent_id=body["agent_id"],
            task=body["task"],
            config=body["config"],
            next_at=next_time(body["config"], now()),
        )
        if not row.next_at:
            raise ValueError("执行时间必须在未来")
        db.add(row)
        await db.flush()
        return public(row)


@app.put("/api/v1/schedules/{id}")
async def schedule_update(id: str, body: dict, user=Depends(current_user)):
    async with DB.begin() as db:
        row = await owned(db, Schedule, id, user)
        if "enabled" in body:
            row.enabled = bool(body["enabled"])
        for key in ("name", "agent_id", "task", "config"):
            if key in body:
                setattr(row, key, body[key])
        row.next_at = next_time(row.config, now())
        return public(row)


@app.delete("/api/v1/schedules/{id}")
async def schedule_remove(id: str, user=Depends(current_user)):
    async with DB.begin() as db:
        await db.delete(await owned(db, Schedule, id, user))
    return {"ok": True}


@app.post("/api/v1/schedules/{id}/run")
async def schedule_run(id: str, user=Depends(current_user)):
    async with DB.begin() as db:
        await owned(db, Schedule, id, user)
        row = await db.get(Schedule, id, with_for_update=True)
        previous = await db.get(Run, row.last_run) if row.last_run else None
        if previous and previous.status not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            raise ValueError("上次运行尚未结束")
        run = await create_run(
            db, user.id, row.agent_id, row.task, trigger="SCHEDULED", schedule_id=id
        )
        row.last_run = run.id
        return {"id": run.id}
