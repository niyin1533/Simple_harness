/**
 * @input Local Playwright, current API-created map view ticket.
 * @output Screenshot and browser error evidence in data/live-acceptance-20260914.
 * @position Opt-in real MCP App rendering diagnostic; does not change product code.
 * @doc-sync Update this header and scripts/INDEX.md on changes.
 */
import { chromium } from "../frontend/node_modules/playwright/index.mjs";
import { readFile, writeFile } from "node:fs/promises";
const directory = new URL("../data/live-acceptance-20260915/", import.meta.url);
const state = JSON.parse(
  await readFile(new URL("state.json", directory), "utf8"),
);
const browser = await chromium.launch({ channel: "msedge", headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 1280, height: 800 },
  });
  const errors = [];
  const messages = [];
  await page.addInitScript(() => {
    window.__mcpMessages = [];
    window.addEventListener("message", (e) => {
      if (e.data?.jsonrpc === "2.0") window.__mcpMessages.push(e.data);
    });
  });
  page.on("console", (m) => {
    if (m.type() !== "error") messages.push(m.text().slice(0, 1000));
  });
  const network = [];
  page.on("response", (r) => {
    if (/tile\.openstreetmap|\/Cesium\/Workers\//.test(r.url()))
      network.push({ url: r.url(), status: r.status() });
  });
  page.on("pageerror", (e) => errors.push(e.stack || String(e)));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text().slice(0, 1500));
  });
  const response = await page.goto(state.map_view.url);
  await page.waitForTimeout(25000);
  const frames = [];
  for (const frame of page.frames()) {
    frames.push({
      main: frame === page.mainFrame(),
      text: (await frame.locator("body").innerText()).slice(0, 3000),
      canvas: await frame.locator("canvas").count(),
      rpc: await frame.evaluate(() => window.__mcpMessages || []),
    });
  }
  await page.screenshot({
    path: new URL("map-browser.png", directory).pathname.replace(
      /^\/([A-Z]:)/i,
      "$1",
    ),
    fullPage: true,
  });
  const evidence = {
    status: response.status(),
    frames,
    errors,
    network,
    messages,
  };
  await writeFile(
    new URL("map-browser.json", directory),
    JSON.stringify(evidence, null, 2),
  );
  console.log(JSON.stringify(evidence, null, 2));
} finally {
  await browser.close();
}
