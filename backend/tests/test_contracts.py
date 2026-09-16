"""@input Policy, path, extension and scheduler services. @output Deterministic boundary tests.
@position Unit verification. @doc-sync Update INDEX.md on changes.
"""

import io
import zipfile
from datetime import datetime
import pytest
from app.capabilities import policy, resolve_path, file_operation
from app.extensions import inspect_zip, validate_server
from app.scheduling import next_time
from app.providers import parse_json
from app.security import sanitize


@pytest.mark.parametrize(
    "preset,operation,expected",
    [
        ("read-only", "READ_SCOPED", "ALLOW"),
        ("read-only", "MUTATE_SCOPED", "DENY"),
        ("workspace-write", "MUTATE_SCOPED", "CONFIRM"),
        ("workspace-write", "DESTRUCTIVE", "DENY"),
        ("danger-full-access", "DESTRUCTIVE", "CONFIRM"),
        ("danger-full-access", "CONTROL_PLANE", "CONFIRM"),
        ("danger-full-access", "MUTATE_SCOPED", "ALLOW"),
        ("invalid", "READ_SCOPED", "DENY"),
        ("danger-full-access", "UNKNOWN", "DENY"),
    ],
)
def test_policy(preset, operation, expected):
    assert policy(preset, {"operation_class": operation}) == expected


def test_paths_and_unique_patch(tmp_path):
    with pytest.raises(ValueError):
        resolve_path(tmp_path, "../outside")
    file_operation(
        "builtin.fs.write", {"path": "a.txt", "content": "hello"}, tmp_path, "one"
    )
    with pytest.raises(ValueError):
        file_operation(
            "builtin.fs.write", {"path": "a.txt", "content": "bad"}, tmp_path, "two"
        )
    file_operation(
        "builtin.fs.patch",
        {"path": "a.txt", "oldText": "hello", "newText": "world"},
        tmp_path,
        "three",
    )
    assert (tmp_path / "a.txt").read_text() == "world"
    with pytest.raises(ValueError):
        file_operation(
            "builtin.fs.patch",
            {"path": "a.txt", "oldText": "missing", "newText": "bad"},
            tmp_path,
            "four",
        )
    result = file_operation("builtin.fs.delete", {"path": "a.txt"}, tmp_path, "five")
    assert result["recoverable"] and not (tmp_path / "a.txt").exists()


def archive(entries):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        for name, content in entries.items():
            z.writestr(name, content)
    return data.getvalue()


def test_zip_projection():
    value = inspect_zip(
        archive(
            {"plugin.json": '{"name":"test"}', "skills/example/SKILL.md": "# Example"}
        )
    )
    assert value["manifest"]["name"] == "test" and len(value["skills"]) == 1


@pytest.mark.parametrize("name", ["../escape.md", "C:/escape.md", "run.exe", "run.py"])
def test_zip_rejects_execution_and_traversal(name):
    with pytest.raises(ValueError):
        inspect_zip(archive({"plugin.json": '{"name":"test"}', name: "unsafe"}))


def test_mcp_secret_rules():
    with pytest.raises(ValueError):
        validate_server({"command": "npx", "env": {"API_KEY": "secret-value"}})
    assert (
        validate_server({"command": "npx", "env": {"API_KEY": "${secret:TEST_KEY}"}})[
            "transport"
        ]
        == "stdio"
    )
    assert (
        validate_server({"url": "https://example.com/mcp", "transport": "http"})[
            "transport"
        ]
        == "streamable-http"
    )


def test_schedule_modes():
    start = int(datetime.fromisoformat("2026-09-07T10:00:00+08:00").timestamp() * 1000)
    assert next_time({"type": "daily", "time": "09:00"}, start) == start + 23 * 3600000
    assert next_time({"type": "once", "at": "2026-09-07T09:00:00+08:00"}, start) == 0
    assert (
        next_time({"type": "weekly", "time": "09:00", "weekday": 0}, start)
        == start + (7 * 24 - 1) * 3600000
    )
    assert (
        next_time({"type": "cron", "expression": "0 11 * * *"}, start)
        == start + 3600000
    )
    with pytest.raises(ValueError):
        next_time({"type": "monthly", "day": 32}, start)


def test_json_and_redaction():
    assert parse_json('```json\n{"action":"final"}\n```')["action"] == "final"
    assert sanitize({"api_key": "hidden", "text": "Bearer abc.def"}) == {
        "api_key": "[REDACTED]",
        "text": "Bearer [REDACTED]",
    }


def test_mcp_single_server_wrapper():
    direct = {
        "transport": "streamable-http",
        "url": "https://learn.microsoft.com/api/mcp?maxTokenBudget=2000",
    }
    wrapped = {"mcpServers": {"microsoft-learn": direct}}
    assert validate_server(wrapped) == direct
    assert validate_server(direct) == direct
    assert (
        validate_server({"mcpServers": {"local": {"command": "npx", "args": []}}})[
            "transport"
        ]
        == "stdio"
    )
    assert (
        validate_server({"url": " https://example.com/mcp \n"})["url"]
        == "https://example.com/mcp"
    )
    assert wrapped["mcpServers"]["microsoft-learn"] == direct
    with pytest.raises(ValueError, match="敏感字段"):
        validate_server(
            {
                "mcpServers": {
                    "test": {
                        "url": "https://example.com",
                        "headers": {"Authorization": "plain-secret"},
                    }
                }
            }
        )


@pytest.mark.parametrize(
    "config,message",
    [
        ({"mcpServers": {}}, "非空对象"),
        ({"mcpServers": []}, "非空对象"),
        ({"mcpServers": {"a": {}, "b": {}}}, "导入 mcpServers JSON"),
        ({"mcpServers": {"a": None}}, "JSON 对象"),
        ({"mcpServers": {"a": {}}, "url": "https://example.com"}, "混用"),
        ({"url": "file:///tmp/a"}, "HTTP/HTTPS"),
        ({"url": None}, "字符串"),
    ],
)
def test_mcp_wrapper_errors(config, message):
    with pytest.raises(ValueError, match=message):
        validate_server(config)
