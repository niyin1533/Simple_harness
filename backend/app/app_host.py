"""@input Expiring UI tickets created by the authenticated API. @output Cross-origin MCP App views.
@position Separate-origin display host with opt-in Cesium compatibility; no business API bridge.
@doc-sync Update INDEX.md on changes.
"""

import html
import json
import re
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from .config import settings
from .db import now

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount(
    "/Cesium",
    StaticFiles(directory=Path(__file__).resolve().parents[1] / "vendor/cesium"),
    name="cesium",
)


@app.get("/view/{ticket}", response_class=HTMLResponse)
async def view(ticket: str):
    if not re.fullmatch("[a-f0-9]{64}", ticket):
        raise HTTPException(404)
    path = settings.data_dir / "app-views" / (ticket + ".json")
    if not path.is_file():
        raise HTTPException(404)
    value = json.loads(path.read_text(encoding="utf-8"))
    if value["expires"] < now():
        path.unlink(missing_ok=True)
        raise HTTPException(410)
    # Compatibility is explicitly authorized per ticket, never controlled by untrusted HTML.
    # The display origin must remain different from the business frontend/API origins.
    compatibility = value.get("compatibility") is True
    origins = value.get("resource_domains", [])
    safe = []
    for origin in origins:
        if re.fullmatch(r"https://(?:\*\.)?[a-zA-Z0-9.-]+(?::[0-9]{1,5})?", origin):
            safe.append(origin)
    document_html = value["html"]
    local_cesium = compatibility and bool(
        re.search(
            r"https://cesium\.com/downloads/cesiumjs/releases/[^/]+/Build/Cesium",
            document_html,
        )
    )
    connect = list(value.get("connect_domains", []))
    bootstrap = ""
    if local_cesium:
        document_html = re.sub(
            r"https://cesium\.com/downloads/cesiumjs/releases/[^/]+/Build/Cesium",
            "/Cesium",
            document_html,
        )
        # Same fallback as the original Fanwu compatibility mode, not an open proxy.
        document_html = document_html.replace(
            "https://tile.openstreetmap.org/", "https://tile.openstreetmap.de/"
        )
        safe.extend(["'self'", "https://tile.openstreetmap.de"])
        connect.extend(["'self'", "blob:", "https://tile.openstreetmap.de"])
        bootstrap = (
            "<script>"
            + Path(__file__).with_name("mcp_compat.js").read_text(encoding="utf-8")
            + "</script>"
        )
    external = " ".join(safe)
    dynamic = " 'unsafe-eval' 'wasm-unsafe-eval'" if compatibility else ""
    policy = (
        "default-src 'none'; script-src 'unsafe-inline' "
        + dynamic
        + " "
        + external
        + "; style-src 'unsafe-inline' "
        + external
        + "; img-src data: blob: "
        + external
        + "; font-src data: "
        + external
        + "; connect-src "
        + (" ".join(connect) or "'none'")
        + "; media-src data: blob: "
        + external
        + "; worker-src blob: "
        + external
        + "; object-src 'none'; frame-src about:; form-action 'none'; base-uri 'none'"
    )
    document = (
        '<meta http-equiv="Content-Security-Policy" content="'
        + html.escape(policy, quote=True)
        + '">'
        + bootstrap
        + document_html
    )
    payload = json.dumps(
        {
            "arguments": value.get("arguments", {}),
            "result": value.get("result", {}),
            "compatibility": compatibility,
        },
        ensure_ascii=False,
    ).replace("<", "\\u003c")
    src = html.escape(document, quote=True)
    body = (
        """<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;height:100%;background:white}iframe{border:0;width:100%;height:100%}</style></head><body><iframe title="MCP App" sandbox="allow-scripts allow-forms"""
        + (" allow-same-origin" if compatibility else "")
        + '" srcdoc="'
        + src
        + """"></iframe><script>
const data="""
        + payload
        + """;const frame=document.querySelector('iframe');
const send=x=>frame.contentWindow.postMessage({jsonrpc:'2.0',...x},'*');
window.addEventListener('message',event=>{
 if(event.source!==frame.contentWindow || event.origin!==(data.compatibility?location.origin:'null'))return;
 const m=event.data;if(!m||m.jsonrpc!=='2.0'||typeof m.method!=='string')return;
 if(m.method==='ui/initialize'){send({id:m.id,result:{protocolVersion:m.params?.protocolVersion||'2026-01-26',hostInfo:{name:'Agent Harness',version:'0.1.0'},hostCapabilities:{},hostContext:{theme:'light',displayMode:'inline',availableDisplayModes:['inline']}}});}
 else if(m.method==='ui/notifications/initialized'){send({method:'ui/notifications/tool-input',params:{arguments:data.arguments}});send({method:'ui/notifications/tool-result',params:data.result});}
 else if(m.method==='ui/notifications/size-changed'){frame.style.height=Math.min(1200,Math.max(200,Number(m.params?.height)||400))+'px';}
 else if(m.method==='ui/update-model-context' && m.id!==undefined){send({id:m.id,result:{}});}
 else if(m.id!==undefined){send({id:m.id,error:{code:-32601,message:'Display-only host: actions must be requested through an approved agent run.'}});}
});</script></body></html>"""
    )
    return HTMLResponse(
        body,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": policy
            + "; frame-ancestors "
            + " ".join(settings.origins.split(",")),
        },
    )
