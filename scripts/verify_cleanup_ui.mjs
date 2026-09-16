/** @input Running Vite and intercepted fixture APIs. @output Loading, overflow and deletion UI checks.
 * @position Non-destructive browser regression. @doc-sync Update scripts/INDEX.md on changes.
 */
import { chromium } from "../frontend/node_modules/playwright/index.mjs";
import assert from "node:assert/strict";
const browser = await chromium.launch({ channel: "msedge", headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  let sessions = [{id:"s1",title:"保留会话",target_id:"a"},{id:"s2",title:"删除会话",target_id:"a"}];
  let runs = [{id:"r1",task:"历史任务",status:"SUCCEEDED"},{id:"r2",task:"运行任务",status:"RUNNING"}];
  const writes = [];
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const method = route.request().method();
    if (method !== "GET") writes.push({path,method,body:route.request().postDataJSON()});
    let body = [];
    if(path === "/auth/me") body = {user:{username:"test",admin:true},csrf:"fixture"};
    else if(path === "/preferences") body = {config:{}};
    else if(path === "/memories/review") {
      await new Promise(r=>setTimeout(r,1200));
      body = {suggestions:[{id:"m",action:"disable",reason:"与原有记录重复"+"abcdefgh1234567890".repeat(30),content:"用户希望以后称呼其为小明"}]};
    } else if(path === "/memories/reindex") { await new Promise(r=>setTimeout(r,1200)); body = {count:1}; }
    else if(path === "/sessions") body = sessions;
    else if(path === "/sessions/s2" && method === "DELETE") {sessions=sessions.filter(s=>s.id!=="s2");body={ok:true};}
    else if(path.endsWith("/messages")) body = {messages:[]};
    else if(path === "/runs") body = runs;
    else if(path === "/runs/batch-delete") {runs=runs.filter(r=>r.id!=="r1");body={deleted:1};}
    await route.fulfill({json:body});
  });
  await page.goto("http://127.0.0.1:5173/memories");
  await page.getByRole("button",{name:"分析重复与冲突"}).click();
  await page.getByRole("button",{name:"正在分析…"}).waitFor();
  assert(await page.locator(".ant-btn-loading").count()>0);
  await page.getByRole("button",{name:"停用重复记忆"}).waitFor();
  for (const width of [1280,600]) {
    await page.setViewportSize({width,height:900});
    const fit = await page.locator(".memory-review-list").evaluate(el=>el.scrollWidth<=el.clientWidth+1);
    assert(fit,"review overflows horizontally");
    const card = await page.locator(".memory-review-list .ant-card").boundingBox();
    const modal = await page.locator(".ant-modal-content").boundingBox();
    assert(card.x+card.width<=modal.x+modal.width+1);
  }
  await page.getByRole("button",{name:/知.*道.*了/}).click();
  await page.getByRole("button",{name:"重建向量索引"}).click();
  await page.getByRole("button",{name:"正在重建…"}).waitFor();
  await page.getByRole("button",{name:"重建向量索引"}).waitFor();
  await page.setViewportSize({width:1280,height:900});
  await page.goto("http://127.0.0.1:5173/chat");
  const deleteButton = page.getByRole("button",{name:"删除对话：删除会话"});
  await deleteButton.waitFor();
  await page.mouse.move(1100,800);
  await page.waitForTimeout(180);
  assert.equal(await deleteButton.evaluate(el=>getComputedStyle(el).opacity),"0");
  const row = page.locator(".ant-list-item").filter({has:deleteButton});
  const before = await row.locator(".session-title").boundingBox();
  await row.hover({position:{x:15,y:15}});
  await page.waitForTimeout(180);
  assert.equal(await deleteButton.evaluate(el=>getComputedStyle(el).opacity),"1");
  assert.equal(await deleteButton.evaluate(el=>getComputedStyle(el).color),"rgb(102, 112, 133)");
  assert.deepEqual(await row.locator(".session-title").boundingBox(),before);
  const box = await deleteButton.boundingBox();
  assert(box.width===32 && box.height===32 && before.x+before.width<=box.x);
  await deleteButton.hover();
  await page.waitForTimeout(180);
  assert.equal(await deleteButton.evaluate(el=>getComputedStyle(el).color),"rgb(180, 35, 24)");
  await page.mouse.move(1100,800);
  await page.getByRole("button",{name:"新建对话"}).focus();
  await page.keyboard.press("Tab");
  assert(await page.getByRole("button",{name:"删除对话：保留会话"}).evaluate(el=>el===document.activeElement));
  await page.waitForTimeout(180);
  assert.equal(await page.getByRole("button",{name:"删除对话：保留会话"}).evaluate(el=>getComputedStyle(el).opacity),"1");
  await row.hover();
  await deleteButton.click();
  await page.getByRole("button",{name:/确.*定/}).click();
  await page.getByRole("button",{name:"删除对话：删除会话"}).waitFor({state:"detached"});
  assert(!writes.some(w=>w.path.includes("/sessions/s1")));
  await page.goto("http://127.0.0.1:5173/tasks");
  const running = page.getByRole("row").filter({hasText:"运行任务"});
  assert(await running.getByRole("checkbox").isDisabled());
  const history = page.getByRole("row").filter({hasText:"历史任务"});
  await history.getByRole("checkbox").check();
  await page.getByRole("button",{name:/批量删除/}).click();
  await page.getByRole("button",{name:/确.*定/}).click();
  await history.waitFor({state:"detached"});
  assert.deepEqual(writes.find(w=>w.path==="/runs/batch-delete").body,{ids:["r1"]});
  const touchContext = await browser.newContext({hasTouch:true,viewport:{width:1024,height:768}});
  const touchPage = await touchContext.newPage();
  await touchPage.route("**/api/v1/**",route=>route.fulfill({json:route.request().url().endsWith("/auth/me")?{user:{username:"test",admin:true},csrf:"fixture"}:route.request().url().endsWith("/sessions")?sessions:[]}));
  await touchPage.goto("http://127.0.0.1:5173/chat");
  const touchDelete = touchPage.locator(".session-delete").first();
  await touchDelete.waitFor();
  assert.equal(await touchDelete.evaluate(el=>getComputedStyle(el).opacity),"1");
  await touchContext.close();
  console.log("PASS: loading, long text at 1280/600px, sidebar deletion, protected active task and batch deletion; all APIs mocked");
} finally { await browser.close(); }
