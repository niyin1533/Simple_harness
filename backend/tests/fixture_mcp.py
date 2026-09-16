"""@input MCP test clients. @output Local echo tool and HTML resource.
@position Transport fixture. @doc-sync Update INDEX.md on changes.
"""

import sys
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Harness fixture", host="127.0.0.1", port=18992)


@mcp.tool(meta={"ui": {"resourceUri": "ui://fixture/result"}})
def echo(text: str) -> dict:
    return {"text": text}


@mcp.resource("ui://fixture/result", mime_type="text/html;profile=mcp-app")
def view() -> str:
    return """<!doctype html><h1>Fixture MCP App</h1><p id="state">waiting</p><script>
parent.postMessage({jsonrpc:'2.0',id:1,method:'ui/initialize',params:{protocolVersion:'2026-01-26'}},'*');
window.addEventListener('message',e=>{if(e.source!==parent)return;const m=e.data;if(m.id===1&&m.result)parent.postMessage({jsonrpc:'2.0',method:'ui/notifications/initialized'},'*');if(m.method==='ui/notifications/tool-input')document.getElementById('state').textContent='input: '+m.params.arguments.text;});
</script>"""


if __name__ == "__main__":
    mcp.run(transport="streamable-http" if "--http" in sys.argv else "stdio")
