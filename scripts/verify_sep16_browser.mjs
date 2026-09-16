/** @input Fresh map view ticket and Playwright. @output Map screenshot, canvas and network evidence.
 * @position Real browser acceptance. @doc-sync Update scripts/INDEX.md on changes.
 */
import { chromium } from "../frontend/node_modules/playwright/index.mjs";
import { readFile, writeFile } from "node:fs/promises";
const dir = new URL("../data/fix-verification-20260916/", import.meta.url);
const ticket = JSON.parse(await readFile(new URL("map-view.json", dir), "utf8"));
const browser = await chromium.launch({ channel: "msedge", headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const errors = [], tiles = [];
  page.on("pageerror", e => errors.push(String(e)));
  page.on("response", r => { if(r.url().includes("tile.openstreetmap")) tiles.push(r.status()); });
  const response = await page.goto(ticket.url);
  await page.waitForTimeout(20000);
  const frames = [];
  for (const frame of page.frames()) frames.push({text: (await frame.locator("body").innerText()).slice(0,1500), canvas: await frame.locator("canvas").count()});
  await page.screenshot({path: new URL("map.png",dir).pathname.replace(/^\/([A-Z]:)/i,"$1")});
  await writeFile(new URL("browser.json",dir),JSON.stringify({status:response.status(),errors,tiles,frames},null,2));
  if(response.status()!==200 || !frames.some(f=>f.canvas>0) || !tiles.includes(200)) throw Error("Map rendering not verified; inspect evidence");
  console.log("MAP BROWSER PASS: canvas and successful map tiles", tiles.filter(s=>s===200).length);
} finally { await browser.close(); }
