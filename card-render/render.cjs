#!/usr/bin/env node
const path = require("path");
const fs = require("fs");
const { pathToFileURL } = require("url");

function resolvePlaywright(taskDir) {
  const candidates = [
    path.join(__dirname, "..", "browser-runners", "node_modules", "playwright"),
    path.join(__dirname, "..", "publisher-worker", "node_modules", "playwright"),
    path.join(process.cwd(), "node_modules", "playwright"),
    path.join(taskDir, "node_modules", "playwright"),
    "playwright",
  ];
  for (const candidate of candidates) {
    try {
      return require(candidate);
    } catch (_) {
      /* try next */
    }
  }
  throw new Error("playwright not found");
}

(async () => {
  const args = process.argv.slice(2);
  const taskDir = path.resolve(args[0] || ".");
  const scaleIdx = args.indexOf("--scale");
  const scale = scaleIdx > -1 ? Number(args[scaleIdx + 1]) || 1 : 1;
  const htmlIdx = args.indexOf("--html");
  const htmlName = htmlIdx > -1 ? args[htmlIdx + 1] : "index.html";
  const htmlPath = path.join(taskDir, htmlName);
  if (!fs.existsSync(htmlPath)) {
    console.error("missing HTML", htmlPath);
    process.exit(1);
  }
  const outDir = path.join(taskDir, "output");
  fs.mkdirSync(outDir, { recursive: true });
  const { chromium } = resolvePlaywright(taskDir);
  const browser = await chromium.launch();
  const page = await browser.newPage({ deviceScaleFactor: scale });
  await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(400);
  const handles = await page.$$(".card, .dcard, .ecard, .femcard");
  if (handles.length === 0) {
    console.error("no card nodes");
    await browser.close();
    process.exit(1);
  }
  let index = 0;
  for (const el of handles) {
    index += 1;
    const id = await el.getAttribute("id");
    const name = `${id || `card-${String(index).padStart(2, "0")}`}.png`;
    await el.screenshot({ path: path.join(outDir, name) });
    const box = await el.boundingBox();
    console.log(`exported ${name} (${Math.round(box.width * scale)}x${Math.round(box.height * scale)})`);
  }
  await browser.close();
  console.log(`done ${index} ${outDir}`);
})();
