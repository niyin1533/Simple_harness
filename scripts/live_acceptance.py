"""@input Running platform, configured DeepSeek, user-approved public MCPs and plugin ZIP.
@output Real-provider acceptance evidence under data/live-acceptance; no product-code changes.
@position Opt-in integration diagnostics. @doc-sync Update scripts/INDEX.md on changes.
"""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import sys
import time
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app import extensions
from app.config import settings
from sqlalchemy.engine import make_url

DIRECTORY = ROOT / ("data/live-acceptance-" + datetime.now().strftime("%Y%m%d"))
STATE = DIRECTORY / "state.json"
PREFIX = "[联调" + datetime.now().strftime("%m%d") + "] "


class Suite:
    def __init__(self):
        DIRECTORY.mkdir(parents=True, exist_ok=True)
        self.state = (
            json.loads(STATE.read_text(encoding="utf-8"))
            if STATE.exists()
            else {"resources": {}, "results": {}, "runs": []}
        )
        self.client = httpx.AsyncClient(
            base_url="http://127.0.0.1:8010/api/v1", timeout=150, trust_env=False
        )

    def save(self):
        STATE.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def record(self, name, status, detail):
        self.state["results"][name] = {
            "status": status,
            "detail": detail,
            "time": datetime.now().isoformat(),
        }
        self.save()
        print(
            json.dumps(
                {"test": name, "status": status, "detail": detail}, ensure_ascii=False
            ),
            flush=True,
        )

    async def request(self, path, method="GET", data=None, client=None, **kwargs):
        r = await (client or self.client).request(method, path, json=data, **kwargs)
        if not r.is_success:
            raise RuntimeError(f"{method} {path}: HTTP {r.status_code} " + r.text[:500])
        return r.json()

    async def login(self):
        credentials = dict(
            line.split("=", 1)
            for line in (ROOT / "data/initial-admin.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if "=" in line
        )
        result = await self.request("/auth/login", "POST", credentials)
        self.client.headers["X-CSRF-Token"] = result["csrf"]
        models = await self.request("/resources/model")
        model = next(
            (
                m
                for m in models
                if m["enabled"]
                and "deepseek"
                in (m["name"] + " " + m["config"].get("model", "")).lower()
            ),
            None,
        )
        if not model:
            raise RuntimeError("No enabled DeepSeek model found")
        self.state["model_id"] = model["id"]
        self.state["model_name"] = model["name"]
        self.save()
        u = make_url(settings.database_url)
        self.record(
            "infrastructure",
            "PASS",
            {
                "host": u.host,
                "port": u.port,
                "database": u.database,
                "data_dir": str(settings.data_dir),
                "model": model["name"],
                "model_id": model["id"],
            },
        )

    async def case(self, name, operation):
        try:
            self.record(name, "PASS", await operation())
        except Exception as e:
            self.record(name, "FAIL", str(e))

    async def resource(self, kind, key, **fields):
        if key in self.state["resources"]:
            rows = await self.request("/resources/" + kind)
            row = next(
                (r for r in rows if r["id"] == self.state["resources"][key]), None
            )
            if row:
                return row
        row = await self.request(
            "/resources/" + kind, "POST", {"name": PREFIX + key, **fields}
        )
        self.state["resources"][key] = row["id"]
        self.save()
        return row

    async def agent(self, key, **config):
        return await self.resource(
            "agent",
            key,
            config={
                "model_id": self.state["model_id"],
                "system_prompt": "你是联调测试助手。必须真实调用所需工具，不得假装成功；不执行无关操作。回答简洁。",
                "loop_enabled": True,
                "workspace_path": str(DIRECTORY / "workspace"),
                "permission_preset": "workspace-write",
                "limits": {
                    "max_steps": 12,
                    "max_tool_calls": 12,
                    "max_run_seconds": 240,
                    "max_consecutive_failures": 2,
                    "model_retries": 1,
                    "tool_retries": 0,
                },
                **config,
            },
        )

    async def run(
        self,
        target,
        task,
        target_type="agent",
        session_id=None,
        approval="allow",
        paths=(),
        timeout=260,
    ):
        started = await self.request(
            "/runs",
            "POST",
            {
                "target_id": target,
                "target_type": target_type,
                "task": PREFIX + task,
                "session_id": session_id,
            },
        )
        id = started["id"]
        self.state["runs"].append(id)
        self.save()
        deadline = time.monotonic() + timeout
        approvals = []
        while time.monotonic() < deadline:
            detail = await self.request("/runs/" + id)
            status = detail["run"]["status"]
            if status == "WAITING_APPROVAL":
                pending = next(
                    a for a in detail["approvals"] if a["status"] == "PENDING"
                )
                call = next(c for c in detail["calls"] if c["id"] == pending["call_id"])
                is_mcp = call["capability_id"].startswith("mcp.")
                safe = is_mcp or (
                    call["capability_id"] == "builtin.fs.write"
                    and call["arguments"].get("path") in paths
                )
                approvals.append(
                    {
                        "capability": call["capability_id"],
                        "arguments": call["arguments"],
                        "before_files": sorted(
                            p.name for p in (DIRECTORY / "workspace").iterdir()
                        ),
                    }
                )
                if approval == "cancel":
                    await self.request("/runs/" + id + "/cancel", "POST")
                elif approval == "pause":
                    await self.request("/runs/" + id + "/pause", "POST")
                    paused = await self.request("/runs/" + id)
                    assert paused["run"]["status"] == "PAUSED"
                    await self.request("/runs/" + id + "/resume", "POST")
                    approval = "allow"
                else:
                    await self.request(
                        "/approvals/" + pending["id"],
                        "POST",
                        {"approved": safe and approval == "allow"},
                    )
            elif status in {
                "SUCCEEDED",
                "FAILED",
                "CANCELLED",
                "BLOCKED",
                "NEEDS_REVIEW",
                "PAUSED",
            }:
                events = await self.request("/runs/" + id + "/events")
                evidence = {
                    "run": detail["run"],
                    "calls": detail["calls"],
                    "approvals": approvals,
                    "events": events,
                }
                (DIRECTORY / (id + ".json")).write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                return evidence
            await asyncio.sleep(1)
        await self.request("/runs/" + id + "/cancel", "POST")
        raise RuntimeError("Run timed out and cancelled: " + id)

    def summary(self, e):
        return {
            "run_id": e["run"]["id"],
            "status": e["run"]["status"],
            "answer": e["run"]["result"][:1500],
            "error": e["run"]["error"],
            "calls": [
                {"tool": c["capability_id"], "status": c["status"]} for c in e["calls"]
            ],
            "approvals": len(e["approvals"]),
        }

    async def base(self):
        workspace = DIRECTORY / "workspace"
        workspace.mkdir(exist_ok=True)
        # Generated test input, never an existing user file.
        if not (workspace / "orders.csv").exists():
            (workspace / "orders.csv").write_text(
                "order,product,quantity,price\nT001,A,2,120\nT002,B,3,80\nT003,C,1,200\n",
                encoding="utf-8",
            )

        async def model_test():
            value = await self.request(
                "/models/" + self.state["model_id"] + "/test", "POST"
            )
            return {"content": value.get("content"), "usage": value.get("usage")}

        await self.case("deepseek_connection", model_test)

        async def direct():
            e = await self.run(
                self.state["model_id"],
                "计算120*2+80*3+200，只回答数字。",
                target_type="model",
            )
            assert e["run"]["status"] == "SUCCEEDED" and "680" in e["run"]["result"], (
                self.summary(e)
            )
            self.state["chat_session"] = e["run"]["session_id"]
            self.save()
            return self.summary(e)

        await self.case("deepseek_direct_chat", direct)
        knowledge = await self.resource(
            "knowledge",
            "订单规则",
            content="虚构验收规则：总金额达到600元全部九折；专用规则码 RULE-927。",
        )
        prompt = await self.resource(
            "prompt",
            "报告格式",
            content="报告必须包含订单数、数量、原价、折后价、规则码，末尾写 AG-TEST-01。",
        )
        skill = await self.resource(
            "skill",
            "订单分析",
            content="# 订单分析\n先列目录、读取 orders.csv；按规则计算，再根据用户要求写报告。工具失败不能宣称成功。",
        )
        agent = await self.agent(
            "订单助手",
            knowledge_ids=[knowledge["id"]],
            prompt_ids=[prompt["id"]],
            skill_ids=[skill["id"]],
        )

        async def order():
            e = await self.run(
                agent["id"],
                "先用文件工具列目录并读取orders.csv，直接计算，无需执行命令。依据绑定规则写report.md和result.json，不覆盖现有文件。JSON字段为order_count,quantity_total,original_total,discounted_total,rule_code。",
                paths=["report.md", "result.json"],
            )
            assert e["run"]["status"] == "SUCCEEDED", self.summary(e)
            result = json.loads((workspace / "result.json").read_text(encoding="utf-8"))
            assert result == {
                "order_count": 3,
                "quantity_total": 6,
                "original_total": 680,
                "discounted_total": 612,
                "rule_code": "RULE-927",
            }, result
            assert (workspace / "report.md").is_file() and len(e["approvals"]) == 2, (
                self.summary(e)
            )
            assert "AG-TEST-01" in e["run"]["result"], self.summary(e)
            return {**self.summary(e), "file_result": result}

        await self.case("agent_order_files_approval", order)

        async def reject():
            e = await self.run(
                agent["id"],
                "只调用builtin.fs.write创建rejected.txt，内容为rejected。",
                approval="reject",
                paths=["rejected.txt"],
            )
            assert (
                e["run"]["status"] == "BLOCKED"
                and not (workspace / "rejected.txt").exists()
            ), self.summary(e)
            return self.summary(e)

        await self.case("reject_approval", reject)

        async def cancel():
            e = await self.run(
                agent["id"],
                "只调用builtin.fs.write创建cancelled.txt，内容cancelled。",
                approval="cancel",
                paths=["cancelled.txt"],
            )
            assert (
                e["run"]["status"] == "CANCELLED"
                and not (workspace / "cancelled.txt").exists()
            ), self.summary(e)
            return self.summary(e)

        await self.case("cancel_pending_approval", cancel)

        async def pause():
            e = await self.run(
                agent["id"],
                "只调用builtin.fs.write创建paused.txt，内容resumed。",
                approval="pause",
                paths=["paused.txt"],
            )
            assert (
                e["run"]["status"] == "SUCCEEDED"
                and (workspace / "paused.txt").is_file()
            ), self.summary(e)
            return self.summary(e)

        await self.case("pause_resume_pending_approval", pause)
        readonly = await self.agent("只读助手", permission_preset="read-only")

        async def boundary():
            e = await self.run(
                readonly["id"],
                "必须调用builtin.fs.read读取../outside.txt，不要自行猜测内容。",
            )
            errors = json.dumps([c["result"] for c in e["calls"]], ensure_ascii=False)
            assert e["calls"] and "路径超出授权工作目录" in errors, self.summary(e)
            return self.summary(e)

        await self.case("workspace_boundary", boundary)

        async def ro():
            e = await self.run(
                readonly["id"], "调用builtin.fs.write写入readonly.txt，内容test。"
            )
            assert (
                not (workspace / "readonly.txt").exists()
                and e["run"]["status"] == "FAILED"
            ), self.summary(e)
            return self.summary(e)

        await self.case("read_only_write_denied", ro)

    async def integration_extensions(self):
        mcp = await self.resource(
            "mcp",
            "Microsoft Learn",
            enabled=False,
            config={
                "transport": "streamable-http",
                "url": "https://learn.microsoft.com/api/mcp?maxTokenBudget=2000",
            },
        )

        async def discover():
            value = await self.request("/mcp/" + mcp["id"] + "/discover", "POST")
            self.state["learn_discovery"] = value
            self.save()
            names = [t["name"] for t in value["tools"]]
            assert set(
                [
                    "microsoft_docs_search",
                    "microsoft_docs_fetch",
                    "microsoft_code_sample_search",
                ]
            ).issubset(names), names
            return {"tools": names}

        await self.case("learn_mcp_discovery", discover)
        if "learn_discovery" in self.state:
            tools = [
                t
                for t in await self.request("/resources/tool")
                if t["parent_id"] == mcp["id"]
            ]
            agent = await self.agent("微软文档助手", tool_ids=[t["id"] for t in tools])
            tasks = {
                "microsoft_docs_search": "用microsoft_docs_search搜索Azure Blob Storage Python入门，查询参数query设为Azure Blob Storage Python quickstart；返回两个真实文档链接。",
                "microsoft_docs_fetch": "用microsoft_docs_fetch读取https://learn.microsoft.com/en-us/azure/storage/blobs/storage-quickstart-blobs-python，简述文档内容并给出原链接。",
                "microsoft_code_sample_search": "用microsoft_code_sample_search搜索Azure Blob Storage upload blob，language设为python，展示一个实际返回的代码示例摘要和来源。",
            }
            for tool_name, task in tasks.items():

                async def call(task=task, tool_name=tool_name):
                    e = await self.run(agent["id"], task)
                    ids = {
                        t["id"] for t in tools if t["config"]["tool_name"] == tool_name
                    }
                    matched = [c for c in e["calls"] if c["capability_id"] in ids]
                    assert (
                        e["run"]["status"] == "SUCCEEDED"
                        and matched
                        and all(c["status"] == "SUCCEEDED" for c in matched)
                    ), self.summary(e)
                    return self.summary(e)

                await self.case("learn_" + tool_name, call)
        archive = (
            ROOT.parent / "fanwu/test-packages/fanwu-mcp-app-map-extension-1.0.0.zip"
        )

        async def install():
            raw = archive.read_bytes()
            pre = await self.request(
                "/extensions/preflight",
                "POST",
                files={"file": (archive.name, raw, "application/zip")},
            )
            installed = await self.request(
                "/extensions/install",
                "POST",
                files={"file": (archive.name, raw, "application/zip")},
            )
            self.state["plugin_id"] = installed["id"]
            self.save()
            rows = [
                r
                for k in ["mcp", "skill"]
                for r in await self.request("/resources/" + k)
                if r["parent_id"] == installed["id"]
            ]
            assert len(rows) == 2 and not any(r["enabled"] for r in rows)
            self.state["map_server"] = next(r for r in rows if r["kind"] == "mcp")
            self.state["map_skill"] = next(r for r in rows if r["kind"] == "skill")
            self.save()
            return {
                "plugin_id": installed["id"],
                "default_disabled": True,
                "projected": [(r["kind"], r["name"]) for r in rows],
                "manifest": pre["manifest"],
            }

        await self.case("map_plugin_preflight_install", install)
        if "map_server" not in self.state:
            return
        await self.request(
            "/extensions/" + self.state["plugin_id"] + "/status",
            "POST",
            {"enabled": True},
        )
        server = self.state["map_server"]

        async def map_discover():
            value = await self.request("/mcp/" + server["id"] + "/discover", "POST")
            self.state["map_discovery"] = value
            self.save()
            return value

        await self.case("map_mcp_discovery", map_discover)
        if "map_discovery" in self.state:
            tools = [
                t
                for t in await self.request("/resources/tool")
                if t["parent_id"] == server["id"]
            ]
            agent = await self.agent(
                "地图助手",
                tool_ids=[t["id"] for t in tools],
                skill_ids=[self.state["map_skill"]["id"]],
            )

            async def map_run():
                e = await self.run(
                    agent["id"],
                    "请调用地图工具展示北京天安门，使用明确给定的真实坐标：纬度39.9087，经度116.3975。标题为天安门联调。仅展示地图，不调用其他工具。",
                )
                self.state["map_run_id"] = e["run"]["id"]
                self.state["map_agent_id"] = agent["id"]
                self.save()
                assert e["run"]["status"] == "SUCCEEDED" and any(
                    c["capability_id"].startswith("mcp.") and c["status"] == "SUCCEEDED"
                    for c in e["calls"]
                ), self.summary(e)
                return self.summary(e)

            await self.case("map_agent_tool_call", map_run)

            async def resource():
                tool = next(t for t in tools if t["config"].get("ui_uri"))
                data = await self.request(
                    "/mcp/" + server["id"] + "/resource",
                    params={"uri": tool["config"]["ui_uri"]},
                )
                self.state["map_ui_uri"] = tool["config"]["ui_uri"]
                self.save()
                (DIRECTORY / "map-resource.json").write_text(
                    json.dumps(data, ensure_ascii=False), encoding="utf-8"
                )
                return {
                    "uri": tool["config"]["ui_uri"],
                    "contents": [
                        {
                            "mimeType": c.get("mimeType"),
                            "length": len(c.get("text", "")),
                            "meta": c.get("_meta"),
                        }
                        for c in data.get("contents", [])
                    ],
                }

            await self.case("map_ui_resource", resource)

    async def governance(self):
        workspace = DIRECTORY / "workspace"
        workspace.mkdir(exist_ok=True)
        agent = await self.agent(
            "记忆助手", memory_enabled=True, memory_scopes=["agent"]
        )
        memory = await self.request(
            "/memories",
            "POST",
            {
                "agent_id": agent["id"],
                "content": PREFIX
                + "本次验收代号是 BLUE-WHALE-927，回答应使用这个代号。",
            },
        )
        self.state["test_memory_id"] = memory["id"]
        self.save()

        async def recall():
            e = await self.run(
                agent["id"],
                "本次验收的代号是什么？仅根据已提供的记忆回答，不调用工具。",
            )
            assert (
                e["run"]["status"] == "SUCCEEDED"
                and "BLUE-WHALE-927" in e["run"]["result"]
            ), self.summary(e)
            assert any(
                memory["id"] in json.dumps(ev["data"])
                for ev in e["events"]
                if ev["name"] == "MEMORY_RETRIEVED"
            )
            return self.summary(e)

        await self.case("memory_cross_session_recall", recall)
        await self.request("/memories/" + memory["id"], "PUT", {"enabled": False})

        async def disabled():
            e = await self.run(
                agent["id"], "本次验收的代号是什么？不知道请明确说不知道，不调用工具。"
            )
            assert "BLUE-WHALE-927" not in e["run"]["result"], self.summary(e)
            return self.summary(e)

        await self.case("memory_disable_exclusion", disabled)

        async def compact():
            session = None
            for task in [
                "记住本次上下文测试编号 CTX-927。只需确认。",
                "再记住报告是星期五交付。只需确认。",
                "报告颜色是蓝色。只需确认。",
                "只回复准备好了。",
            ]:
                e = await self.run(
                    self.state["model_id"],
                    task,
                    target_type="model",
                    session_id=session,
                )
                assert e["run"]["status"] == "SUCCEEDED", self.summary(e)
                session = e["run"]["session_id"]
            result = await self.request("/sessions/" + session + "/compact", "POST")
            assert result.get("compacted"), result
            e = await self.run(
                self.state["model_id"],
                "之前约定的上下文测试编号是什么？",
                target_type="model",
                session_id=session,
            )
            assert "CTX-927" in e["run"]["result"], self.summary(e)
            history = await self.request("/sessions/" + session + "/messages")
            assert len(history["messages"]) == 10 and len(history["checkpoints"]) >= 1
            return {
                "summary": result,
                "message_count": len(history["messages"]),
                "run": self.summary(e),
            }

        await self.case("context_compaction_real_model", compact)

        async def schedule():
            target = await self.agent("计划助手", loop_enabled=False)
            future = (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat()
            s = await self.request(
                "/schedules",
                "POST",
                {
                    "name": PREFIX + "一次计划",
                    "agent_id": target["id"],
                    "task": "仅回复 SCHEDULE-927。",
                    "config": {
                        "type": "once",
                        "at": future,
                        "timezone": "Asia/Shanghai",
                    },
                },
            )
            self.state["schedule_id"] = s["id"]
            self.save()
            try:
                for _ in range(90):
                    rows = await self.request("/schedules")
                    row = next(r for r in rows if r["id"] == s["id"])
                    if row.get("last_run"):
                        detail = await self.request("/runs/" + row["last_run"])
                        if detail["run"]["status"] == "SUCCEEDED":
                            self.state["runs"].append(row["last_run"])
                            self.save()
                            assert (
                                not row["enabled"]
                                and "SCHEDULE-927" in detail["run"]["result"]
                            )
                            return {"schedule": row, "run": detail["run"]}
                    await asyncio.sleep(1)
                raise RuntimeError("Scheduled run not completed")
            finally:
                await self.request("/schedules/" + s["id"], "PUT", {"enabled": False})

        await self.case("one_shot_scheduler", schedule)

        async def isolation():
            password = secrets.token_urlsafe(18)
            name = "acceptance_" + secrets.token_hex(4)
            user = await self.request(
                "/users",
                "POST",
                {"username": name, "password": password, "admin": False},
            )
            self.state["isolation_user_id"] = user["id"]
            self.save()
            try:
                async with httpx.AsyncClient(
                    base_url=str(self.client.base_url), trust_env=False
                ) as client:
                    result = await self.request(
                        "/auth/login",
                        "POST",
                        {"username": name, "password": password},
                        client=client,
                    )
                    client.headers["X-CSRF-Token"] = result["csrf"]
                    statuses = {}
                    for path, method, data in [
                        ("/runs/" + self.state["runs"][0], "GET", None),
                        ("/memories/" + memory["id"], "PUT", {"content": "forbidden"}),
                        ("/resources/model", "POST", {"name": "forbidden"}),
                    ]:
                        r = await client.request(method, path, json=data)
                        statuses[path] = r.status_code
                    assert list(statuses.values()) == [404, 404, 403], statuses
                    assert await self.request("/sessions", client=client) == []
                    assert await self.request("/memories", client=client) == []
                    return statuses
            finally:
                await self.request("/users/" + user["id"], "PUT", {"active": False})

        await self.case("cross_user_isolation", isolation)

    async def independent(self):
        """Continue independent checks after the agent-create endpoint fails."""
        self.record(
            "agent_creation",
            "FAIL",
            "POST /resources/agent returned 500 twice; API log confirms query-triggered autoflush inserting Resource.name=NULL (MySQL 1048).",
        )
        for name in [
            "agent_order_files_approval",
            "reject_approval",
            "cancel_pending_approval",
            "pause_resume_pending_approval",
            "workspace_boundary",
            "read_only_write_denied",
            "memory_cross_session_recall",
            "one_shot_scheduler",
            "learn_agent_tool_calls",
            "map_agent_tool_call",
        ]:
            self.record(
                name,
                "BLOCKED",
                "Agent creation fails; no database seeding or product patch used to bypass the failure.",
            )
        self.record(
            "prompt_skill_knowledge_creation",
            "PASS",
            {"resources": self.state["resources"]},
        )
        config = {
            "transport": "streamable-http",
            "url": "https://learn.microsoft.com/api/mcp?maxTokenBudget=2000",
        }
        for name, args in {
            "microsoft_docs_search": {"query": "Azure Blob Storage Python quickstart"},
            "microsoft_docs_fetch": {
                "url": "https://learn.microsoft.com/en-us/azure/storage/blobs/storage-quickstart-blobs-python"
            },
            "microsoft_code_sample_search": {
                "query": "Azure Blob Storage upload blob",
                "language": "python",
            },
        }.items():

            async def call(name=name, args=args):
                result = await extensions.call(config, name, args)
                (DIRECTORY / (name + ".json")).write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                assert not result.get("isError") and result.get("content"), result
                return {
                    "layer": "backend MCP adapter, NOT an agent run",
                    "content_blocks": len(result["content"]),
                    "sample": str(result["content"])[:700],
                }

            await self.case(name + "_adapter", call)
        archive = (
            ROOT.parent / "fanwu/test-packages/fanwu-mcp-app-map-extension-1.0.0.zip"
        )

        async def install():
            raw = archive.read_bytes()
            pre = await self.request(
                "/extensions/preflight",
                "POST",
                files={"file": (archive.name, raw, "application/zip")},
            )
            installed = await self.request(
                "/extensions/install",
                "POST",
                files={"file": (archive.name, raw, "application/zip")},
            )
            self.state["plugin_id"] = installed["id"]
            self.save()
            rows = [
                r
                for k in ["mcp", "skill"]
                for r in await self.request("/resources/" + k)
                if r["parent_id"] == installed["id"]
            ]
            self.state["map_server"] = next(r for r in rows if r["kind"] == "mcp")
            self.state["map_skill"] = next(r for r in rows if r["kind"] == "skill")
            self.save()
            assert len(rows) == 2 and not any(r["enabled"] for r in rows)
            return {
                "plugin_id": installed["id"],
                "default_disabled": True,
                "projected": [(r["kind"], r["name"]) for r in rows],
                "manifest": pre["manifest"],
            }

        await self.case("map_plugin_preflight_install", install)
        if "map_server" in self.state:
            await self.request(
                "/extensions/" + self.state["plugin_id"] + "/status",
                "POST",
                {"enabled": True},
            )
            server = self.state["map_server"]

            async def discovery():
                result = await self.request(
                    "/mcp/" + server["id"] + "/discover", "POST"
                )
                self.state["map_discovery"] = result
                self.save()
                return result

            await self.case("map_mcp_discovery", discovery)

        async def compact():
            session = None
            for task in [
                "记住上下文编号 CTX-927，报告星期五交付。只回复确认。",
                "报告颜色为蓝色。只回复确认。",
                "报告语言为中文。只回复确认。",
                "只回复准备好了。",
            ]:
                e = await self.run(
                    self.state["model_id"],
                    task,
                    target_type="model",
                    session_id=session,
                )
                assert e["run"]["status"] == "SUCCEEDED", self.summary(e)
                session = e["run"]["session_id"]
            result = await self.request("/sessions/" + session + "/compact", "POST")
            e = await self.run(
                self.state["model_id"],
                "之前约定的上下文编号是什么？",
                target_type="model",
                session_id=session,
            )
            history = await self.request("/sessions/" + session + "/messages")
            assert result.get("compacted") and "CTX-927" in e["run"]["result"], (
                self.summary(e)
            )
            assert len(history["messages"]) == 10 and len(history["checkpoints"]) >= 1
            return {
                "compaction": result,
                "message_count": len(history["messages"]),
                "run": self.summary(e),
            }

        await self.case("context_compaction_real_model", compact)

        async def memories():
            memory = await self.request(
                "/memories",
                "POST",
                {"scope": "global", "content": PREFIX + "全局记忆 CRUD 验收 MEM-927"},
            )
            self.state["test_memory_id"] = memory["id"]
            self.save()
            updated = await self.request(
                "/memories/" + memory["id"],
                "PUT",
                {"content": PREFIX + "更新 MEM-928", "enabled": False},
            )
            assert not updated["enabled"] and "MEM-928" in updated["content"], updated
            return {"id": memory["id"], "created_updated_disabled": True}

        await self.case("memory_management", memories)

        async def isolation():
            password = secrets.token_urlsafe(18)
            name = "acceptance_" + secrets.token_hex(4)
            user = await self.request(
                "/users",
                "POST",
                {"username": name, "password": password, "admin": False},
            )
            self.state["isolation_user_id"] = user["id"]
            self.save()
            try:
                async with httpx.AsyncClient(
                    base_url=str(self.client.base_url), trust_env=False
                ) as client:
                    result = await self.request(
                        "/auth/login",
                        "POST",
                        {"username": name, "password": password},
                        client=client,
                    )
                    client.headers["X-CSRF-Token"] = result["csrf"]
                    statuses = {}
                    for path, method, data in [
                        ("/runs/" + self.state["runs"][0], "GET", None),
                        ("/resources/model", "POST", {"name": "forbidden"}),
                    ]:
                        r = await client.request(method, path, json=data)
                        statuses[path] = r.status_code
                    assert list(statuses.values()) == [404, 403], statuses
                    assert await self.request("/sessions", client=client) == []
                    assert await self.request("/memories", client=client) == []
                    return statuses
            finally:
                await self.request("/users/" + user["id"], "PUT", {"active": False})

        await self.case("cross_user_isolation", isolation)

    async def map_display(self):
        server = self.state["map_server"]
        arguments = {
            "west": 116.3875,
            "south": 39.8987,
            "east": 116.4075,
            "north": 39.9187,
            "label": "天安门联调",
        }
        result = await extensions.call(server["config"], "show-map", arguments)
        (DIRECTORY / "map-tool-result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        assert not result.get("isError"), result
        self.record(
            "map_tool_adapter",
            "PASS",
            {
                "layer": "backend adapter, not agent orchestration",
                "arguments": arguments,
                "result": result,
            },
        )
        uri = "ui://cesium-map/mcp-app.html"
        resource = await self.request(
            "/mcp/" + server["id"] + "/resource", params={"uri": uri}
        )
        (DIRECTORY / "map-resource.json").write_text(
            json.dumps(resource, ensure_ascii=False), encoding="utf-8"
        )
        self.record(
            "map_ui_resource",
            "PASS",
            {
                "contents": [
                    {
                        "mimeType": c.get("mimeType"),
                        "length": len(c.get("text", "")),
                        "meta": c.get("_meta"),
                    }
                    for c in resource["contents"]
                ]
            },
        )
        view = await self.request(
            "/mcp/" + server["id"] + "/view",
            "POST",
            {
                "uri": uri,
                "arguments": arguments,
                "result": result,
                "compatibility": True,
            },
        )
        self.state["map_view"] = view
        self.save()
        self.record("map_view_ticket", "PASS", {"mode": view["mode"]})

    async def finish(self):
        # Disable only created resources, preserve task evidence and user's original model/configuration.
        browser_file = DIRECTORY / "map-browser.json"
        if browser_file.exists():
            browser = json.loads(browser_file.read_text(encoding="utf-8"))
            tiles = [
                r
                for r in browser.get("network", [])
                if "tile.openstreetmap" in r["url"] and r["status"] == 200
            ]
            workers = [
                r for r in browser.get("network", []) if "/Cesium/Workers/" in r["url"]
            ]
            self.record(
                "map_browser_render",
                "PASS"
                if tiles
                and workers
                and all(r["status"] == 200 for r in workers)
                and any(f["canvas"] for f in browser["frames"])
                else "FAIL",
                {
                    "tiles_loaded": len(tiles),
                    "workers_loaded": len(workers),
                    "warnings": browser["errors"],
                    "evidence": "map-browser.json / map-browser.png; screenshot visually verified",
                },
            )
        for key, id in self.state["resources"].items():
            if key == "Microsoft Learn":
                await self.request(
                    "/extensions/" + id + "/status", "POST", {"enabled": False}
                )
            else:
                for kind in ["agent", "knowledge", "prompt", "skill"]:
                    rows = await self.request("/resources/" + kind)
                    r = next((r for r in rows if r["id"] == id), None)
                    if r:
                        await self.request(
                            "/resources/" + kind + "/" + id,
                            "PUT",
                            {
                                k: r[k]
                                for k in [
                                    "name",
                                    "description",
                                    "content",
                                    "config",
                                    "version",
                                ]
                            }
                            | {"enabled": False},
                        )
                        break
        if self.state.get("plugin_id"):
            await self.request(
                "/extensions/" + self.state["plugin_id"] + "/status",
                "POST",
                {"enabled": False},
            )
        if self.state.get("test_memory_id"):
            await self.request("/memories/" + self.state["test_memory_id"], "DELETE")
        created = set(self.state["resources"].values()) | {
            self.state.get("plugin_id"),
            self.state.get("map_server", {}).get("id"),
            self.state.get("map_skill", {}).get("id"),
        }
        for kind in ["agent", "knowledge", "prompt", "skill", "mcp", "plugin", "tool"]:
            for row in await self.request("/resources/" + kind):
                if row["id"] in created or row.get("parent_id") in created:
                    assert not row["enabled"], (kind, row["id"])
        models = await self.request("/resources/model")
        assert next(m for m in models if m["id"] == self.state["model_id"])["enabled"]
        self.record(
            "cleanup",
            "PASS",
            "Test resources disabled; test memory deleted; task/file evidence retained. Original model unchanged.",
        )


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase",
        choices=[
            "base",
            "extensions",
            "governance",
            "independent",
            "map_display",
            "finish",
        ],
    )
    args = parser.parse_args()
    suite = Suite()
    try:
        await suite.login()
        await getattr(
            suite,
            "integration_extensions" if args.phase == "extensions" else args.phase,
        )()
    finally:
        await suite.client.aclose()


if __name__ == "__main__":
    for stream in [sys.stdout, sys.stderr]:
        stream.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(main())
