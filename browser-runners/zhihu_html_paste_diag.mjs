import { readFile } from "node:fs/promises";
import { chromium } from "playwright";

// minimal blocksToRichEditorHtml inline test
function escapeHtml(v) { return String(v).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function renderInlineMarkdownToHtml(text) { return escapeHtml(text); }
function blocksToRichEditorHtml(blocks) {
  return blocks.map((block) => {
    if (block.type === "table") {
      const rows = block.rows || [];
      if (!rows.length) return "";
      const [header, ...body] = rows;
      const ths = header.map((c) => `<th>${renderInlineMarkdownToHtml(c)}</th>`).join("");
      const trs = body.map((row) => `<tr>${row.map((c) => `<td>${renderInlineMarkdownToHtml(c)}</td>`).join("")}</tr>`).join("");
      return `<table><thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table><p><br></p>`;
    }
    if (block.type === "heading") return `<h2>${renderInlineMarkdownToHtml(block.text)}</h2>`;
    return `<p>${renderInlineMarkdownToHtml(block.text || "")}</p>`;
  }).join("");
}

const payload = JSON.parse(await readFile("/tmp/zhihu-republish/payload.json", "utf8"));
const markdown = payload.draft.markdown;
const blocks = [{type:"heading", text:"测试标题"}, {type:"paragraph", text:"段落内容"}, {type:"table", rows:[["A","B"],["1","2"]]}];
const html = blocksToRichEditorHtml(blocks);
const stateFile = "/var/lib/aimagician/artifacts/browser-states/zhihu-session-state.json";

const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
const context = await browser.newContext({ storageState: stateFile, locale: "zh-CN", permissions: ["clipboard-read", "clipboard-write"] });
const page = await context.newPage();
await page.goto("https://zhuanlan.zhihu.com/write", { waitUntil: "domcontentloaded", timeout: 60000 });
await page.waitForTimeout(2000);
const body = page.locator("div[contenteditable='true'][role='textbox']").first();
await body.click();
await page.evaluate(async ({ html, plain }) => {
  const item = new ClipboardItem({
    "text/html": new Blob([html], { type: "text/html" }),
    "text/plain": new Blob([plain], { type: "text/plain" }),
  });
  await navigator.clipboard.write([item]);
}, { html, plain: "段落内容" });
await page.keyboard.press("Control+V");
await page.waitForTimeout(3000);
const inner = await body.innerHTML();
console.log("INNER_HAS_TABLE", inner.includes("<table"));
await page.locator("textarea[placeholder*='标题']").first().click();
await page.waitForTimeout(12000);
const url = page.url();
await page.goto(url, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(4000);
const reloadInner = await page.locator("div[contenteditable='true'][role='textbox']").first().innerHTML();
console.log("RELOAD_HAS_TABLE", reloadInner.includes("<table"), "URL", url);
await browser.close();
