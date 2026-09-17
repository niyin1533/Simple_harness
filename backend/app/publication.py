"""@input Draft resources, grants and publication records. @output Immutable snapshots and execution guards.
@position Published application domain; reuses the existing serial runtime.
@doc-sync Update header and INDEX.md on changes.
"""

import copy
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlparse
from sqlalchemy import select, func
from fastapi import HTTPException
from .db import Resource, Deployment, Preference, now, uid
from .config import settings
from .capabilities import policy, resolve_path
from .publication_models import PublishedApp, PublishedVersion, PublicationAudit, Invocation, PublicEvent


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def keyed(value):
    # Domain-separated HMAC: existing server-only master material is backed up with data.
    key = (settings.data_dir / "master.key").read_bytes()
    return hmac.new(key, ("publication-v1:" + value).encode(), hashlib.sha256).hexdigest()


def audit(db, app_id, actor, action, **details):
    db.add(PublicationAudit(app_id=app_id, actor_id=actor, action=action, details=details))


def risk(cap):
    if cap["id"] == "builtin.process.exec":
        return "HIGH"
    op = cap.get("operation_class", "")
    return "READ" if op.startswith("READ_") else "WRITE" if op == "MUTATE_SCOPED" else "HIGH"


def without_credentials(value):
    if isinstance(value, dict):
        return {k: without_credentials(v) for k, v in value.items() if k not in {"secret", "password", "api_key", "authorization"}}
    if isinstance(value, list):
        return [without_credentials(v) for v in value]
    return value


def validate_references(value):
    """MCP environment/headers must reference server secrets, never freeze literal credentials."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"headers", "env"} and isinstance(item, dict):
                for name, val in item.items():
                    if any(word in name.lower() for word in ("key", "token", "secret", "password", "authorization", "cookie")):
                        if not (isinstance(val, str) and val.startswith("${secret:") and val.endswith("}")):
                            raise ValueError("发布前请将 MCP 敏感 headers/env 改为 ${secret:NAME} 引用")
            validate_references(item)
    elif isinstance(value, list):
        for item in value:
            validate_references(item)


async def build(db, agent_id, owner_id):
    from .runtime import snapshot
    snap = await snapshot(db, agent_id)
    # Knowledge content is resolved at admission; prompts and skills remain frozen.
    agent = await db.get(Resource, agent_id)
    config = snap["definition"]
    prompt = config.get("system_prompt", "")
    dependencies = []
    identifiers = [config["model_id"]]
    for kind in ("knowledge", "prompt", "skill", "tool"):
        identifiers.extend(config.get(kind + "_ids", []))
    for cap in snap["capabilities"]:
        if cap.get("server_id"):
            identifiers.append(cap["server_id"])
    # Include extension parents (skills and MCP servers may belong to a plugin).
    for id in list(identifiers):
        resource = await db.get(Resource, id)
        seen = set()
        while resource and resource.parent_id and resource.parent_id not in seen:
            seen.add(resource.parent_id)
            identifiers.append(resource.parent_id)
            resource = await db.get(Resource, resource.parent_id)
    for id in dict.fromkeys(identifiers):
        resource = await db.get(Resource, id)
        if not resource or not resource.enabled:
            raise ValueError("发布依赖不存在或已停用：" + id)
        cfg = copy.deepcopy(resource.config)
        validate_references(cfg)
        # Ports of deployment tools are runtime locators, not immutable identities.
        if cfg.get("deployment_id"):
            cfg.pop("endpoint", None)
            deployment = await db.get(Deployment, cfg["deployment_id"])
            if not deployment or deployment.status != "RUNNING":
                raise ValueError("工具部署未运行")
        dependencies.append({"id": id, "kind": resource.kind,
                             "schema": checksum(without_credentials(cfg)) if resource.kind in {"tool", "mcp"} else None})
        if resource.kind in {"prompt", "skill"}:
            prompt += "\n\n" + resource.kind + ": " + resource.name + "\n" + resource.content
    snap["prompt"] = prompt
    snap["model"] = {k: v for k, v in snap["model"].items() if k not in {"secret", "updated", "version"}}
    snap["model"]["credential_ref"] = config["model_id"]
    for cap in snap["capabilities"]:
        cap.pop("secret", None)
        if not cap["id"].startswith("builtin."):
            cap["credential_ref"] = cap["id"]
        if cap.get("deployment_id"):
            cap.pop("endpoint", None)
    pref = await db.get(Preference, owner_id)
    snap["memory_policy"] = without_credentials(copy.deepcopy(pref.config if pref else {}))
    snap["description"] = agent.description
    validate_references(snap)
    snap = without_credentials(snap)
    hashed = {k: v for k, v in snap.items() if k != "version"}
    return snap, dependencies, checksum(hashed)


def workspace(value):
    if not value:
        raise ValueError("请先为智能体设置专用工作区")
    try:
        path = Path(value).resolve(strict=True)
    except OSError as exc:
        raise ValueError("发布工作区不存在或不可访问") from exc
    forbidden = {Path(path.anchor), Path.home().resolve(), Path(os.environ.get("SystemRoot", "C:/Windows")).resolve()}
    system_root = Path(os.environ.get("SystemRoot", "C:/Windows")).resolve()
    protected = settings.data_dir.resolve()
    if not path.is_dir() or path in forbidden or path.is_relative_to(system_root) or path == protected or path in protected.parents or len(path.parts) < 3:
        raise ValueError("发布工作区必须是专用目录，不能是磁盘根、用户目录或系统目录")
    return str(path)


def parameter_scopes(cap):
    properties = cap.get("input_schema", {}).get("properties", {})
    paths = [key for key in properties if key.lower() in {"path", "source", "target", "cwd", "directory"} or key.lower().endswith(("_path", "_file"))]
    urls = [key for key in properties if key.lower() in {"url", "uri"} or key.lower().endswith("_url")]
    return paths, urls


def validate_grants(snap, grants):
    caps = {c["id"]: c for c in snap["capabilities"]}
    if set(grants) - set(caps):
        raise ValueError("预授权包含未绑定能力")
    for id, grant in grants.items():
        cap = caps[id]
        if policy(snap["definition"].get("permission_preset", "workspace-write"), cap) == "DENY":
            raise ValueError("智能体权限预设不允许：" + cap["name"])
        if not isinstance(grant, dict):
            raise ValueError("预授权必须是对象")
        paths, urls = parameter_scopes(cap)
        if paths or id.startswith("builtin.fs.") or id == "builtin.process.exec":
            snap["definition"]["workspace_path"] = workspace(snap["definition"].get("workspace_path", ""))
        if id == "builtin.process.exec":
            commands = grant.get("commands", [])
            if not commands or any(not isinstance(c, dict) or not c.get("executable") or not isinstance(c.get("args"), list) or "*" in json.dumps(c) for c in commands):
                raise ValueError("命令授权需提供精确 executable 和完整 args 列表，不允许通配")
        if urls or id == "builtin.http.fetch":
            hosts = grant.get("hosts", [])
            if not hosts or any(not isinstance(h, str) or any(c in h for c in "*/@ ") or not h for h in hosts):
                raise ValueError("网络授权需指定精确域名及可选端口")
    return grants


async def dependencies_valid(db, version):
    for dependency in version.dependencies:
        row = await db.get(Resource, dependency["id"])
        if not row or not row.enabled or row.kind != dependency["kind"]:
            raise HTTPException(409, "DEPENDENCY_UNAVAILABLE")
        if dependency.get("schema"):
            cfg = copy.deepcopy(row.config)
            if cfg.get("deployment_id"):
                cfg.pop("endpoint", None)
                deployment = await db.get(Deployment, cfg["deployment_id"])
                if not deployment or deployment.status != "RUNNING":
                    raise HTTPException(409, "DEPENDENCY_UNAVAILABLE")
            if checksum(without_credentials(cfg)) != dependency["schema"]:
                raise HTTPException(409, "DEPENDENCY_CHANGED")


async def materialize(db, version):
    await dependencies_valid(db, version)
    snap = copy.deepcopy(version.snapshot)
    for id in snap["definition"].get("knowledge_ids", []):
        row = await db.get(Resource, id)
        snap["prompt"] += "\n\nknowledge: " + row.name + "\n" + row.content
    return snap


async def credentials(db, snap):
    """Hydrate only the in-memory execution copy; never assign it back to Run.snapshot."""
    snap = copy.deepcopy(snap)
    for obj in [snap["model"], *snap["capabilities"]]:
        if obj.get("credential_ref"):
            row = await db.get(Resource, obj["credential_ref"])
            if not row or not row.enabled:
                raise ValueError("发布运行依赖已停用")
            obj["secret"] = row.secret
        if obj.get("deployment_id"):
            deployment = await db.get(Deployment, obj["deployment_id"])
            if not deployment or deployment.status != "RUNNING":
                raise ValueError("部署不可用")
            obj["endpoint"] = "http://127.0.0.1:" + str(deployment.port)
    return snap


def tool_allowed(snap, cap, args):
    publication = snap.get("publication")
    if not publication:
        return True
    grant = publication["grants"].get(cap["id"])
    if grant is None or policy(snap["definition"].get("permission_preset", "workspace-write"), cap) == "DENY":
        return False
    if publication["channel"] == "WEB_APP" and risk(cap) == "HIGH":
        return False
    try:
        paths, urls = parameter_scopes(cap)
        if paths or cap["id"].startswith("builtin.fs.") or cap["id"] == "builtin.process.exec":
            configured = snap["definition"].get("workspace_path", "")
            root = workspace(configured)
            if os.path.normcase(os.path.abspath(configured)) != os.path.normcase(root):
                return False  # A replaced junction must not move the frozen workspace boundary.
            for key in set(paths) | {"path", "source", "target", "cwd"}:
                if key in args:
                    resolve_path(root, args[key])
        for key in urls:
            if key in args:
                parsed = urlparse(args[key])
                if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in grant.get("hosts", []) or parsed.username:
                    return False
        if cap["id"] == "builtin.process.exec":
            return {"executable": args.get("executable"), "args": args.get("args", [])} in grant["commands"]
        if cap["id"] == "builtin.http.fetch":
            parsed = urlparse(args.get("url", ""))
            return parsed.scheme in {"http", "https"} and parsed.netloc.lower() in grant["hosts"] and not parsed.username
    except (ValueError, OSError, KeyError, TypeError):
        return False
    return True


async def project_event(db, run, name, data):
    invocation = await db.get(Invocation, run.id)
    if not invocation:
        return
    payloads = []
    if name == "RUN_STARTED" and invocation.public_seq == 0:
        payloads.append(("run_started", {"status": "RUNNING"}))
    elif name == "TOOL_STARTED":
        payloads.append(("tool_started", {"call_id": data.get("tool_call_id")}))
    elif name in {"TOOL_SUCCEEDED", "TOOL_FAILED"}:
        cap = next((c for c in run.snapshot["capabilities"] if c["id"] == data.get("capability_id")), {})
        ui = {"resource_uri": cap["ui_uri"], "call_id": data.get("tool_call_id")} if name == "TOOL_SUCCEEDED" and cap.get("ui_uri") else None
        payloads.append(("tool_completed", {"call_id": data.get("tool_call_id"), "ok": name == "TOOL_SUCCEEDED", "ui": ui}))
    elif name == "RUN_SUCCEEDED":
        payloads.extend([("message_completed", {"answer": run.result}), ("done", {"status": run.status})])
    elif run.status in {"FAILED", "CANCELLED", "BLOCKED", "NEEDS_REVIEW", "PAUSED"}:
        payloads.extend([("run_failed", {"code": run.status, "message": "任务未完成，请联系应用发布者查看审计记录"}), ("done", {"status": run.status})])
    for event_name, payload in payloads:
        invocation.public_seq += 1
        db.add(PublicEvent(run_id=run.id, seq=invocation.public_seq, name=event_name,
                           data={"run_id": run.id, "conversation_id": run.session_id, **payload}))
