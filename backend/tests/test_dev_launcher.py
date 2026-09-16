"""@input Development launcher and local sockets. @output Startup diagnostic regressions.
@position Launcher tests without a database or service shutdown. @doc-sync Update INDEX.md on changes.
"""

import importlib.util
import io
from pathlib import Path
import socket
from types import SimpleNamespace
import pytest

spec = importlib.util.spec_from_file_location(
    "dev_launcher", Path(__file__).resolve().parents[2] / "scripts/dev.py"
)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_conflict_reports_port_without_stopping_listener(monkeypatch):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        monkeypatch.setattr(launcher, "PORTS", {"test-api": port})
        monkeypatch.setattr(launcher.psutil, "net_connections", lambda _: [])
        with pytest.raises(RuntimeError, match=f"test-api: {port}"):
            launcher.preflight()
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass


def test_frontend_uses_node_and_strict_port():
    name, command, _ = launcher.commands("node-test", "vite-test")[-1]
    assert name == "web" and command[:2] == ["node-test", "vite-test"]
    assert "--strictPort" in command and not any("npm.cmd" in part for part in command)


def test_service_failure_identifies_name_exit_code_and_log():
    child = SimpleNamespace(poll=lambda: 7)
    with pytest.raises(RuntimeError, match=r"worker exited with code 7.*worker.log"):
        launcher.check_exits([("worker", child, Path("worker.log"))])


def test_console_encoding_and_utf8_log(tmp_path, monkeypatch):
    output = io.BytesIO()
    console = io.TextIOWrapper(output, encoding="gbk")
    monkeypatch.setattr(launcher.sys, "stdout", console)
    monkeypatch.setattr(launcher, "preflight", lambda: ("node", "vite"))
    assert launcher.main(["--check"]) == 0
    launcher.pump("web", io.StringIO("➜ ready\n"), tmp_path / "web.log")
    console.flush()
    assert "[web] ? ready" in output.getvalue().decode("gbk")
    assert (tmp_path / "web.log").read_text(encoding="utf-8") == "➜ ready\n"
