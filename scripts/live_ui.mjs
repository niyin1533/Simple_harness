/**
 * @input Running React platform, admin credential file, today's live acceptance state.
 * @output Actual wizard and task-detail map compatibility browser evidence.
 * @position Opt-in UI regression; disables only the agent created by this script.
 * @doc-sync Update scripts/INDEX.md on changes.
 */
import { chromium } from "../frontend/node_modules/playwright/index.mjs";
import { readFile, writeFile } from "node:fs/promises";
const directory = new URL("../data/live-acceptance-20260915/", import.meta.url);
const state = JSON.parse(
  await readFile(new URL("state.json", directory), "utf8"),
);
const credentials = Object.fromEntries(
  (
    await readFile(
      new URL("../data/initial-admin.txt", import.meta.url),
      "utf8",
    )
  )
    .trim()
    .split(/\r?\n/)
    .map((x) => {
      const i = x.indexOf("=");
      return [x.slice(0, i), x.slice(i + 1)];
    }),
);
const browser = await chromium.launch({ channel: "msedge", headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
});
const page = await context.newPage();
let created;
const evidence = {};
try {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.stack || String(e)));
  await page.goto("http://127.0.0.1:5173/agents");
  await page.getByLabel("用户名").fill(credentials.username);
  await page.getByLabel("密码", { exact: true }).fill(credentials.password);
  const loggedIn = page.waitForResponse(
    (r) => r.url().endsWith("/auth/login") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: /登\s*录/ }).click();
  if (!(await loggedIn).ok()) throw new Error("Login failed");
  await page.goto("http://127.0.0.1:5173/agents");
  await page.getByRole("button", { name: /创建智能体/ }).click();
  await page
    .getByLabel("智能体名称", { exact: true })
    .fill("[联调0915] 浏览器创建验收 " + Date.now());
  await page.getByRole("button", { name: "下一步" }).click();
  await page.getByLabel("基础模型", { exact: true }).press("ArrowDown");
  await page.getByText(state.model_name, { exact: true }).last().click();
  await page.getByRole("button", { name: "下一步" }).click();
  await page.getByRole("button", { name: "下一步" }).click();
  const saved = page.waitForResponse(
    (r) =>
      r.url().endsWith("/resources/agent") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "保存智能体" }).click();
  const response = await saved;
  if (!response.ok())
    throw new Error("Wizard failed: " + (await response.text()));
  created = await response.json();
  await page
    .getByRole("heading", { name: created.name, exact: true })
    .waitFor();
  evidence.wizard = {
    status: "PASS",
    agent_id: created.id,
    model_id: created.config.model_id,
  };
  await page.screenshot({
    path: new URL("ui-wizard.png", directory).pathname.slice(1),
  });
  await page.goto("http://127.0.0.1:5173/tasks");
  await page.locator("tr[data-row-key]").first().waitFor();
  for (let i = 0; i < 20; i++) {
    const row = page.locator('tr[data-row-key="' + state.map_run_id + '"]');
    if (await row.count()) {
      await row.getByRole("button", { name: /详\s*情/ }).click();
      break;
    }
    const next = page.locator(
      ".ant-pagination-next:not(.ant-pagination-disabled)",
    );
    if (!(await next.count())) throw new Error("Map task not found");
    await next.click();
    await page.waitForTimeout(300);
  }
  await page.getByRole("button", { name: "地图兼容模式" }).click();
  const view = page.waitForResponse(
    (r) =>
      /\/mcp\/[^/]+\/view$/.test(r.url()) && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "启用兼容模式", exact: true }).click();
  const viewResult = await view;
  if (!viewResult.ok())
    throw new Error("Map view failed: " + (await viewResult.text()));
  const frame = page.locator('iframe[title="MCP 交互结果"]');
  await frame.waitFor();
  await frame.scrollIntoViewIfNeeded();
  await page.waitForTimeout(25000);
  await frame.screenshot({
    path: new URL("ui-map.png", directory).pathname.slice(1),
  });
  evidence.map = {
    http_status: viewResult.status(),
    mode: (await viewResult.json()).mode,
    canvas: await page
      .frameLocator('iframe[title="MCP 交互结果"]')
      .frameLocator('iframe[title="MCP App"]')
      .locator("canvas")
      .count(),
    errors,
  };
} catch (e) {
  evidence.failure = String(e);
  evidence.page = {
    url: page.url(),
    text: (await page.locator("body").innerText()).slice(0, 2500),
    buttons: await page.getByRole("button").allTextContents(),
  };
  await page.screenshot({
    path: new URL("ui-failure.png", directory).pathname.slice(1),
  });
  process.exitCode = 1;
} finally {
  if (created) {
    const auth = await (
      await context.request.get("http://127.0.0.1:5173/api/v1/auth/me")
    ).json();
    const result = await context.request.put(
      "http://127.0.0.1:5173/api/v1/resources/agent/" + created.id,
      {
        headers: { "X-CSRF-Token": auth.csrf },
        data: {
          name: created.name,
          config: created.config,
          version: created.version,
          enabled: false,
        },
      },
    );
    evidence.cleanup = result.status();
  }
  await writeFile(
    new URL("ui-results.json", directory),
    JSON.stringify(evidence, null, 2),
  );
  console.log(JSON.stringify(evidence, null, 2));
  await browser.close();
}
