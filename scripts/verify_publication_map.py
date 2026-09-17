"""@input Existing successful map tool result and read-only MCP resource.
@output Short-lived compatible display ticket for browser verification; never mutates publication grants.
@position Non-destructive real map display smoke test. @doc-sync Update scripts/INDEX.md on changes.
"""

import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy import select
from app.db import DB, Run, ToolCall, engine
from app import extensions
from app.main import create_mcp_view
from app.config import settings


async def main():
    async with DB() as db:
        rows = (await db.execute(select(ToolCall, Run).join(Run, Run.id == ToolCall.run_id)
                                .where(ToolCall.status == "SUCCEEDED")
                                .order_by(Run.created.desc()).limit(100))).all()
        found = None
        for call, run in rows:
            cap = next((c for c in run.snapshot.get("capabilities", []) if c["id"] == call.capability_id), {})
            if cap.get("ui_uri") == "ui://cesium-map/mcp-app.html":
                found = call, cap
                break
        if not found:
            raise RuntimeError("No successful map tool result exists for display verification")
        call, cap = found
        arguments, result, server, uri = call.arguments, call.result.get("data", {}), cap["server"], cap["ui_uri"]
    resource = await extensions.resource(server, uri)
    ticket = create_mcp_view(resource, {"arguments": arguments, "result": result, "compatibility": True})
    directory = settings.data_dir / "publication-ui"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "map-ticket.json").write_text(json.dumps(ticket), encoding="utf-8")
    await engine.dispose()
    print("Created 5-minute map display ticket; published apps and versions were not modified.")


if __name__ == "__main__":
    asyncio.run(main())
