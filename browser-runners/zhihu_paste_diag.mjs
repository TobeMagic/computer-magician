import { readFile } from "node:fs/promises";
import { chromium } from "playwright";

const payload = JSON.parse(await readFile("/tmp/zhihu-republish/payload.json", "utf8"));
const draft = payload.draft || {};
const markdown = draft.markdown || payload.markdown || "";
const stateFile = "/var/lib/aimagician/artifacts/browser-states/zhihu-session-state.json";

const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
const context = await browser.newContext({ storageState: stateFile, locale: "zh-CN", permissions: ["clipboard-read", "clipboard-write"] });
const page = await context.newPage();
await page.goto("https://zhuanlan.zhihu.com/write", { waitUntil: "domcontentloaded", timeout: 60000 });
await page.waitForTimeout(2000);
const draftUrl = page.url();
console.log("DRAFT_URL", draftUrl);
await page.locator("textarea[placeholder*='标题']").first().fill(String(draft.title || ""));

const body = page.locator("div[contenteditable='true'][role='textbox']").first();
await body.click();
await page.evaluate(async (text) => {
  await navigator.clipboard.writeText(text);
}, markdown.slice(0, 8000));
await page.keyboard.press("Control+V");
await page.waitForTimeout(5000);
await page.locator("textarea[placeholder*='标题']").first().click().catch(() => null);
await page.waitForTimeout(5000);

let bodyLen = (await body.innerText()).length;
console.log("PASTE_BODY_LEN", bodyLen, "URL", page.url());

await page.waitForTimeout(15000);
await page.locator("textarea[placeholder*='标题']").first().click().catch(() => null);
await page.waitForTimeout(3000);
bodyLen = (await body.innerText()).length;
console.log("AFTER_WAIT_BODY_LEN", bodyLen);

await page.goto(page.url(), { waitUntil: "domcontentloaded", timeout: 60000 });
await page.waitForTimeout(5000);
bodyLen = (await page.locator("div[contenteditable='true'][role='textbox']").first().innerText()).length;
console.log("RELOAD_BODY_LEN", bodyLen);

await browser.close();
