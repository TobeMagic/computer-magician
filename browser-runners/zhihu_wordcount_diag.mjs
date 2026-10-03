import { readFile } from "node:fs/promises";
import { chromium } from "playwright";

const payload = JSON.parse(await readFile("/tmp/zhihu-republish/payload.json", "utf8"));
const draft = payload.draft || {};
const stateFile = "/var/lib/aimagician/artifacts/browser-states/zhihu-session-state.json";

const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
const context = await browser.newContext({ storageState: stateFile, locale: "zh-CN" });
const page = await context.newPage();
await page.goto("https://zhuanlan.zhihu.com/write", { waitUntil: "domcontentloaded", timeout: 60000 });
await page.waitForTimeout(2000);

await page.locator("textarea[placeholder*='标题']").first().fill(String(draft.title || payload.title || ""));
const body = page.locator("div[contenteditable='true'][role='textbox']").first();
await body.click();
await body.evaluate((node, html) => {
  node.innerHTML = html;
  node.dispatchEvent(new InputEvent("input", { bubbles: true }));
}, "<p>测试段落一</p><p>测试段落二，字数应该增加。</p><h2>标题测试</h2><p>更多内容更多内容更多内容。</p>");
await page.waitForTimeout(3000);
await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
await page.waitForTimeout(1000);
const text = await page.locator("body").innerText();
console.log("FOOTER", text.slice(-800));
console.log("MATCH", text.match(/字数[：:]\s*([\d,]+)/));
await browser.close();
