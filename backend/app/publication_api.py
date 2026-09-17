"""@input Console administration and independently authenticated public requests.
@output Publication/version/key management, Web/API invocation and safe resumable SSE.
@position Publication HTTP boundary; no second execution engine.
@doc-sync Update header and INDEX.md on changes.
"""

import asyncio
import hmac
import json
import secrets
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import async_sessionmaker
from .db import DB, Resource, Run, Session, Message, Checkpoint, Memory, User, ToolCall, now, uid
from .security import administrator
from .config import settings
from .publication_models import PublishedApp, PublishedVersion, AppKey, EndUser, AppSession, Invocation, Idempotency, PublicEvent
from .publication import build, checksum, keyed, audit, risk, validate_grants, dependencies_valid, materialize, parameter_scopes
from .publication_traffic import admit
from .runtime import create_run, event
from .invocation import acting_as
from .db import engine

# Admission reads after the app lock must see the previous admission's commit.
# MySQL REPEATABLE READ would otherwise retain the pre-lock API-key read snapshot.
DB = async_sessionmaker(engine.execution_options(isolation_level="READ COMMITTED"), expire_on_commit=False)

router = APIRouter()
FINISHED = {"SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED", "PAUSED", "NEEDS_REVIEW"}


def app_view(app):
    return {k: getattr(app, k) for k in ("id", "agent_id", "site_code", "current_version", "enabled", "web_enabled", "api_enabled", "rpm", "concurrency")}


async def own_app(db, id, user, lock=False):
    app = await db.get(PublishedApp, id, with_for_update=lock)
    if not app or app.user_id != user.id:
        raise HTTPException(404, "应用不存在")
    return app


@router.get("/api/v1/publications")
async def publications(user=Depends(administrator)):
    async with DB() as db:
        result = []
        for app in (await db.scalars(select(PublishedApp).where(PublishedApp.user_id == user.id))).all():
            version = await db.get(PublishedVersion, app.current_version)
            changed, dependency_error = False, False
            try:
                _, _, current = await build(db, app.agent_id, user.id)
                changed = current != version.checksum
                await dependencies_valid(db, version)
            except (ValueError, HTTPException):
                dependency_error = True
            result.append({**app_view(app), "number": version.number, "changed": changed, "dependency_error": dependency_error})
        return result


@router.get("/api/v1/publications/check/{agent_id}")
async def check(agent_id: str, user=Depends(administrator)):
    async with DB() as db:
        snap, _, _ = await build(db, agent_id, user.id)
        app = await db.scalar(select(PublishedApp).where(PublishedApp.agent_id == agent_id))
        if app and app.user_id != user.id:
            raise HTTPException(403, "只能由该应用发布者管理")
        current = await db.get(PublishedVersion, app.current_version) if app else None
        from .capabilities import policy
        return {"saved_grants": current.grants if current else None,
                "current_version_id": current.id if current else None,
                "capabilities": [{"id": c["id"], "name": c["name"], "risk": risk(c),
                                  "allowed": policy(snap["definition"].get("permission_preset", "workspace-write"), c) != "DENY",
                                  "ui_uri": c.get("ui_uri"), "url_parameters": parameter_scopes(c)[1], "path_parameters": parameter_scopes(c)[0]} for c in snap["capabilities"]],
                "warnings": ["远程模型及扩展服务的实时可达性需通过后台调试确认；发布检查不执行有副作用的工具。"]}


class PublishInput(BaseModel):
    agent_id: str
    web_enabled: bool = False
    api_enabled: bool = True
    grants: dict = Field(default_factory=dict)
    notes: str = Field(default="", max_length=2000)
    acknowledge_warnings: bool = False


@router.post("/api/v1/publications")
async def publish(body: PublishInput, user=Depends(administrator)):
    if not body.acknowledge_warnings:
        raise HTTPException(400, "请确认已在后台调试远程依赖")
    async with DB.begin() as db:
        # Serialize first publish too, before the application row exists.
        agent = await db.get(Resource, body.agent_id, with_for_update=True)
        if not agent or agent.kind != "agent":
            raise HTTPException(404, "智能体不存在")
        snap, dependencies, digest = await build(db, body.agent_id, user.id)
        grants = validate_grants(snap, body.grants)
        app = await db.scalar(select(PublishedApp).where(PublishedApp.agent_id == body.agent_id).with_for_update())
        if app and app.user_id != user.id:
            raise HTTPException(403, "只能由该应用发布者管理")
        if not app:
            app = PublishedApp(id=uid(), agent_id=body.agent_id, user_id=user.id, site_code=secrets.token_urlsafe(24))
            db.add(app)
            await db.flush()
        number = (await db.scalar(select(func.max(PublishedVersion.number)).where(PublishedVersion.app_id == app.id)) or 0) + 1
        version = PublishedVersion(id=uid(), app_id=app.id, number=number, snapshot=snap,
                                   dependencies=dependencies, grants=grants, checksum=digest, notes=body.notes)
        db.add(version)
        app.current_version = version.id
        app.enabled, app.web_enabled, app.api_enabled = True, body.web_enabled, body.api_enabled
        audit(db, app.id, user.id, "PUBLISHED", version=number, grants=grants)
        return {**app_view(app), "number": number}


class AppSettings(BaseModel):
    enabled: bool
    web_enabled: bool
    api_enabled: bool
    rpm: int = Field(default=30, ge=1, le=1000)
    concurrency: int = Field(default=5, ge=1, le=100)


@router.patch("/api/v1/publications/{id}")
async def configure(id: str, body: AppSettings, user=Depends(administrator)):
    async with DB.begin() as db:
        app = await own_app(db, id, user, True)
        for key, value in body.model_dump().items():
            setattr(app, key, value)
        audit(db, id, user.id, "CHANNELS_CHANGED", **body.model_dump())
        return app_view(app)


@router.get("/api/v1/publications/{id}/versions")
async def versions(id: str, user=Depends(administrator)):
    async with DB() as db:
        await own_app(db, id, user)
        return [{"id": v.id, "number": v.number, "notes": v.notes, "created": v.created}
                for v in (await db.scalars(select(PublishedVersion).where(PublishedVersion.app_id == id).order_by(PublishedVersion.number.desc()))).all()]


@router.post("/api/v1/publications/{id}/versions/{version_id}/activate")
async def rollback(id: str, version_id: str, user=Depends(administrator)):
    async with DB.begin() as db:
        app = await own_app(db, id, user, True)
        version = await db.get(PublishedVersion, version_id)
        if not version or version.app_id != id:
            raise HTTPException(404, "版本不存在")
        await dependencies_valid(db, version)
        app.current_version = version.id
        audit(db, id, user.id, "VERSION_ACTIVATED", number=version.number)
        return {"ok": True}


class KeyInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires: int | None = None


@router.get("/api/v1/publications/{id}/keys")
async def keys(id: str, user=Depends(administrator)):
    async with DB() as db:
        await own_app(db, id, user)
        return [{k: getattr(row, k) for k in ("id", "name", "prefix", "last_four", "active", "expires", "last_used")}
                for row in (await db.scalars(select(AppKey).where(AppKey.app_id == id))).all()]


@router.post("/api/v1/publications/{id}/keys")
async def new_key(id: str, body: KeyInput, user=Depends(administrator)):
    async with DB.begin() as db:
        await own_app(db, id, user, True)
        count = await db.scalar(select(func.count()).select_from(AppKey).where(AppKey.app_id == id, AppKey.active == True,
                                 (AppKey.expires.is_(None) | (AppKey.expires > now()))))
        if count >= 10:
            raise HTTPException(409, "最多 10 个有效密钥")
        if body.expires is not None and body.expires <= now():
            raise HTTPException(400, "失效时间必须在将来")
        plaintext = "app-" + secrets.token_urlsafe(32)
        row = AppKey(id=uid(), app_id=id, name=body.name, digest=keyed(plaintext), prefix=plaintext[:12],
                     last_four=plaintext[-4:], expires=body.expires)
        db.add(row)
        audit(db, id, user.id, "KEY_CREATED", key_id=row.id)
        return {"id": row.id, "key": plaintext}


@router.delete("/api/v1/publications/{id}/keys/{key_id}")
async def revoke(id: str, key_id: str, user=Depends(administrator)):
    async with DB.begin() as db:
        await own_app(db, id, user, True)
        key = await db.get(AppKey, key_id)
        if not key or key.app_id != id:
            raise HTTPException(404, "密钥不存在")
        key.active = False
        audit(db, id, user.id, "KEY_REVOKED", key_id=key_id)
        return {"ok": True}


async def identify(db, request, external_user=None, site_code=None, accepting=False, allow_cleared=False):
    key = None
    if site_code:
        app = await db.scalar(select(PublishedApp).where(PublishedApp.site_code == site_code).with_for_update())
        channel = "WEB_APP"
        cookie = request.cookies.get("visitor_" + site_code, "")
        parts = cookie.split(".")
        if len(parts) != 2 or not hmac.compare_digest(parts[1], keyed(site_code + ":" + parts[0])):
            raise HTTPException(401, "VISITOR_REQUIRED")
        external_user = parts[0]
        if request.method not in {"GET", "HEAD"}:
            origin = request.headers.get("origin", "")
            if origin not in settings.origins.split(",") or not hmac.compare_digest(request.headers.get("x-visitor-csrf", ""), keyed("csrf:" + cookie)):
                raise HTTPException(403, "CSRF_INVALID")
    else:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer app-"):
            raise HTTPException(401, "INVALID_API_KEY")
        key = await db.scalar(select(AppKey).where(AppKey.digest == keyed(auth[7:])))
        if not key or not key.active or (key.expires and key.expires <= now()):
            raise HTTPException(401, "INVALID_API_KEY")
        app = await db.get(PublishedApp, key.app_id, with_for_update=True)
        await db.refresh(key)
        if not key.active or (key.expires and key.expires <= now()):
            raise HTTPException(401, "INVALID_API_KEY")
        channel = "SERVICE_API"
        key.last_used = now()
    if not app:
        raise HTTPException(404, "APP_UNAVAILABLE")
    owner = await db.get(User, app.user_id)
    if not owner or not owner.active:
        raise HTTPException(403, "APP_UNAVAILABLE")
    if accepting and (not app.enabled or not (app.web_enabled if site_code else app.api_enabled)):
        raise HTTPException(403, "APP_UNAVAILABLE")
    if not external_user or len(external_user) > 200:
        raise HTTPException(400, "USER_REQUIRED")
    digest = keyed(app.id + ":" + channel + ":" + external_user)
    end_user = await db.scalar(select(EndUser).where(EndUser.app_id == app.id, EndUser.channel == channel, EndUser.external_digest == digest))
    if not end_user:
        end_user = EndUser(id=uid(), app_id=app.id, channel=channel, external_digest=digest, active=True)
        db.add(end_user)
        await db.flush()
    if not end_user.active and not allow_cleared:
        raise HTTPException(401, "VISITOR_CLEARED")
    return app, end_user, channel, key


class ChatInput(BaseModel):
    query: str = Field(min_length=1, max_length=32768)
    user: str | None = Field(default=None, max_length=200)
    conversation_id: str | None = None
    response_mode: Literal["async", "streaming"] = "async"


async def invoke(body, request, site_code=None):
    if not body.query.strip() or len(body.query.encode()) > 32768:
        raise HTTPException(400, "INPUT_TOO_LARGE")
    async with DB.begin() as db:
        app, visitor, channel, key = await identify(db, request, body.user, site_code, accepting=True)
        raw_idem = request.headers.get("idempotency-key")
        if raw_idem and len(raw_idem) > 200:
            raise HTTPException(400, "INVALID_IDEMPOTENCY_KEY")
        idem = keyed(app.id + ":" + visitor.id + ":" + raw_idem) if raw_idem else None
        request_hash = checksum({"query": body.query, "conversation_id": body.conversation_id})
        record = await db.get(Idempotency, idem) if idem else None
        if record and record.expires > now():
            if record.request_hash != request_hash:
                raise HTTPException(409, "IDEMPOTENCY_CONFLICT")
            run = await db.get(Run, record.run_id)
            if not run:
                raise HTTPException(410, "RUN_DELETED")
            binding = await db.get(AppSession, run.session_id)
            version = await db.get(PublishedVersion, binding.version_id)
        else:
            if body.conversation_id:
                binding = await db.get(AppSession, body.conversation_id)
                if not binding or binding.app_id != app.id or binding.end_user_id != visitor.id or binding.channel != channel:
                    raise HTTPException(404, "CONVERSATION_NOT_FOUND")
                version_id = binding.version_id
            else:
                version_id = app.current_version
            version = await db.get(PublishedVersion, version_id)
            snap = await materialize(db, version)
            active = select(func.count()).select_from(Invocation).join(Run, Run.id == Invocation.run_id).where(Invocation.app_id == app.id, Run.status.not_in(FINISHED))
            if (await db.scalar(active)) >= app.concurrency or (await db.scalar(active.where(Invocation.end_user_id == visitor.id))) >= 2:
                raise HTTPException(429, "CONCURRENCY_LIMIT_EXCEEDED")
            await admit(app, channel, request.client.host if request.client else "unknown")
            snap["publication"] = {"app_id": app.id, "version_id": version.id, "number": version.number,
                                   "end_user_id": visitor.id, "channel": channel, "grants": version.grants}
            run = await create_run(db, app.user_id, app.agent_id, body.query, session_id=body.conversation_id,
                                   trigger=channel, published_snapshot=snap)
            if not body.conversation_id:
                db.add(AppSession(session_id=run.session_id, app_id=app.id, version_id=version.id, end_user_id=visitor.id, channel=channel))
            db.add(Invocation(run_id=run.id, app_id=app.id, version_id=version.id, end_user_id=visitor.id,
                              channel=channel, key_id=key.id if key else None, public_seq=0))
            if record:
                await db.delete(record)
                await db.flush()
            if idem:
                db.add(Idempotency(id=idem, request_hash=request_hash, run_id=run.id, expires=now() + 86400000))
            audit(db, app.id, visitor.id, "RUN_ACCEPTED", run_id=run.id, version=version.number, channel=channel)
        result = {"run_id": run.id, "conversation_id": run.session_id, "version": version.number, "status": run.status}
    if body.response_mode == "streaming":
        return sse(run.id, 0, request, body.user, site_code)
    from fastapi.responses import JSONResponse
    return JSONResponse(result, status_code=202)


@router.post("/service-api/v1/chat-messages")
async def service_chat(body: ChatInput, request: Request):
    return await invoke(body, request)


@router.post("/public-api/v1/apps/{site_code}/chat-messages")
async def web_chat(site_code: str, body: ChatInput, request: Request):
    return await invoke(body, request, site_code)


async def owned_run(db, request, run_id, user, site_code):
    app, visitor, _, _ = await identify(db, request, user, site_code)
    inv = await db.get(Invocation, run_id)
    run = await db.get(Run, run_id)
    if not inv or inv.app_id != app.id or inv.end_user_id != visitor.id or not run:
        raise HTTPException(404, "RUN_NOT_FOUND")
    return run


@router.get("/service-api/v1/runs/{run_id}")
@router.get("/public-api/v1/apps/{site_code}/runs/{run_id}")
async def run_state(run_id: str, request: Request, user: str | None = None, site_code: str | None = None):
    async with DB.begin() as db:
        run = await owned_run(db, request, run_id, user, site_code)
        return {"run_id": run.id, "conversation_id": run.session_id, "status": run.status,
                "version": run.snapshot["publication"]["number"], "answer": run.result if run.status == "SUCCEEDED" else "",
                "error": "任务未完成，请联系发布者" if run.status in FINISHED - {"SUCCEEDED"} else None}


def sse(run_id, after, request, user, site_code):
    async def stream():
        seq = after
        while not await request.is_disconnected():
            async with DB.begin() as db:
                try:
                    run = await owned_run(db, request, run_id, user, site_code)
                except HTTPException:
                    yield 'event: done\ndata: {"status":"ACCESS_REVOKED"}\n\n'
                    return
                rows = (await db.scalars(select(PublicEvent).where(PublicEvent.run_id == run_id, PublicEvent.seq > seq).order_by(PublicEvent.seq))).all()
                finished = run.status in FINISHED
            for row in rows:
                seq = row.seq
                yield f"id: {seq}\nevent: {row.name}\ndata: {json.dumps({**row.data, 'seq': seq}, ensure_ascii=False)}\n\n"
            if finished:
                return
            yield ": keepalive\n\n"
            await asyncio.sleep(1)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/service-api/v1/runs/{run_id}/events")
@router.get("/public-api/v1/apps/{site_code}/runs/{run_id}/events")
async def events(run_id: str, request: Request, user: str | None = None, site_code: str | None = None):
    async with DB.begin() as db:
        await owned_run(db, request, run_id, user, site_code)
    try:
        after = max(0, int(request.headers.get("last-event-id", "0")))
    except ValueError:
        raise HTTPException(400, "INVALID_EVENT_ID")
    return sse(run_id, after, request, user, site_code)


@router.post("/service-api/v1/runs/{run_id}/stop")
@router.post("/public-api/v1/apps/{site_code}/runs/{run_id}/stop")
async def stop(run_id: str, request: Request, user: str | None = None, site_code: str | None = None):
    async with DB.begin() as db:
        await owned_run(db, request, run_id, user, site_code)
        run = await db.get(Run, run_id, with_for_update=True)
        if run.status not in FINISHED:
            run.status = "CANCEL_REQUESTED" if run.status == "RUNNING" else "CANCELLED"
            await event(db, run, "RUN_" + run.status)
        return {"run_id": run.id, "status": run.status}


@router.get("/service-api/v1/conversations/{conversation_id}/messages")
@router.get("/public-api/v1/apps/{site_code}/conversations/{conversation_id}/messages")
async def messages(conversation_id: str, request: Request, user: str | None = None, site_code: str | None = None):
    async with DB.begin() as db:
        app, visitor, _, _ = await identify(db, request, user, site_code)
        binding = await db.get(AppSession, conversation_id)
        if not binding or binding.app_id != app.id or binding.end_user_id != visitor.id:
            raise HTTPException(404, "CONVERSATION_NOT_FOUND")
        return [{"role": row.role, "content": row.content, "created": row.created, "run_id": (row.meta or {}).get("run_id")}
                for row in (await db.scalars(select(Message).where(Message.session_id == conversation_id).order_by(Message.id))).all()]


@router.get("/public-api/v1/apps/{site_code}/conversations/{conversation_id}/views")
async def conversation_views(site_code: str, conversation_id: str, request: Request):
    """Replay only view descriptors belonging to this visitor, never raw tool arguments."""
    async with DB.begin() as db:
        app, visitor, _, _ = await identify(db, request, site_code=site_code)
        binding = await db.get(AppSession, conversation_id)
        if not binding or binding.app_id != app.id or binding.end_user_id != visitor.id:
            raise HTTPException(404, "CONVERSATION_NOT_FOUND")
        rows = (await db.execute(select(ToolCall, Run).join(Run, Run.id == ToolCall.run_id)
                                .where(Run.session_id == conversation_id, ToolCall.status == "SUCCEEDED")
                                .order_by(Run.created, ToolCall.id))).all()
        result = []
        for call, run in rows:
            cap = next((c for c in run.snapshot.get("capabilities", []) if c["id"] == call.capability_id), {})
            if cap.get("ui_uri") and cap["id"] in run.snapshot.get("publication", {}).get("grants", {}):
                result.append({"run_id": run.id, "call_id": call.id, "name": cap.get("name", "交互结果")})
        return result


@router.get("/public-api/v1/apps/{site_code}")
async def web_info(site_code: str, request: Request, response: Response):
    async with DB() as db:
        app = await db.scalar(select(PublishedApp).where(PublishedApp.site_code == site_code))
        if not app or not app.enabled or not app.web_enabled:
            raise HTTPException(404, "APP_UNAVAILABLE")
        version = await db.get(PublishedVersion, app.current_version)
        cookie_name = "visitor_" + site_code
        cookie = request.cookies.get(cookie_name, "")
        parts = cookie.split(".")
        if len(parts) != 2 or not hmac.compare_digest(parts[-1], keyed(site_code + ":" + parts[0])):
            identity = secrets.token_urlsafe(32)
            cookie = identity + "." + keyed(site_code + ":" + identity)
            response.set_cookie(cookie_name, cookie, httponly=True, secure=settings.secure_cookie, samesite="strict",
                                path="/public-api/v1/apps/" + site_code, max_age=365 * 86400)
        return {"name": version.snapshot["agent_name"], "description": version.snapshot.get("description", ""),
                "version": version.number, "csrf": keyed("csrf:" + cookie)}


@router.get("/public-api/v1/apps/{site_code}/conversations")
async def conversations(site_code: str, request: Request):
    async with DB.begin() as db:
        app, visitor, _, _ = await identify(db, request, site_code=site_code)
        rows = (await db.execute(select(Session, PublishedVersion.number).join(AppSession, AppSession.session_id == Session.id)
                 .join(PublishedVersion, PublishedVersion.id == AppSession.version_id)
                 .where(AppSession.end_user_id == visitor.id).order_by(Session.created.desc()))).all()
        return [{"id": session.id, "title": session.title, "version": number} for session, number in rows]


@router.delete("/public-api/v1/apps/{site_code}/conversations/{conversation_id}")
async def clear_conversation(site_code: str, conversation_id: str, request: Request):
    async with DB.begin() as db:
        _, visitor, _, _ = await identify(db, request, site_code=site_code)
        binding = await db.get(AppSession, conversation_id)
        if not binding or binding.end_user_id != visitor.id:
            raise HTTPException(404, "CONVERSATION_NOT_FOUND")
        if await db.scalar(select(Run.id).where(Run.session_id == conversation_id, Run.status.not_in(FINISHED)).limit(1)):
            raise HTTPException(409, "请先停止当前任务")
        await db.execute(delete(Message).where(Message.session_id == conversation_id))
        await db.execute(delete(Checkpoint).where(Checkpoint.session_id == conversation_id))
        await db.execute(delete(Session).where(Session.id == conversation_id))
        await db.delete(binding)
        return {"ok": True}


@router.delete("/public-api/v1/apps/{site_code}/visitor")
async def clear_visitor(site_code: str, request: Request, response: Response):
    async with DB.begin() as db:
        app, visitor, _, _ = await identify(db, request, site_code=site_code, allow_cleared=True)
        visitor = await db.get(EndUser, visitor.id, with_for_update=True)
        visitor.active = False
        runs = (await db.scalars(select(Run).join(Invocation, Invocation.run_id == Run.id).where(Invocation.end_user_id == visitor.id).with_for_update())).all()
        for run in runs:
            if run.status not in FINISHED:
                run.status = "CANCEL_REQUESTED" if run.status == "RUNNING" else "CANCELLED"
                await event(db, run, "RUN_" + run.status)
        visitor_id, app_id, owner_id = visitor.id, app.id, app.user_id
    # Drain claimed workers before deleting messages; governance serializes on EndUser.
    for _ in range(20):
        async with DB() as db:
            pending = await db.scalar(select(Run.id).join(Invocation, Invocation.run_id == Run.id).where(
                Invocation.end_user_id == visitor_id, Run.lease_owner.is_not(None)).limit(1))
        if not pending:
            break
        await asyncio.sleep(0.25)
    else:
        raise HTTPException(409, "VISITOR_CLEAR_PENDING_RETRY")
    async with DB.begin() as db:
        visitor = await db.get(EndUser, visitor_id, with_for_update=True)
        bindings = (await db.scalars(select(AppSession).where(AppSession.end_user_id == visitor.id))).all()
        for binding in bindings:
            await db.execute(delete(Message).where(Message.session_id == binding.session_id))
            await db.execute(delete(Checkpoint).where(Checkpoint.session_id == binding.session_id))
            await db.execute(delete(Session).where(Session.id == binding.session_id))
            await db.delete(binding)
        with acting_as(visitor.id):
            await db.execute(delete(Memory).where(Memory.user_id == owner_id))
        audit(db, app_id, visitor.id, "VISITOR_CLEARED")
    response.delete_cookie("visitor_" + site_code, path="/public-api/v1/apps/" + site_code)
    return {"ok": True, "notice": "访客会话及记忆已清除；发布者的任务审计依法保留"}


@router.post("/public-api/v1/apps/{site_code}/runs/{run_id}/views/{call_id}")
async def public_view(site_code: str, run_id: str, call_id: str, request: Request):
    async with DB.begin() as db:
        run = await owned_run(db, request, run_id, None, site_code)
        call = await db.get(ToolCall, call_id)
        if not call or call.run_id != run.id or call.status != "SUCCEEDED":
            raise HTTPException(404, "VIEW_NOT_FOUND")
        cap = next((c for c in run.snapshot["capabilities"] if c["id"] == call.capability_id), None)
        if not cap or not cap.get("ui_uri") or not cap.get("server_id"):
            raise HTTPException(404, "VIEW_NOT_FOUND")
        grant = run.snapshot["publication"]["grants"].get(cap["id"])
        if grant is None:
            raise HTTPException(403, "VIEW_NOT_AUTHORIZED")
        from .main import create_mcp_view
        from . import extensions
        from .security import sanitize
        body = {"arguments": sanitize(call.arguments), "result": sanitize(call.result.get("data", {})),
                "compatibility": grant.get("ui_compatibility") is True}
    data = await extensions.resource(cap["server"], cap["ui_uri"])
    return {**create_mcp_view(data, body),
            "compatibility_required": cap["ui_uri"] == "ui://cesium-map/mcp-app.html",
            "compatibility_allowed": body["compatibility"]}
