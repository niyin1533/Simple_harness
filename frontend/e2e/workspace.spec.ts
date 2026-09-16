/** @input Running API, worker, frontend and fixture model. @output UI smoke and real transport roundtrip. @position Browser verification. @doc-sync Update INDEX.md on changes. */
import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
test("login, pages, memory and durable chat", async ({ page, request }) => {
  const credentials = Object.fromEntries(
    (await readFile("../data/initial-admin.txt", "utf8"))
      .trim()
      .split(/\r?\n/)
      .map((line) => {
        const i = line.indexOf("=");
        return [line.slice(0, i), line.slice(i + 1)];
      }),
  );
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "欢迎回来" })).toBeVisible();
  await page.screenshot({ path: "test-results/login.png", fullPage: true });
  await page.getByLabel("用户名", { exact: true }).fill(credentials.username);
  await page.getByLabel("密码", { exact: true }).fill(credentials.password);
  await page.getByRole("button", { name: "登录工作台" }).click();
  await expect(page.getByText("复杂任务，从一次对话开始。")).toBeVisible();
  for (const label of ["智能体", "任务中心", "定时任务", "记忆", "配置中心"]) {
    await page.locator("nav").getByText(label, { exact: true }).click();
    await expect(page.locator("h1")).toBeVisible();
  }
  await expect(page.locator(".ant-spin-spinning")).toHaveCount(0);
  await page.screenshot({
    path: "test-results/configuration.png",
    fullPage: true,
  });
  await page.locator("nav").getByText("记忆", { exact: true }).click();
  await page.getByRole("button", { name: "添加记忆" }).click();
  await page.getByLabel("记忆内容").fill("e2e-test: prefer concise responses");
  await page.getByRole("button", { name: "确 定" }).click();
  await expect(
    page.getByRole("cell", {
      name: "e2e-test: prefer concise responses",
      exact: true,
    }),
  ).toBeVisible();
  const login = await request.post("http://127.0.0.1:8010/api/v1/auth/login", {
    data: credentials,
  });
  const auth = await login.json();
  const headers = { "X-CSRF-Token": auth.csrf };
  const suffix = Date.now();
  const modelResponse = await request.post(
    "http://127.0.0.1:8010/api/v1/resources/model",
    {
      headers,
      data: {
        name: "E2E temporary model " + suffix,
        config: { endpoint: "http://127.0.0.1:18991/v1", model: "fixture" },
      },
    },
  );
  expect(modelResponse.ok()).toBeTruthy();
  const model = await modelResponse.json();
  try {
    await page.locator("nav").getByText("聊天", { exact: true }).click();
    await page.reload();
    await page.locator(".conversation-toolbar .ant-select").click();
    await page.getByText("模型 · " + model.name, { exact: true }).click();
    await page
      .getByPlaceholder("描述你的目标，Shift + Enter 换行")
      .fill("e2e: verify independent harness");
    await page.getByRole("button", { name: /发送$/ }).click();
    await expect(
      page.getByText("端到端链路验证通过。", { exact: true }),
    ).toBeVisible({ timeout: 30000 });
    await page.screenshot({ path: "test-results/chat.png", fullPage: true });
    await page.getByRole("button", { name: "查看执行过程" }).click();
    await expect(
      page.getByText("RUN_SUCCEEDED", { exact: true }),
    ).toBeVisible();
    await page.screenshot({ path: "test-results/run.png", fullPage: true });
    expect(errors).toEqual([]);
  } finally {
    await request.delete(
      "http://127.0.0.1:8010/api/v1/resources/model/" + model.id,
      { headers },
    );
    const memories = await (
      await request.get("http://127.0.0.1:8010/api/v1/memories")
    ).json();
    for (const m of memories.filter(
      (m: any) => m.content === "e2e-test: prefer concise responses",
    ))
      await request.delete("http://127.0.0.1:8010/api/v1/memories/" + m.id, {
        headers,
      });
  }
});

test("MCP resource renders in an opaque-origin frame", async ({
  page,
  request,
}) => {
  const credentials = Object.fromEntries(
    (await readFile("../data/initial-admin.txt", "utf8"))
      .trim()
      .split(/\r?\n/)
      .map((line) => {
        const i = line.indexOf("=");
        return [line.slice(0, i), line.slice(i + 1)];
      }),
  );
  const login = await request.post("http://127.0.0.1:8010/api/v1/auth/login", {
    data: credentials,
  });
  const auth = await login.json();
  const headers = { "X-CSRF-Token": auth.csrf };
  const response = await request.post(
    "http://127.0.0.1:8010/api/v1/resources/mcp",
    {
      headers,
      data: {
        name: "E2E MCP fixture",
        config: {
          command: resolve("../.venv/Scripts/python.exe"),
          args: [resolve("../backend/tests/fixture_mcp.py")],
        },
      },
    },
  );
  expect(response.ok()).toBeTruthy();
  const server = await response.json();
  try {
    const discovery = await request.post(
      "http://127.0.0.1:8010/api/v1/mcp/" + server.id + "/discover",
      { headers },
    );
    expect(discovery.ok()).toBeTruthy();
    const view = await request.post(
      "http://127.0.0.1:8010/api/v1/mcp/" + server.id + "/view",
      {
        headers,
        data: {
          uri: "ui://fixture/result",
          arguments: { text: "bridge verified" },
          result: { content: [] },
        },
      },
    );
    expect(view.ok()).toBeTruthy();
    await page.goto((await view.json()).url);
    const frame = page.frameLocator("iframe");
    await expect(
      frame.getByRole("heading", { name: "Fixture MCP App" }),
    ).toBeVisible();
    await expect(frame.getByText("input: bridge verified")).toBeVisible();
    const child = page.frames().find((f) => f.parentFrame());
    expect(
      await child!.evaluate(() => {
        try {
          void parent.document.body;
          return false;
        } catch {
          return true;
        }
      }),
    ).toBe(true);
    await page.screenshot({ path: "test-results/mcp-app.png", fullPage: true });
  } finally {
    await request.delete(
      "http://127.0.0.1:8010/api/v1/resources/mcp/" + server.id,
      { headers },
    );
  }
});
