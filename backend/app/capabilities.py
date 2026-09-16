"""@input Capability manifests and run snapshots. @output Governed local/MCP/HTTP execution.
@position Tool execution boundary. @doc-sync Update header and INDEX.md on changes.
"""

import asyncio
import ipaddress
import os
import shutil
from pathlib import Path
from urllib.parse import urlparse
import httpx
import psutil
from jsonschema import validate
from .config import settings
from .security import decrypt
from . import extensions


def schema(properties, required=()):
    return {
        "type": "object",
        "properties": {k: {"type": v} for k, v in properties.items()},
        "required": list(required),
    }


def builtin(id, name, operation, props, required=(), idempotent=True):
    return {
        "id": id,
        "name": name,
        "description": name,
        "operation_class": operation,
        "idempotent": idempotent,
        "timeout_seconds": 60,
        "input_schema": schema(props, required),
        "source": "builtin",
    }


BUILTINS = [
    builtin("builtin.fs.list", "查看目录", "READ_SCOPED", {"path": "string"}),
    builtin(
        "builtin.fs.read", "读取文本文件", "READ_SCOPED", {"path": "string"}, ["path"]
    ),
    builtin(
        "builtin.fs.write",
        "写入文件",
        "MUTATE_SCOPED",
        {"path": "string", "content": "string", "overwrite": "boolean"},
        ["path", "content"],
    ),
    builtin(
        "builtin.fs.patch",
        "唯一文本精确替换",
        "MUTATE_SCOPED",
        {"path": "string", "oldText": "string", "newText": "string"},
        ["path", "oldText", "newText"],
    ),
    builtin(
        "builtin.fs.mkdir", "创建目录", "MUTATE_SCOPED", {"path": "string"}, ["path"]
    ),
    builtin(
        "builtin.fs.search_name",
        "搜索文件名",
        "READ_SCOPED",
        {"query": "string"},
        ["query"],
    ),
    builtin(
        "builtin.fs.search_content",
        "搜索文件内容",
        "READ_SCOPED",
        {"query": "string"},
        ["query"],
    ),
    builtin(
        "builtin.fs.copy",
        "复制文件",
        "MUTATE_SCOPED",
        {"source": "string", "target": "string"},
        ["source", "target"],
    ),
    builtin(
        "builtin.fs.move",
        "移动文件",
        "MUTATE_SCOPED",
        {"source": "string", "target": "string"},
        ["source", "target"],
        False,
    ),
    builtin(
        "builtin.fs.delete",
        "回收文件",
        "DESTRUCTIVE",
        {"path": "string"},
        ["path"],
        False,
    ),
    builtin(
        "builtin.process.exec",
        "执行受控程序",
        "MUTATE_SCOPED",
        {"executable": "string", "args": "array", "cwd": "string"},
        ["executable"],
        False,
    ),
    builtin(
        "builtin.http.fetch", "读取网页", "READ_GLOBAL", {"url": "string"}, ["url"]
    ),
    builtin("builtin.harness.context.compact", "压缩当前会话", "MUTATE_SCOPED", {}),
    builtin(
        "builtin.harness.memory.manage",
        "显式保存、更新或删除记忆",
        "MUTATE_SCOPED",
        {"operation": "string", "content": "string", "id": "string", "scope": "string"},
        ["operation"],
        False,
    ),
    builtin("builtin.harness.run.status", "查询当前任务状态", "READ_SCOPED", {}),
]


def policy(preset, capability):
    op = capability.get("operation_class")
    if op not in {
        "READ_SCOPED",
        "READ_GLOBAL",
        "MUTATE_SCOPED",
        "MUTATE_GLOBAL",
        "DESTRUCTIVE",
        "CONTROL_PLANE",
    }:
        return "DENY"
    if preset == "read-only":
        return "ALLOW" if op == "READ_SCOPED" else "DENY"
    if preset == "workspace-write":
        return {"READ_SCOPED": "ALLOW", "MUTATE_SCOPED": "CONFIRM"}.get(op, "DENY")
    if preset == "danger-full-access":
        return "ALLOW" if op in {"READ_SCOPED", "MUTATE_SCOPED"} else "CONFIRM"
    return "DENY"


def resolve_path(root, value="."):
    if not root:
        raise ValueError("当前智能体没有授权工作目录")
    base = Path(root).resolve(strict=True)
    path = (base / value).resolve()
    if not path.is_relative_to(base):
        raise ValueError("路径超出授权工作目录")
    return path


def file_operation(id, args, root, call_id):
    base = resolve_path(root)
    path = resolve_path(root, args.get("path", "."))
    if id.endswith(".list"):
        return {
            "entries": [
                {"name": p.name, "directory": p.is_dir()}
                for p in list(path.iterdir())[:200]
            ]
        }
    if id.endswith(".read"):
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("单次读取不得超过 1MB")
        return {"content": path.read_text(encoding="utf-8"), "path": str(path)}
    if id.endswith((".search_name", ".search_content")):
        matches = []
        for index, p in enumerate(base.rglob("*")):
            if index >= 5000 or len(matches) >= 200:
                break
            if (
                p.is_symlink()
                or not p.is_file()
                or not p.resolve().is_relative_to(base)
            ):
                continue
            query = args["query"].lower()
            if id.endswith("search_name"):
                if query in p.name.lower():
                    matches.append({"path": str(p.relative_to(base))})
            elif p.stat().st_size <= 1024 * 1024:
                try:
                    content = p.read_text(encoding="utf-8")
                except UnicodeError:
                    continue
                pos = content.lower().find(query)
                if pos >= 0:
                    matches.append(
                        {
                            "path": str(p.relative_to(base)),
                            "preview": content[max(0, pos - 80) : pos + 200],
                        }
                    )
        return {"matches": matches}
    if path == base and id.endswith((".delete", ".write", ".patch")):
        raise ValueError("不能修改工作区根目录")
    if id.endswith(".mkdir"):
        path.mkdir(parents=True, exist_ok=True)
    elif id.endswith((".write", ".patch")):
        if id.endswith(".patch"):
            original = path.read_text(encoding="utf-8")
            if not args["oldText"] or original.count(args["oldText"]) != 1:
                raise ValueError("oldText 必须唯一出现")
            content = original.replace(args["oldText"], args["newText"], 1)
        else:
            if path.exists() and not args.get("overwrite"):
                raise ValueError("文件已存在，需 overwrite=true")
            content = args["content"]
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.parent / (".agent-" + call_id + ".tmp")
        try:
            temp.write_text(content, encoding="utf-8")
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
    elif id.endswith(".delete"):
        trash = base / ".agent-trash" / call_id / path.name
        trash.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(trash))
        return {"trash_path": str(trash), "recoverable": True}
    elif id.endswith((".copy", ".move")):
        source = resolve_path(root, args["source"])
        target = resolve_path(root, args["target"])
        if source == base or target == base:
            raise ValueError("不能复制或移动根目录")
        if target.exists():
            raise ValueError("目标已存在")
        target.parent.mkdir(parents=True, exist_ok=True)
        (shutil.copy2 if id.endswith(".copy") else shutil.move)(
            str(source), str(target)
        )
    return {"path": str(path), "completed": True}


def kill_tree(pid):
    try:
        process = psutil.Process(pid)
        children = process.children(recursive=True)
        for child in children:
            child.kill()
        process.kill()
    except psutil.NoSuchProcess:
        pass


async def process_operation(args, root):
    executable = args["executable"]
    leaf = Path(executable).name.lower().removesuffix(".exe").removesuffix(".cmd")
    if leaf not in settings.command_allowlist.split(","):
        raise ValueError("程序不在允许列表")
    cwd = resolve_path(root, args.get("cwd", "."))
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper()
        in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE"}
    }
    process = await asyncio.create_subprocess_exec(
        executable,
        *map(str, args.get("args", [])),
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def drain(stream):
        output = bytearray()
        truncated = False
        while data := await stream.read(4096):
            remaining = 65536 - len(output)
            output.extend(data[:remaining])
            truncated |= len(data) > remaining
        return output.decode("utf-8", errors="replace"), truncated

    try:
        out, err, _ = await asyncio.gather(
            drain(process.stdout), drain(process.stderr), process.wait()
        )
        return {
            "exitCode": process.returncode,
            "stdout": out[0],
            "stderr": err[0],
            "truncated": out[1] or err[1],
        }
    except BaseException:
        kill_tree(process.pid)
        await process.wait()
        raise


async def fetch(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ValueError("URL 不合法")
    allowed = settings.network_hosts.split(",") if settings.network_hosts else []
    hostport = (
        f"{parsed.hostname}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}"
    )
    if hostport not in allowed:
        raise ValueError("目标域名和端口不在联网白名单：" + hostport)
    addresses = await asyncio.get_running_loop().getaddrinfo(
        parsed.hostname, parsed.port or 443
    )
    if any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("内置网页读取禁止本机及内网目标")
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=False, trust_env=False
    ) as client:
        async with client.stream("GET", url) as response:
            if 300 <= response.status_code < 400:
                raise ValueError("重定向需单独校验")
            response.raise_for_status()
            output = bytearray()
            async for chunk in response.aiter_bytes():
                output.extend(chunk[: 1024 * 1024 - len(output)])
                if len(output) >= 1024 * 1024:
                    break
            return {
                "status": response.status_code,
                "content": output.decode("utf-8", errors="replace"),
            }


async def execute(cap, args, root, call_id):
    validate(args, cap.get("input_schema") or {"type": "object"})
    async with asyncio.timeout(min(300, max(1, int(cap.get("timeout_seconds", 60))))):
        if cap["id"].startswith("builtin.fs."):
            return file_operation(cap["id"], args, root, call_id)
        if cap["id"] == "builtin.process.exec":
            result = await process_operation(args, root)
            if result["exitCode"] != 0:
                return {"ok": False, "error": "程序返回非零退出码", **result}
            return result
        if cap["id"] == "builtin.http.fetch":
            return await fetch(args["url"])
        if cap.get("source") == "mcp":
            result = await extensions.call(cap["server"], cap["tool_name"], args)
            if result.get("isError"):
                result["ok"] = False
            if cap.get("ui_uri"):
                result["app"] = {"server_id": cap["server_id"], "uri": cap["ui_uri"]}
            return result
        headers = (
            {"Authorization": "Bearer " + decrypt(cap["secret"])}
            if cap.get("secret")
            else {}
        )
        async with httpx.AsyncClient(
            timeout=120, trust_env=False, follow_redirects=False
        ) as client:
            if cap.get("deployment_id"):
                health = await client.get(cap["endpoint"].rstrip("/") + "/health")
                if (
                    not health.is_success
                    or health.json().get("instance_id") != cap["deployment_id"]
                ):
                    raise ValueError("部署实例已变化，请重新发起任务")
            response = await client.post(
                cap["endpoint"].rstrip("/") + "/" + cap["path"].lstrip("/"),
                json=args,
                headers=headers,
            )
            response.raise_for_status()
            if len(response.content) > 2 * 1024 * 1024:
                raise ValueError("工具结果超过 2MB")
            return response.json()
