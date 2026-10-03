import { writeFile, mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { readFile } from "node:fs/promises";
import { chromium } from "playwright";

const payload = JSON.parse(await readFile("/tmp/zhihu-republish/payload.json", "utf8"));
const draft = payload.draft || {};
const stateFile = "/var/lib/aimagician/artifacts/browser-states/zhihu-session-state.json";
const tempDir = await mkdtemp(path.join(os.tmpdir(), "zhihu-md-"));
const mdPath = path.join(tempDir, "article.md");
await writeFile(mdPath, draft.markdown || payload.markdown || "", "utf8");

const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
const context = await browser.newContext({ storageState: stateFile, locale: "zh-CN" });
const page = await context.newPage();
await page.goto("https://zhuanlan.zhihu.com/write", { waitUntil: "domcontentloaded", timeout: 60000 });
await page.waitForTimeout(2000);
await page.locator("textarea[placeholder*='标题']").first().fill(String(draft.title || ""));

const importSelectors = [
  "button[aria-label*='导入']",
  "button:text-is('导入')",
  "[role='button']:text-is('导入')",
];
let clicked = "";
for (const sel of importSelectors) {
  const loc = page.locator(sel).first();
  if (await loc.count() && await loc.isVisible().catch(() => false)) {
    const chooserPromise = page.waitForEvent("filechooser", { timeout: 5000 }).catch(() => null);
    await loc.click().catch(() => null);
    const chooser = await chooserPromise;
    if (chooser) {
      await chooser.setFiles(mdPath);
      clicked = sel;
      break;
    }
  }
}
console.log("IMPORT_CLICKED", clicked);
await page.waitForTimeout(8000);
const bodyText = await page.locator("div[contenteditable='true'][role='textbox']").first().innerText().catch(() => "");
console.log("BODY_LEN", bodyText.length);
console.log("BODY_START", bodyText.slice(0, 200).replace(/\n/g, " "));
await page.goto(page.url(), { waitUntil: "domcontentloaded" });
await page.waitForTimeout(4000);
const reloadLen = (await page.locator("div[contenteditable='true'][role='textbox']").first().innerText().catch(() => "")).length;
console.log("RELOAD_BODY_LEN", reloadLen);
await browser.close();
