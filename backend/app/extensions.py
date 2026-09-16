"""@input MCP SDK, direct/single-entry mcpServers config and ZIP archives. @output Normalized servers, pre-dispatch reconnect, phase diagnostics and validated projections.
@position Extension adapters. @doc-sync Update header and INDEX.md on changes.
"""

import asyncio
import io
import json
import logging
import os
import re
import zipfile
import httpx
import anyio
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client


def secrets(value):
    if isinstance(value, dict):
        return {k: secrets(v) for k, v in value.items()}
    if isinstance(value, list):
        return [secrets(v) for v in value]
    if isinstance(value, str) and value.startswith("${secret:") and value.endswith("}"):
        key = value[9:-1]
        if key not in os.environ:
            raise ValueError("缺少密钥环境变量：" + key)
        return os.environ[key]
    return value


def validate_server(config):
    if not isinstance(config, dict):
        raise ValueError("MCP 配置必须为 JSON 对象")
    if "mcpServers" in config:
        servers = config["mcpServers"]
        if not isinstance(servers, dict) or not servers:
            raise ValueError("mcpServers 必须是包含服务配置的非空对象")
        if len(servers) != 1:
            raise ValueError(
                "添加单个 MCP 服务只能包含一个服务；多个服务请使用“导入 mcpServers JSON”"
            )
        if any(key in config for key in ("url", "command", "transport")):
            raise ValueError("请勿混用顶层服务参数与 mcpServers 包装格式")
        config = next(iter(servers.values()))
        if not isinstance(config, dict) or "mcpServers" in config:
            raise ValueError(
                "mcpServers 内的服务配置必须为包含 url 或 command 的 JSON 对象"
            )
    config = dict(config)
    if "url" in config:
        if not isinstance(config["url"], str):
            raise ValueError("MCP URL 必须为 HTTP/HTTPS 字符串")
        config["url"] = config["url"].strip()
    if "transport" in config and not isinstance(config["transport"], str):
        raise ValueError("MCP transport 必须为字符串")
    transport = (
        config.get("transport", "stdio" if config.get("command") else "streamable-http")
        .lower()
        .replace("_", "-")
    )
    if transport in {"http", "streamablehttp"}:
        transport = "streamable-http"
    if transport not in {"stdio", "streamable-http"}:
        raise ValueError("不支持的 MCP transport")
    config = {**config, "transport": transport}
    if transport == "stdio":
        leaf = (
            re.split(r"[/\\]", config.get("command", ""))[-1]
            .lower()
            .removesuffix(".exe")
            .removesuffix(".cmd")
        )
        if leaf not in {"python", "python3", "node", "npx", "uvx", "java", "docker"}:
            raise ValueError("MCP 程序不在允许列表")
    elif not config.get("url", "").startswith(("https://", "http://")):
        raise ValueError("MCP URL 必须为 HTTP/HTTPS")
    for key, value in {**config.get("env", {}), **config.get("headers", {})}.items():
        if re.search(r"key|token|secret|password|authorization", key, re.I) and not str(
            value
        ).startswith("${secret:"):
            raise ValueError("敏感字段必须使用 ${secret:ENV_NAME}")
    return config


@asynccontextmanager
async def session(config):
    # Retry only connection/initialization. Once yielded, a tool may have run.
    for attempt in range(3):
        ready = False
        try:
            async with _session(config) as client:
                ready = True
                yield client
            return
        except Exception as exc:
            if not transport_failure(exc):
                raise
            phase = "operation_or_close" if ready else "initialize"
            logging.getLogger(__name__).warning(
                "MCP transport failure phase=%s attempt=%s types=%s",
                phase,
                attempt + 1,
                transport_error_types(exc),
            )
            if ready:
                raise
            if attempt == 2:
                raise McpTransportError(
                    "MCP 连接/初始化连续失败，工具尚未发出。请检查服务网络后重试。"
                ) from exc
            await asyncio.sleep(0.5 * (attempt + 1))


@asynccontextmanager
async def _session(config):
    config = secrets(validate_server(config))
    async with asyncio.timeout(120):
        if config["transport"] == "stdio":
            env = {
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
                    "APPDATA",
                    "LOCALAPPDATA",
                }
            }
            env.update(config.get("env", {}))
            async with stdio_client(
                StdioServerParameters(
                    command=config["command"], args=config.get("args", []), env=env
                )
            ) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    yield client
        else:
            async with httpx.AsyncClient(
                headers=config.get("headers"),
                timeout=120,
                trust_env=False,
                transport=httpx.AsyncHTTPTransport(retries=2, trust_env=False),
            ) as http_client:
                async with streamable_http_client(
                    config["url"], http_client=http_client
                ) as (read, write, _):
                    async with ClientSession(read, write) as client:
                        await client.initialize()
                        yield client


async def _discover(config):
    async with session(config) as client:
        tools, cursor = [], None
        for _ in range(20):
            page = await client.list_tools(cursor=cursor)
            tools.extend(
                t.model_dump(mode="json", by_alias=True, exclude_none=True)
                for t in page.tools
            )
            cursor = page.nextCursor
            if not cursor:
                return tools
        raise ValueError("MCP 发现页数超过限制")


async def _call(config, name, arguments):
    async with session(config) as client:
        result = await client.call_tool(name, arguments)
        data = result.model_dump(mode="json", by_alias=True, exclude_none=True)
        if len(json.dumps(data)) > 2 * 1024 * 1024:
            raise ValueError("MCP 结果超过 2MB")
        return data


async def _resource(config, uri):
    async with session(config) as client:
        data = (await client.read_resource(uri)).model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
        if len(json.dumps(data)) > 2 * 1024 * 1024:
            raise ValueError("MCP UI 资源过大")
        return data


class McpTransportError(RuntimeError):
    """Sanitized remote connection error, distinct from configuration validation."""


def transport_failure(exc):
    if isinstance(exc, BaseExceptionGroup):
        return any(transport_failure(item) for item in exc.exceptions)
    return isinstance(
        exc,
        (
            httpx.TransportError,
            TimeoutError,
            ConnectionError,
            anyio.BrokenResourceError,
            anyio.EndOfStream,
        ),
    )


def transport_error_types(exc):
    """Keep diagnostics useful without exposing headers, URLs or credentials."""
    if isinstance(exc, BaseExceptionGroup):
        return sorted(
            {name for item in exc.exceptions for name in transport_error_types(item)}
        )
    return [type(exc).__name__]


async def transport_request(operation, retry=False):
    for attempt in range(3 if retry else 1):
        try:
            return await operation()
        except Exception as exc:
            if not transport_failure(exc):
                raise
            if retry and attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            raise McpTransportError(
                "MCP 服务连接或读取失败，请检查服务网络后重试。工具执行可能已发出，不会自动重放有副作用的调用。"
            ) from exc


async def discover(config):
    return await transport_request(lambda: _discover(config), retry=True)


async def resource(config, uri):
    return await transport_request(lambda: _resource(config, uri), retry=True)


async def call(config, name, arguments):
    return await transport_request(lambda: _call(config, name, arguments))


def inspect_zip(raw):
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("扩展包不能超过 20MB")
    output = {"manifest": None, "mcp": {}, "skills": {}}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if len(archive.infolist()) > 256:
            raise ValueError("扩展包文件超过 256 个")
        total = 0
        for entry in archive.infolist():
            name = entry.filename.replace("\\", "/")
            path = PurePosixPath(name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or ":" in name
                or (entry.external_attr >> 16) & 0o170000 == 0o120000
            ):
                raise ValueError("扩展包路径不安全")
            total += entry.file_size
            if entry.file_size > 2 * 1024 * 1024 or total > 20 * 1024 * 1024:
                raise ValueError("解压后体积超过限制")
            if entry.is_dir():
                continue
            if path.suffix.lower() not in {
                ".md",
                ".json",
                ".txt",
                ".html",
                ".css",
                ".svg",
                ".png",
                ".jpg",
                ".jpeg",
            }:
                raise ValueError("扩展包仅接受声明、文档及 UI 资源，不执行包内脚本")
            data = archive.read(entry)
            if name in {
                "plugin.json",
                ".codex-plugin/plugin.json",
                ".claude-plugin/plugin.json",
            }:
                output["manifest"] = json.loads(data)
            elif name == ".mcp.json":
                output["mcp"] = json.loads(data).get("mcpServers", {})
            elif name.startswith("skills/") and name.endswith("/SKILL.md"):
                output["skills"][name] = data.decode("utf-8")
        if not output["manifest"] or not output["manifest"].get("name"):
            raise ValueError("扩展包缺少有效 plugin.json")
        for config in output["mcp"].values():
            validate_server(config)
    return output
