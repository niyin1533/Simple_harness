"""@input Running platform, configured models and approved map/weight fixtures.
@output Isolated real-provider regression evidence; existing memories are not changed.
@position Opt-in migration acceptance. @doc-sync Update scripts/INDEX.md on changes.
"""

import asyncio
import json
import sys
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from sqlalchemy import select, delete
from app.db import DB, User, Preference, Memory, engine, uid
from app.memory_governance import govern, review

OUT = ROOT / "data" / "fix-verification-20260916"
OUT.mkdir(exist_ok=True)


async def memory():
    test_user = uid()
    try:
        async with DB.begin() as db:
            admin = await db.scalar(select(User).where(User.username == "admin"))
            pref = await db.get(Preference, admin.id)
            db.add(
                User(
                    id=test_user,
                    username="memory-regression-" + test_user,
                    password="disabled",
                    active=False,
                )
            )
            db.add(
                Preference(user_id=test_user, config=pref.config, secret=pref.secret)
            )
        evidence = []
        for index, request in enumerate(
            [
                "请记住我的名字是小明，以后称呼我小明。",
                "我的名字是小明，以后称呼我小明。",
                "请更正，我现在希望你叫我小红，姓名仍然是小明。",
            ]
        ):
            async with DB.begin() as db:
                outcome = await govern(
                    db, test_user, "regression", request, explicit=index != 1
                )
                rows = (
                    await db.scalars(select(Memory).where(Memory.user_id == test_user))
                ).all()
                evidence.append(
                    {
                        "outcome": outcome,
                        "memories": [
                            {
                                "content": r.content,
                                "meta": r.meta,
                                "confirmed": r.confirmed,
                            }
                            for r in rows
                        ],
                    }
                )
                assert outcome["status"] == "success", outcome
                assert len(rows) == 1, "Duplicate stable-slot memory"
        async with DB() as db:
            advice = await review(db, admin.id)
            evidence.append(
                {
                    "existing_user_review_suggestions": len(advice["suggestions"]),
                    "applied": False,
                }
            )
        (OUT / "memory.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            "MEMORY PASS: create/repeat/update each leave one memory; real review succeeded",
            flush=True,
        )
    finally:
        async with DB.begin() as db:
            for cls in [Memory, Preference]:
                await db.execute(delete(cls).where(cls.user_id == test_user))
            await db.execute(delete(User).where(User.id == test_user))
        await engine.dispose()


async def api_phase(phase):
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8010/api/v1", timeout=180, trust_env=False
    ) as client:

        async def req(path, method="GET", data=None):
            r = await client.request(method, path, json=data)
            r.raise_for_status()
            return r.json()

        credentials = dict(
            line.split("=", 1)
            for line in (ROOT / "data/initial-admin.txt").read_text().splitlines()
            if "=" in line
        )
        login = await req("/auth/login", "POST", credentials)
        client.headers["X-CSRF-Token"] = login["csrf"]
        if phase == "map":
            models = await req("/resources/model")
            model = next(
                m
                for m in models
                if m["enabled"] and "deepseek" in m["config"].get("model", "")
            )
            tool = "mcp.86e1ac9e-f4f3-4583-8ea5-7e62d7993388.4bdea8d035cb63fa"
            agent = await req(
                "/resources/agent",
                "POST",
                {
                    "name": "[修复验收] 地图实际任务",
                    "config": {
                        "model_id": model["id"],
                        "system_prompt": "请按用户要求实际调用 show-map，依据真实结果回答。不要调用其他工具。",
                        "tool_ids": [tool],
                        "memory_enabled": False,
                        "permission_preset": "workspace-write",
                    },
                },
            )
            try:
                for i in range(3):
                    run = await req(
                        "/runs",
                        "POST",
                        {
                            "target_id": agent["id"],
                            "task": "请实际调用 show-map：west=116.3875,south=39.8987,east=116.4075,north=39.9187,label=天安门验收。",
                        },
                    )
                    for _ in range(180):
                        detail = await req("/runs/" + run["id"])
                        if detail["run"]["status"] == "WAITING_APPROVAL":
                            for a in detail["approvals"]:
                                if a["status"] == "PENDING":
                                    call = next(
                                        c
                                        for c in detail["calls"]
                                        if c["id"] == a["call_id"]
                                    )
                                    await req(
                                        "/approvals/" + a["id"],
                                        "POST",
                                        {"approved": call["capability_id"] == tool},
                                    )
                        if detail["run"]["status"] in {
                            "SUCCEEDED",
                            "FAILED",
                            "CANCELLED",
                            "BLOCKED",
                        }:
                            break
                        await asyncio.sleep(1)
                    calls = [c for c in detail["calls"] if c["capability_id"] == tool]
                    (OUT / f"map-run-{i}.json").write_text(
                        json.dumps(
                            {
                                "id": run["id"],
                                "status": detail["run"]["status"],
                                "calls": calls,
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    assert calls and all(c["status"] == "SUCCEEDED" for c in calls), (
                        "Map tool failed; inspect evidence"
                    )
                    assert detail["run"]["status"] == "SUCCEEDED", detail["run"][
                        "error"
                    ]
                    print("MAP TASK PASS", i + 1, run["id"], flush=True)
                call = calls[-1]
                view = await req(
                    "/mcp/86e1ac9e-f4f3-4583-8ea5-7e62d7993388/view",
                    "POST",
                    {
                        "uri": "ui://cesium-map/mcp-app.html",
                        "arguments": call["arguments"],
                        "result": call["result"]["data"],
                        "compatibility": True,
                    },
                )
                (OUT / "map-view.json").write_text(json.dumps(view), encoding="utf-8")
            finally:
                await req(
                    "/resources/agent/" + agent["id"],
                    "PUT",
                    {**agent, "enabled": False},
                )
        elif phase == "view":
            call = json.loads((OUT / "map-run-2.json").read_text(encoding="utf-8"))[
                "calls"
            ][-1]
            view = await req(
                "/mcp/86e1ac9e-f4f3-4583-8ea5-7e62d7993388/view",
                "POST",
                {
                    "uri": "ui://cesium-map/mcp-app.html",
                    "arguments": call["arguments"],
                    "result": call["result"]["data"],
                    "compatibility": True,
                },
            )
            (OUT / "map-view.json").write_text(json.dumps(view), encoding="utf-8")
            print("MAP VIEW TICKET PASS", flush=True)
        elif phase == "deployment":
            id = "2e32d764-e9e6-4b0f-a730-c4cfc8101fdd"
            rows = await req("/deployments")
            row = next(r for r in rows if r["id"] == id)
            if row["status"] != "RUNNING":
                await req("/deployments/" + id + "/start", "POST", {})
            for _ in range(100):
                row = next(r for r in await req("/deployments") if r["id"] == id)
                if row["status"] in {"RUNNING", "FAILED"}:
                    break
                await asyncio.sleep(1)
            assert row["status"] == "RUNNING", row.get("error")
            sample = ROOT / ".venv-yolo/Lib/site-packages/ultralytics/assets/bus.jpg"
            with sample.open("rb") as image:
                response = await client.post(
                    "/uploads/attachment",
                    files={"file": ("regression-bus.jpg", image, "image/jpeg")},
                )
                response.raise_for_status()
                artifact = response.json()
            detected = await req(
                "/deployments/" + id + "/test",
                "POST",
                {"artifact_id": artifact["id"], "path": "/detect"},
            )
            (OUT / "inference.json").write_text(
                json.dumps(detected, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print("DEPLOYMENT PASS", id, row["port"], flush=True)
            (OUT / "deployment.json").write_text(
                json.dumps({"id": id, "status": row["status"], "port": row["port"]}),
                encoding="utf-8",
            )


if __name__ == "__main__":
    asyncio.run(memory() if sys.argv[1] == "memory" else api_phase(sys.argv[1]))
