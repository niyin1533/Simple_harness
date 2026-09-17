/** @input Running Vite and mocked HTTP/SSE fixtures. @output Grant persistence, sidebar, compatibility and responsive screenshot regression.
 * @position Non-destructive UI acceptance. @doc-sync Update scripts/INDEX.md on changes. */
import { chromium } from "../frontend/node_modules/playwright/index.mjs";
import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
const realMap = process.env.AGENT_REAL_MAP === "1" ? JSON.parse(await readFile("data/publication-ui/map-ticket.json", "utf8")) : null;
const browser = await chromium.launch({ channel: "msedge", headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  const tileResponses=[];
  page.on("response", response => { if(response.url().includes("tile.openstreetmap")) tileResponses.push(response.status()); });
  let authRequests = 0, publishedBody, published, saved = null, keyBody;
  let sessions = [{ id:"old", title:"地图与灵感", version:1 }, { id:"other", title:"本周研究计划", version:1 }];
  const capabilities = [{ id:"test.read", name:"读取官方文档", risk:"READ", allowed:true }, { id:"test.write", name:"更新内容", risk:"WRITE", allowed:true }, { id:"test.high", name:"危险工具", risk:"HIGH", allowed:true }, { id:"map", name:"Show Map", risk:"WRITE", allowed:true, ui_uri:"ui://cesium-map/mcp-app.html" }, ...Array.from({length:20},(_,i)=>({ id:`extra.${i}`,name:`工具 ${i}`, risk:"READ", allowed:true }))];
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    let body = [];
    if(path === "/auth/me") { authRequests++; body={user:{username:"fixture",admin:true},csrf:"fixture"}; }
    else if(path === "/resources/agent") body=[{id:"a",name:"发布验收助手",enabled:true,version:1,config:{}}];
    else if(path === "/publications/check/a") body={capabilities,saved_grants:saved,current_version_id:published?.current_version || null,warnings:["请先完成后台调试"]};
    else if(path === "/publications" && route.request().method() === "POST") { publishedBody=route.request().postDataJSON(); saved=structuredClone(publishedBody.grants); published={id:"app",agent_id:"a",number:1,current_version:"v1",enabled:true,web_enabled:false,api_enabled:true,site_code:"site",rpm:30,concurrency:5}; body=published; }
    else if(path === "/publications") body=published?[published]:[];
    else if(path === "/publications/app/keys" && route.request().method()==="POST") {keyBody=route.request().postDataJSON();body={key:"app-test-not-real"};}
    await route.fulfill({json:body});
  });
  await page.route("**/public-api/v1/apps/site**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/public-api/v1/apps/site", "");
    if(path.endsWith("/events")) { await route.fulfill({contentType:"text/event-stream",body:'id: 1\nevent: run_started\ndata: {"status":"RUNNING"}\n\nid: 2\nevent: message_completed\ndata: {"answer":"公开应用测试通过"}\n\nid: 3\nevent: done\ndata: {"status":"SUCCEEDED"}\n\n'});return; }
    let body=[];
    if(path === "") body={name:"自测助手",description:"连接知识与工具，让每一个想法，都有下一步。",version:1,csrf:"visitor"};
    else if(path === "/conversations") body=sessions;
    else if(path === "/chat-messages") body={run_id:"r",conversation_id:"c",version:1,status:"QUEUED"};
    else if(path === "/runs/r") body={status:"SUCCEEDED",answer:"公开应用测试通过"};
    else if(path === "/conversations/old/messages") body=[{role:"user",content:"为我展示天安门附近的地图。",run_id:"maprun"},{role:"assistant",content:"### 已为你定位天安门\n地图已准备就绪，你可以在下方交互卡片中缩放和浏览。",run_id:"maprun"}];
    else if(path === "/conversations/old/views") body=[{run_id:"maprun",call_id:"mapcall",name:"Show Map"}];
    else if(path === "/runs/maprun/views/mapcall") body={...(realMap || {url:"http://127.0.0.1:8011/fixture-map",mode:"isolated-compatibility"}),compatibility_required:true,compatibility_allowed:true};
    else if(path === "/conversations/other" && route.request().method()==="DELETE") {sessions=sessions.filter(s=>s.id!=="other");body={ok:true};}
    await route.fulfill({json:body});
  });
  await page.route("**/fixture-map",route=>route.fulfill({contentType:"text/html",body:'<html style="background:#172d34;color:#bdffdf;font:20px sans-serif"><body style="padding:70px;text-align:center">地图兼容视图 · 浏览器夹具</body></html>'}));
  await mkdir("data/publication-ui",{recursive:true});
  await page.goto("http://127.0.0.1:5173/published/agents/site");
  await page.getByRole("heading",{name:"自测助手"}).waitFor();
  assert.equal(authRequests,0);
  await page.screenshot({path:"data/publication-ui/welcome-desktop.png"});
  await page.getByRole("textbox",{name:"消息输入框"}).fill("你好");
  await page.getByRole("button",{name:/发\s*送/,exact:true}).click();
  await page.getByText("公开应用测试通过",{exact:true}).waitFor();
  await page.locator('.public-history-select[title="地图与灵感"]').click();
  await page.locator('iframe[title="工具交互卡片"]').waitFor();
  assert((await page.locator('iframe[title="工具交互卡片"]').getAttribute("sandbox")).includes("allow-same-origin"));
  await page.getByText("兼容模式 · 隔离运行").waitFor();
  if(realMap) {
    let rendered=false;
    for(let n=0;n<40;n++) { for(const frame of page.frames()) { if(await frame.locator("canvas").count()) rendered=true; } if(rendered) break; await page.waitForTimeout(500); }
    assert(rendered,"Real Cesium map canvas not rendered in public iframe");
    await page.waitForTimeout(20000);
    const errors=[];for(const frame of page.frames()) { if((await frame.locator(".cesium-widget-errorPanel").count())>0) errors.push(await frame.locator(".cesium-widget-errorPanel").innerText()); }
    assert.equal(errors.length,0,"Cesium runtime error: "+errors.join("; "));
    assert(tileResponses.includes(200),"No successful real map tile response");
    console.log("PASS: actual MCP HTML and local Cesium canvas in public compatibility iframe");
  }
  await page.screenshot({path:"data/publication-ui/chat-desktop.png"});
  const row=page.locator(".public-history-row").filter({hasText:"本周研究计划"});await row.hover();
  await page.getByRole("button",{name:"删除会话：本周研究计划"}).click();
  await page.getByRole("button",{name:/确\s*定/,exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('[title="本周研究计划"]'));
  await page.getByRole("button",{name:"隐私与数据菜单"}).click();await page.getByRole("menuitem",{name:"隐私与数据"}).click();
  await page.getByRole("dialog").getByText("隐私与数据",{exact:true}).waitFor();await page.getByRole("button",{name:/取\s*消/,exact:true}).click();
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.getByRole("button",{name:"打开会话列表"}).click();await page.getByRole("navigation",{name:"历史会话"}).waitFor();
  await page.waitForTimeout(350);
  await page.waitForFunction(()=>document.querySelector('.public-sidebar.is-open')?.getBoundingClientRect().left>=-1);
  await page.screenshot({path:"data/publication-ui/mobile.png"});
  await page.setViewportSize({width:1440,height:960});await page.goto("http://127.0.0.1:5173/agents");
  await page.getByRole("button",{name:"发布管理",exact:true}).click();
  await page.getByRole("checkbox",{name:"全选非 HIGH 工具"}).waitFor();
  assert(await page.getByRole("checkbox",{name:"更新内容",exact:true}).isChecked());
  assert(!(await page.getByRole("checkbox",{name:"危险工具",exact:true}).isChecked()));
  assert(await page.getByRole("checkbox",{name:"允许可信交互卡片兼容模式"}).isChecked());
  assert(await page.locator(".publish-tool-scroll").evaluate(e=>e.clientHeight<=360 && e.scrollHeight>e.clientHeight));
  await page.getByRole("checkbox",{name:"读取官方文档",exact:true}).uncheck();
  await page.getByRole("checkbox",{name:"我已完成后台调试，确认依赖和所选授权可对外开放"}).check();
  await page.getByRole("button",{name:"发布新版本"}).click();await page.getByText("操作成功",{exact:true}).waitFor();
  assert(!("test.read" in publishedBody.grants));assert.equal(publishedBody.grants.map.ui_compatibility,true);assert(!("test.high" in publishedBody.grants));
  await page.locator(".ant-drawer-close").click();await page.getByRole("button",{name:"发布管理",exact:true}).click();
  await page.getByRole("checkbox",{name:"更新内容",exact:true}).waitFor();
  await page.waitForFunction(()=>document.querySelector('.publish-tool-scroll input') && !document.querySelector('.publish-tool-scroll input').checked);
  assert(!(await page.getByRole("checkbox",{name:"读取官方文档",exact:true}).isChecked()));assert(await page.getByRole("checkbox",{name:"更新内容",exact:true}).isChecked());
  await page.screenshot({path:"data/publication-ui/publish.png"});
  await page.getByRole("tab",{name:"应用链接与密钥"}).click();assert.equal(await page.locator('input[type="datetime-local"]').count(),0);
  assert(!(await page.getByText("http://127.0.0.1:5173/service-api/v1/chat-messages",{exact:true}).isVisible()));
  await page.getByRole("button",{name:"创建密钥",exact:true}).click();await page.locator('.ant-modal-confirm-title:visible').filter({hasText:"请立即保存，仅显示一次"}).waitFor();assert.equal(keyBody.expires,null);assert(keyBody.name);
  console.log("PASS: saved grants, non-HIGH defaults, scrolling, optional permanent keys, sidebar deletion/privacy, responsive layout and compatible history views");
} finally {await browser.close();}
