"""@input Weight artifacts, administrator templates and isolated interpreters. @output Dependency preflight and managed inference processes.
@position Tool deployment service. @doc-sync Update header and INDEX.md on changes.
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import hashlib
import time
from pathlib import Path
import httpx
import psutil
from .config import ROOT, settings
from .db import DB, Deployment, Artifact, Resource, uid
from .capabilities import kill_tree
from .security import decrypt


async def reconcile(active):
    from sqlalchemy import select

    async with DB.begin() as db:
        rows = (
            await db.scalars(
                select(Deployment)
                .where(Deployment.status.in_(["RUNNING", "STARTING"]))
                .with_for_update(skip_locked=True)
            )
        ).all()
        for row in rows:
            if row.id in active:
                continue
            alive = False
            try:
                process = psutil.Process(row.pid) if row.pid else None
                alive = bool(
                    process
                    and abs(
                        process.create_time() - row.config.get("process_created", 0)
                    )
                    < 0.01
                )
            except psutil.NoSuchProcess:
                pass
            abandoned = (
                row.status == "STARTING"
                and time.time() - row.config.get("process_created", 0) > 90
            )
            if not alive or abandoned:
                if abandoned and alive:
                    await stop(row)
                row.status = "FAILED"
                row.error = "推理进程已退出或启动流程中断，请检查日志后重新启动"
                for tool in (
                    await db.scalars(
                        select(Resource).where(
                            Resource.parent_id == row.id, Resource.kind == "tool"
                        )
                    )
                ).all():
                    tool.enabled = False


def minimal_env():
    return {
        k: v
        for k, v in os.environ.items()
        if k.upper()
        in {
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "HOME",
            "USERPROFILE",
            "CUDA_PATH",
        }
    }


def interpreter_for(environment):
    if environment.get("python"):
        return environment["python"]
    if environment.get("runtime", "yolo") in {"yolo", "yolov5"}:
        candidate = (
            ROOT
            / ".venv-yolo"
            / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )
        if not candidate.is_file():
            raise ValueError(
                "缺少独立推理环境：请运行 python -m venv .venv-yolo，再用该环境 pip install -r tool-runtimes/requirements-yolo.txt；或在模板设置 Python 解释器"
            )
        return str(candidate)
    return sys.executable


async def preflight(interpreter, environment):
    # Custom scripts declare their own dependencies; check only bundled templates.
    if environment.get("script"):
        return
    modules = ["fastapi", "uvicorn", "httpx"]
    if environment.get("runtime", "yolo") == "yolo":
        modules += ["ultralytics", "torch", "PIL"]
    elif environment.get("runtime") == "yolov5":
        modules += ["torch", "PIL"]
    process = await asyncio.create_subprocess_exec(
        interpreter,
        "-c",
        "import importlib.util,json; print(json.dumps([m for m in "
        + repr(modules)
        + " if importlib.util.find_spec(m) is None]))",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=minimal_env(),
    )
    try:
        out, _ = await asyncio.wait_for(process.communicate(), 20)
    except BaseException:
        kill_tree(process.pid)
        await process.wait()
        raise
    if process.returncode:
        raise ValueError("推理 Python 环境无法运行，请检查模板解释器路径")
    missing = json.loads(out)
    if missing:
        raise ValueError(
            "推理环境缺少依赖："
            + ", ".join(missing)
            + "；解释器："
            + interpreter
            + "；请用该解释器安装 tool-runtimes/requirements-yolo.txt"
        )


async def start(id):
    async with DB.begin() as db:
        deployment = await db.get(Deployment, id, with_for_update=True)
        if not deployment or deployment.status != "QUEUED":
            return
        deployment.status = "STARTING"
        config = dict(deployment.config)
        template = await db.get(Resource, config["template_id"])
        if not template or not template.enabled:
            raise ValueError("推理模板不可用")
        artifact = (
            await db.get(Artifact, config.get("weight_id"))
            if config.get("weight_id")
            else None
        )
        if artifact and artifact.user_id != deployment.user_id:
            raise ValueError("权重归属不匹配")
        environment = template.config
        directory = settings.data_dir / "deployments" / id
        directory.mkdir(parents=True, exist_ok=True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        spec = {
            "instance_id": id,
            "host": "127.0.0.1",
            "port": port,
            "weights_path": artifact.path if artifact else "",
            "deployment_dir": str(directory),
            "runtime": environment.get("runtime", "yolo"),
            "device": config.get("device", "cpu"),
            "yolov5_repo": environment.get("yolov5_repo", ""),
            "base_url": environment.get("base_url", "https://api.minimax.chat"),
            "input_roots": [
                str(settings.data_dir / "uploads" / deployment.user_id),
                str(directory),
            ]
            + environment.get("input_roots", []),
        }
        spec_path = directory / "deployment.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        script = environment.get("script") or str(ROOT / "tool-runtimes" / "server.py")
        interpreter = interpreter_for(environment)
        await preflight(interpreter, environment)
        log = open(directory / "process.log", "ab")
        try:
            process = subprocess.Popen(
                [interpreter, script, "--config", str(spec_path)],
                cwd=directory,
                env={**minimal_env(), "AGENT_TOOL_API_KEY": decrypt(template.secret)},
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        finally:
            log.close()
        deployment.pid = process.pid
        deployment.port = port
        deployment.config = {
            **config,
            "process_created": psutil.Process(process.pid).create_time(),
        }
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            for _ in range(60):
                try:
                    response = await client.get(f"http://127.0.0.1:{port}/health")
                    if response.is_success and response.json().get("instance_id") == id:
                        break
                except httpx.HTTPError:
                    pass
                if process.poll() is not None:
                    raise ValueError("推理进程启动失败，请查看部署日志")
                await asyncio.sleep(1)
            else:
                raise ValueError("推理服务健康检查超时")
            schema = (await client.get(f"http://127.0.0.1:{port}/openapi.json")).json()
        async with DB.begin() as db:
            row = await db.get(Deployment, id, with_for_update=True)
            if row.status != "STARTING":
                kill_tree(process.pid)
                return
            row.status = "RUNNING"
            row.error = ""
            row.config = {**row.config, "openapi": schema}
            from sqlalchemy import select

            for tool in (
                await db.scalars(
                    select(Resource).where(
                        Resource.parent_id == id, Resource.kind == "tool"
                    )
                )
            ).all():
                tool.config = {**tool.config, "endpoint": f"http://127.0.0.1:{port}"}
                tool.enabled = True
    except Exception as exc:
        kill_tree(process.pid)
        async with DB.begin() as db:
            row = await db.get(Deployment, id, with_for_update=True)
            if row.status == "STARTING":
                row.status = "FAILED"
                row.error = str(exc)


async def stop(row):
    if row.pid:
        try:
            process = psutil.Process(row.pid)
            if abs(process.create_time() - row.config.get("process_created", 0)) < 0.01:
                kill_tree(row.pid)
        except psutil.NoSuchProcess:
            pass
    row.status = "STOPPED"
    row.pid = None


def resolve_schema(schema, document):
    if "$ref" in schema:
        value = document
        for part in schema["$ref"].removeprefix("#/").split("/"):
            value = value[part]
        return resolve_schema(value, document)
    if isinstance(schema, dict):
        return {
            k: resolve_schema(v, document)
            if isinstance(v, dict)
            else [resolve_schema(x, document) if isinstance(x, dict) else x for x in v]
            if isinstance(v, list)
            else v
            for k, v in schema.items()
        }
    return schema


async def register(db, row, path="/detect"):
    if row.status != "RUNNING":
        raise ValueError("部署尚未运行")
    document = row.config.get("openapi", {})
    operation = document.get("paths", {}).get(path, {}).get("post")
    if not operation:
        raise ValueError("OpenAPI 未声明此 POST 路径")
    input_schema = resolve_schema(
        operation.get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {"type": "object"}),
        document,
    )
    id = "deployment." + row.id + "." + path.strip("/").replace("/", ".")
    tool = await db.get(Resource, id)
    if not tool:
        tool = Resource(id=id, kind="tool", name=row.name, parent_id=row.id)
        db.add(tool)
    tool.enabled = True
    tool.description = operation.get("description") or "已部署模型推理工具"
    tool.config = {
        "source": "http",
        "endpoint": f"http://127.0.0.1:{row.port}",
        "path": path,
        "input_schema": input_schema,
        "deployment_id": row.id,
        "operation_class": "MUTATE_SCOPED",
        "idempotent": False,
        "timeout_seconds": 120,
    }
    await db.flush()
    return tool


async def publish_outputs(db, deployment_id, user_id, value):
    base = (settings.data_dir / "deployments" / deployment_id / "outputs").resolve()
    outputs = []
    for key in ("annotated_image_path", "audio_path", "image_path"):
        candidate = value.get(key)
        if not isinstance(candidate, str):
            continue
        path = Path(candidate).resolve()
        if not path.is_file() or not path.is_relative_to(base):
            continue
        with path.open("rb") as file:
            checksum = hashlib.file_digest(file, "sha256").hexdigest()
        row = Artifact(
            id=uid(),
            user_id=user_id,
            name=path.name,
            path=str(path),
            kind="output",
            digest=checksum,
            size=path.stat().st_size,
        )
        db.add(row)
        outputs.append(
            {
                "id": row.id,
                "name": row.name,
                "url": "/api/v1/artifacts/" + row.id + "/file",
            }
        )
    return {**value, "artifacts": outputs} if outputs else value
