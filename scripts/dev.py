"""@input Local venv, Node/Vite, initialized database and free development ports.
@output Supervised services, readiness checks and per-service console/file logs.
@position Development launcher; never terminates pre-existing processes.
@doc-sync Update this header and scripts/INDEX.md when this file changes.
"""

import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener
import psutil

ROOT = Path(__file__).resolve().parents[1]
PORTS = {"api": 8010, "mcp-ui": 8011, "web": 5173}


def port_conflicts():
    conflicts = []
    for name, port in PORTS.items():
        with socket.socket() as sock:
            try:
                if os.name == "nt":
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                sock.bind(("127.0.0.1", port))
            except OSError:
                conflicts.append((name, port))
    return conflicts


def preflight():
    conflicts = port_conflicts()
    if conflicts:
        try:
            listeners = {
                c.laddr.port: c.pid
                for c in psutil.net_connections("tcp")
                if c.status == "LISTEN" and c.laddr.port in PORTS.values()
            }
        except psutil.Error:
            listeners = {}
        details = ", ".join(
            f"{name}: {port} (PID {listeners.get(port, 'unknown')})"
            for name, port in conflicts
        )
        raise RuntimeError(
            "Ports already occupied: "
            + details
            + ". An earlier instance may still be running at http://127.0.0.1:5173. "
            "Stop that instance with Ctrl+C before restarting; no existing process was stopped."
        )
    node = shutil.which("node")
    if not node:
        raise RuntimeError(
            "Node.js was not found on PATH. Install Node.js 20+ and reopen PowerShell."
        )
    vite = ROOT / "frontend/node_modules/vite/bin/vite.js"
    if not vite.is_file():
        raise RuntimeError("Vite is missing. Run npm ci in the frontend directory.")
    return node, vite


def commands(node, vite):
    # Launch Vite with Node directly: no npm.cmd shell/hidden-window indirection on Windows.
    return [
        (
            "api",
            [
                sys.executable,
                "-u",
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8010",
            ],
            ROOT / "backend",
        ),
        ("worker", [sys.executable, "-u", "-m", "app.worker"], ROOT / "backend"),
        (
            "mcp-ui",
            [
                sys.executable,
                "-u",
                "-m",
                "uvicorn",
                "app.app_host:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8011",
            ],
            ROOT / "backend",
        ),
        (
            "web",
            [node, str(vite), "--host", "127.0.0.1", "--port", "5173", "--strictPort"],
            ROOT / "frontend",
        ),
    ]


def pump(name, pipe, path):
    with path.open("w", encoding="utf-8") as log:
        for line in pipe:
            log.write(line)
            log.flush()
            print(f"[{name}] {line.rstrip()}", flush=True)


def track(children, owned):
    for _, child, _ in children:
        try:
            process = psutil.Process(child.pid)
            # Popen.poll prevents following a recycled PID after the child exited.
            if child.poll() is None:
                for member in [process, *process.children(recursive=True)]:
                    owned[(member.pid, member.create_time())] = member
        except psutil.NoSuchProcess:
            pass


def stop_owned(children, owned):
    track(children, owned)
    live = []
    for process in reversed(list(owned.values())):
        try:
            if process.is_running():
                process.terminate()
                live.append(process)
        except psutil.NoSuchProcess:
            pass
    _, remaining = psutil.wait_procs(live, timeout=3)
    for process in remaining:
        try:
            process.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(remaining, timeout=3)
    for _, child, _ in children:
        child.wait(timeout=5)


def check_exits(children):
    for name, child, path in children:
        code = child.poll()
        if code is not None:
            raise RuntimeError(f"{name} exited with code {code}. Log: {path}")


def ready(opener, port, path="/", expected=200):
    try:
        with opener.open(f"http://127.0.0.1:{port}{path}", timeout=0.5) as response:
            return response.status == expected
    except HTTPError as exc:
        return exc.code == expected
    except (URLError, TimeoutError, OSError):
        return False


def main(argv=None):
    # Windows consoles may use GBK; Vite prints Unicode arrows. Keep the log
    # reader alive even when the console cannot represent a character.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check ports and dependencies without starting services",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Start, verify readiness, then stop owned processes",
    )
    args = parser.parse_args(argv)
    children, threads, owned = [], [], {}
    try:
        node, vite = preflight()
        if args.check:
            print("Preflight passed: ports and Node/Vite are available.", flush=True)
            return 0
        logs = (
            ROOT
            / "data/logs"
            / (datetime.now().strftime("dev-%Y%m%d-%H%M%S-") + str(os.getpid()))
        )
        logs.mkdir(parents=True, exist_ok=True)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        print(f"Starting Agent Harness. Logs: {logs}", flush=True)
        for name, command, cwd in commands(node, vite):
            path = logs / (name + ".log")
            child = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                creationflags=flags,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            children.append((name, child, path))
            track(children, owned)
            thread = threading.Thread(
                target=pump, args=(name, child.stdout, path), daemon=True
            )
            thread.start()
            threads.append(thread)
        opener = build_opener(ProxyHandler({}))
        deadline = time.monotonic() + 45
        waiting = list(PORTS)
        while time.monotonic() < deadline:
            track(children, owned)
            check_exits(children)
            checks = {
                "api": ready(opener, 8010, "/api/v1/health"),
                "mcp-ui": ready(opener, 8011, "/view/not-a-ticket", 404),
                "web": ready(opener, 5173),
            }
            waiting = [name for name, value in checks.items() if not value]
            if not waiting:
                break
            time.sleep(0.25)
        else:
            raise RuntimeError(
                f"Readiness timeout: {', '.join(waiting)}. Check logs at {logs}; API health requires MySQL."
            )
        check_exits(children)
        print(
            "Ready: http://127.0.0.1:5173 - Ctrl+C stops only this launcher's services.",
            flush=True,
        )
        if args.smoke_test:
            return 0
        while True:
            track(children, owned)
            check_exits(children)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping launcher-owned services...", flush=True)
        return 0
    except (RuntimeError, OSError) as exc:
        print(f"Startup failed: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        stop_owned(children, owned)
        for thread in threads:
            thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
