import { chromium } from "playwright";

const draftUrl = "https://zhuanlan.zhihu.com/p/2086140189735502082/edit";
const stateFile = "/var/lib/aimagician/artifacts/browser-states/zhihu-session-state.json";

const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
const context = await browser.newContext({ storageState: stateFile, locale: "zh-CN" });
const page = await context.newPage();
await page.goto(draftUrl, { waitUntil: "domcontentloaded", timeout: 60000 });
await page.waitForTimeout(3000);
await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
await page.waitForTimeout(1000);

const btn = page.locator("button:text-is('发布')").last();
console.log("count", await btn.count());
console.log("visible", await btn.isVisible().catch(() => false));
console.log("enabled", await btn.isEnabled().catch(() => false));
console.log("bodyLen", (await page.locator("div[contenteditable='true'][role='textbox']").first().innerText()).length);
console.log("footer", (await page.locator("body").innerText()).slice(-500));

await browser.close();
