import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { clearStaleChromiumSingletonLocks } from "./profile_lock.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const AIMAGICIAN_ROOT = path.resolve(__dirname, "..");
const DEFAULT_PROFILE_DIR = path.resolve(__dirname, "credentials/infoq-browser-profile");
const DEFAULT_HOME_URL = "https://xie.infoq.cn/";
const DEFAULT_EDITOR_URL = process.env.INFOQ_EDITOR_URL || "https://xie.infoq.cn/write";
const DEFAULT_DRAFTBOX_URL = process.env.INFOQ_DRAFTBOX_URL || "https://xie.infoq.cn/draftbox";
const DEFAULT_LOGIN_URL = process.env.INFOQ_LOGIN_URL
  || `https://account.geekbang.org/infoq/login/sms?redirect=${encodeURIComponent(DEFAULT_EDITOR_URL)}`;
const DEFAULT_SMS_CODE_FILE = path.resolve(__dirname, "credentials/infoq-sms-code.txt");
const DEFAULT_LOCALE = process.env.INFOQ_BROWSER_LOCALE || "zh-CN";
const DEFAULT_TIMEZONE = process.env.INFOQ_BROWSER_TIMEZONE || "Asia/Shanghai";
const DEFAULT_USER_AGENT = process.env.INFOQ_BROWSER_USER_AGENT
  || "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36";
const DEFAULT_PHONE_NUMBER = trimText(
  process.env.INFOQ_PHONE
  || process.env.INFOQ_USERNAME
  || process.env.AIMAGICIAN_PLATFORM_LOGIN_PHONE
  || "",
);
const INFOQ_AUTH_URL = "https://account.infoq.cn/serv/v1/user/auth";
const PUBLIC_URL_PATTERN = /^https:\/\/xie\.infoq\.cn\/article\/[a-z0-9]+(?:[/?#].*)?$/i;
const AUTHOR_ROUTE_PATTERN = /https:\/\/xie\.infoq\.cn\/(?:write|draftbox|draft\/[a-z0-9-]+|edit\/[a-z0-9-]+)/i;
const LOGIN_HINT_MARKERS = [
  "手机号验证码登录",
  "账号密码登录",
  "还没有账号",
  "去注册",
  "去登录",
  "用户登录",
  "用户注册",
];
const MANUAL_CLEARANCE_MARKERS = [
  "图形验证码",
  "请完成验证",
  "安全验证",
  "滑块",
  "拼图",
  "人机验证",
  "验证后继续",
];
const PUBLISH_SUCCESS_MARKERS = [
  "发布成功",
  "发布完成",
  "提交成功",
  "审核中",
  "发布于",
];
const TITLE_SELECTORS = [
  "input[placeholder*='标题']",
  "textarea[placeholder*='标题']",
  "input[aria-label*='标题']",
];
const BODY_SELECTORS = [
  ".ProseMirror",
  ".ql-editor",
  "[contenteditable='true']",
  "div[role='textbox']",
  "textarea[placeholder*='正文']",
  "textarea",
];
const MARKDOWN_ENTRY_SELECTORS = [
  "[markdown='true']",
  ".item_main_jMl1q[markdown='true']",
  "[data-position='bottom'][markdown='true']",
];
const MARKDOWN_FILE_INPUT_SELECTORS = [
  "input[type='file'][accept*='.md']",
  "input[type='file'][accept*='markdown']",
  "input[type='file']",
];
const MARKDOWN_TEXTAREA_SELECTORS = [
  ".monaco-editor textarea",
  ".CodeMirror textarea",
  ".ace_text-input",
  "textarea[placeholder*='Markdown']",
  "textarea[placeholder*='markdown']",
  "textarea",
];
const MARKDOWN_APPLY_SELECTORS = [
  "button:has-text('导入')",
  "button:has-text('上传')",
  "button:has-text('确认')",
  "button:has-text('完成')",
  "[role='button']:has-text('导入')",
  "[role='button']:has-text('上传')",
  "[role='button']:has-text('确认')",
  "[role='button']:has-text('完成')",
];
const PUBLISH_DIALOG_SELECTORS = [
  ".dialog-setting .Modal_gk-modal-main_2eGmU",
  ".dialog-setting .content",
];
const SUMMARY_TEXTAREA_SELECTORS = [
  ".dialog-setting textarea[placeholder*='120字']",
  ".dialog-setting .summary textarea",
  ".dialog-setting textarea",
];
const TAG_OPEN_SELECTORS = [
  "text=添加标签",
  "text=选择标签",
  "text=标签",
];
const TAG_INPUT_SELECTORS = [
  ".dialog-setting input[placeholder*='标签']",
  ".dialog-setting .search-tag input[type='text']",
  "input[placeholder*='标签']",
  "textarea[placeholder*='标签']",
  "input[aria-label*='标签']",
  "[contenteditable='true'][aria-placeholder*='标签']",
];
const COPYRIGHT_SELECT_SELECTORS = [
  ".dialog-setting .copyright-select",
  ".dialog-setting .copyright .Select_select-label_3BiyK",
  ".dialog-setting .copyright",
];
const COPYRIGHT_OPTION_SELECTORS = [
  ".Select_select-option_1LHGz",
  "[role='option']",
  ".el-select-dropdown__item",
  ".ant-select-item-option",
];
const COPYRIGHT_OPEN_SELECTORS = [
  ...COPYRIGHT_SELECT_SELECTORS,
  "text=版权声明",
  "text=版权",
];
const PUBLISH_BUTTON_SELECTORS = [
  ".submit-btn",
  "button:has-text('发布')",
  "[role='button']:has-text('发布')",
  "text=发布",
];
const FINAL_PUBLISH_SELECTORS = [
  ".dialog-setting .dialog-footer-buttons .Button_button_3onsJ:has-text('确定')",
  ".dialog-setting .Button_button_3onsJ:has-text('确定')",
  ".dialog-setting [role='button']:has-text('确定')",
  "[role='dialog'] button:has-text('确认发布')",
  ".el-dialog button:has-text('确认发布')",
  ".ant-modal button:has-text('确认发布')",
  "[role='dialog'] button:has-text('发布')",
  ".el-dialog button:has-text('发布')",
  ".ant-modal button:has-text('发布')",
];
const CREATE_DRAFT_SELECTORS = [
  "text=立即创作",
  "button:has-text('立即创作')",
  "[role='button']:has-text('立即创作')",
  "a:has-text('立即创作')",
];
const DRAFT_LIMIT_MARKERS = [
  "草稿箱已满",
  "草稿数量已达上限",
  "无法新建内容",
];
const DRAFTBOX_ENTRY_SELECTORS = [
  "button:has-text('前往草稿箱')",
  "[role='button']:has-text('前往草稿箱')",
  "text=前往草稿箱",
  "a:has-text('草稿箱')",
  "[role='button']:has-text('草稿箱')",
  "text=草稿箱",
];
const DRAFT_EDIT_SELECTORS = [
  "a:has-text('编辑')",
  "button:has-text('编辑')",
  "[role='button']:has-text('编辑')",
  "text=编辑",
];
const SMS_PHONE_INPUT_SELECTORS = [
  "input[name='cellphone']",
  "input[placeholder*='手机号']",
  "input[autocomplete='tel']",
  "input[type='tel']",
  "input[inputmode='numeric']",
];
const SMS_CODE_INPUT_SELECTORS = [
  "input[name='code']",
  "input[placeholder*='验证码']",
  "input[inputmode='numeric']",
];
const SMS_SEND_CODE_SELECTORS = [
  ".Captcha_send-button_11DEX",
  "div:has-text('获取验证码')",
  "button:has-text('获取验证码')",
  "[role='button']:has-text('获取验证码')",
  "text=获取验证码",
];
const AGREEMENT_CHECKBOX_SELECTORS = [
  "#agree",
  "input[type='checkbox']#agree",
  "input[type='checkbox']",
];
const LOGIN_SUBMIT_SELECTORS = [
  ".LoginForm_button-wrapper_FOiki .Button_button_3onsJ",
  "div:has-text('登录')",
  "button:has-text('登录')",
  "[role='button']:has-text('登录')",
  "text=登录",
];
const BLOCKING_MODAL_ACK_SELECTORS = [
  ".Button_button_3onsJ:has-text('知道了')",
  "button:has-text('知道了')",
  "[role='button']:has-text('知道了')",
  "text=知道了",
];

function parseArgs(argv) {
  const result = { _: [] };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) {
      result._.push(token);
      continue;
    }
    const key = token.slice(2);
    const next = argv[index + 1];
    if (next && !next.startsWith("--")) {
      result[key] = next;
      index += 1;
      continue;
    }
    result[key] = "true";
  }
  return result;
}

function parseBool(value, fallback = false) {
  if (value === undefined) {
    return fallback;
  }
  return String(value).toLowerCase() === "true";
}

function trimText(value) {
  return String(value || "").trim();
}

function truncateByChars(value, maxChars) {
  const chars = Array.from(trimText(value));
  const limit = Math.max(0, Number(maxChars) || 0);
  if (!limit || chars.length <= limit) {
    return chars.join("");
  }
  return chars.slice(0, limit).join("");
}

function normalizeText(value) {
  return trimText(value).replace(/\s+/g, " ").trim().toLowerCase();
}

function uniqueStrings(items) {
  const output = [];
  const seen = new Set();
  for (const item of items || []) {
    const text = trimText(item);
    const key = text.toLowerCase();
    if (!text || seen.has(key)) {
      continue;
    }
    seen.add(key);
    output.push(text);
  }
  return output;
}

async function writeJson(jsonPath, value) {
  await fs.mkdir(path.dirname(jsonPath), { recursive: true });
  await fs.writeFile(jsonPath, JSON.stringify(value, null, 2), "utf8");
}

async function readOptionalTrimmedFile(targetPath) {
  if (!targetPath) {
    return "";
  }
  try {
    const raw = await fs.readFile(targetPath, "utf8");
    return trimText(raw);
  } catch {
    return "";
  }
}

async function checkpointResult(args, value) {
  const outputFile = trimText(args["output-file"]);
  if (!outputFile) {
    return;
  }
  await writeJson(outputFile, value);
}

async function checkpointProgress(args, step, extra = {}) {
  await checkpointResult(args, {
    status: "running",
    step,
    ...extra,
  });
}

async function pathExists(targetPath) {
  if (!targetPath) {
    return false;
  }
  try {
    await fs.access(targetPath);
    return true;
  } catch {
    return false;
  }
}

async function safeInnerText(page) {
  if (!page || page.isClosed()) {
    return "";
  }
  return await page.locator("body").innerText().catch(() => "");
}

function evidenceDirFromArgs(args) {
  const raw = trimText(args["evidence-dir"]);
  return raw ? path.resolve(raw) : "";
}

function sanitizeFileStem(value) {
  return trimText(value)
    .replace(/[^a-z0-9._-]+/gi, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 80) || "infoq";
}

async function capturePageEvidence(page, args, label, extra = {}) {
  const evidenceDir = evidenceDirFromArgs(args);
  if (!evidenceDir || !page || page.isClosed()) {
    return null;
  }
  await fs.mkdir(evidenceDir, { recursive: true });
  const stem = `${Date.now()}-${sanitizeFileStem(label)}`;
  const screenshotPath = path.join(evidenceDir, `${stem}.png`);
  const metadataPath = path.join(evidenceDir, `${stem}.json`);
  let screenshotWritten = false;
  try {
    await page.screenshot({ path: screenshotPath, fullPage: true });
    screenshotWritten = true;
  } catch {}
  const bodyText = await safeInnerText(page);
  const payload = {
    label,
    url: page.url(),
    page_title: await page.title().catch(() => ""),
    body_excerpt: bodyText.slice(0, 5000),
    captured_at: new Date().toISOString(),
    ...extra,
  };
  await writeJson(metadataPath, payload);
  return {
    dir: evidenceDir,
    label,
    screenshot_path: screenshotWritten ? screenshotPath : "",
    metadata_path: metadataPath,
    url: payload.url,
    page_title: payload.page_title,
  };
}

function firstMatchingMarker(text, markers) {
  const haystack = String(text || "");
  for (const marker of markers) {
    if (haystack.includes(marker)) {
      return marker;
    }
  }
  return "";
}

function textIncludesAny(text, markers) {
  return Boolean(firstMatchingMarker(text, markers));
}

async function resetSmsCodeFile(targetPath) {
  if (!targetPath) {
    return false;
  }
  try {
    await fs.mkdir(path.dirname(targetPath), { recursive: true });
    await fs.writeFile(targetPath, "", "utf8");
    return true;
  } catch {
    return false;
  }
}

async function isVisibleLocator(locator) {
  return await locator.isVisible({ timeout: 1500 }).catch(() => false);
}

async function resolveLocator(page, selector) {
  return page.locator(selector).first();
}

async function findVisibleSelector(page, selectors) {
  for (const selector of selectors) {
    const locator = await resolveLocator(page, selector);
    if (await isVisibleLocator(locator)) {
      return selector;
    }
  }
  return "";
}

async function firstVisibleLocator(page, selectors) {
  for (const selector of selectors) {
    const locator = await resolveLocator(page, selector);
    if (await isVisibleLocator(locator)) {
      return { selector, locator };
    }
  }
  return null;
}

async function waitForFirstVisibleLocator(page, selectors, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const match = await firstVisibleLocator(page, selectors);
    if (match) {
      return match;
    }
    await page.waitForTimeout(200);
  }
  return null;
}

async function readFirstVisibleText(page, selectors) {
  const match = await firstVisibleLocator(page, selectors);
  if (!match) {
    return { selector: "", text: "" };
  }
  const text = trimText(await match.locator.innerText().catch(() => ""));
  return { selector: match.selector, text };
}

async function clickFirstVisible(page, selectors, { timeoutMs = 3000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const selector of selectors) {
      const locator = await resolveLocator(page, selector);
      if (!await isVisibleLocator(locator)) {
        continue;
      }
      try {
        await locator.click({ timeout: 1500 });
        return selector;
      } catch {
        try {
          await locator.click({ timeout: 1500, force: true });
          return selector;
        } catch {}
      }
    }
    await page.waitForTimeout(200);
  }
  return "";
}

async function clickFirstMatchingText(page, selectors, hints) {
  const normalizedHints = uniqueStrings(hints).map((item) => normalizeText(item)).filter(Boolean);
  if (!normalizedHints.length) {
    return null;
  }
  for (const selector of selectors) {
    const locator = page.locator(selector);
    const count = await locator.count().catch(() => 0);
    for (let index = 0; index < count; index += 1) {
      const item = locator.nth(index);
      const text = trimText(await item.innerText().catch(() => ""));
      if (!text) {
        continue;
      }
      const normalized = normalizeText(text);
      if (!normalizedHints.some((hint) => normalized.includes(hint))) {
        continue;
      }
      try {
        await item.click({ timeout: 1500 });
        return { selector, matchedText: text };
      } catch {
        try {
          await item.click({ timeout: 1500, force: true });
          return { selector, matchedText: text };
        } catch {}
      }
    }
  }
  return null;
}

async function clickVisibleOptionByText(page, selectors, desiredText, { timeoutMs = 3000 } = {}) {
  const desired = normalizeText(desiredText);
  if (!desired) {
    return null;
  }
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    let fuzzyMatch = null;
    for (const selector of selectors) {
      const locator = page.locator(selector);
      const count = await locator.count().catch(() => 0);
      for (let index = 0; index < count; index += 1) {
        const item = locator.nth(index);
        if (!await isVisibleLocator(item)) {
          continue;
        }
        const text = trimText(await item.innerText().catch(() => ""));
        if (!text) {
          continue;
        }
        const normalized = normalizeText(text);
        const match = { selector, locator: item, matchedText: text };
        if (normalized === desired) {
          try {
            await item.click({ timeout: 1500 });
            return match;
          } catch {
            try {
              await item.click({ timeout: 1500, force: true });
              return match;
            } catch {}
          }
          continue;
        }
        if (!fuzzyMatch && normalized.includes(desired)) {
          fuzzyMatch = match;
        }
      }
    }
    if (fuzzyMatch) {
      try {
        await fuzzyMatch.locator.click({ timeout: 1500 });
        return fuzzyMatch;
      } catch {
        try {
          await fuzzyMatch.locator.click({ timeout: 1500, force: true });
          return fuzzyMatch;
        } catch {}
      }
    }
    await page.waitForTimeout(200);
  }
  return null;
}

async function setLocatorValue(locator, page, text) {
  const normalized = String(text || "");
  const tagName = await locator.evaluate((node) => node.tagName).catch(() => "");
  const isContentEditable = await locator.evaluate((node) => Boolean(node.isContentEditable)).catch(() => false);
  if (tagName === "INPUT" || tagName === "TEXTAREA") {
    try {
      await locator.click({ timeout: 1500 });
      await locator.fill(normalized, { timeout: 3000 });
      return true;
    } catch {}
  }
  if (isContentEditable || !tagName) {
    try {
      await locator.click({ timeout: 1500 });
      await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A").catch(() => null);
      await page.keyboard.press("Backspace").catch(() => null);
      await page.keyboard.insertText(normalized).catch(() => null);
      return true;
    } catch {}
  }
  try {
    await locator.evaluate((node, value) => {
      if ("value" in node) {
        node.value = value;
        node.dispatchEvent(new Event("input", { bubbles: true }));
        node.dispatchEvent(new Event("change", { bubbles: true }));
        return;
      }
      node.textContent = value;
      node.dispatchEvent(new Event("input", { bubbles: true }));
      node.dispatchEvent(new Event("change", { bubbles: true }));
    }, normalized);
    return true;
  } catch {
    return false;
  }
}

async function createTempMarkdownFile(markdown) {
  const baseDir = await fs.mkdtemp(path.join(os.tmpdir(), "aimagician-infoq-md-"));
  const filePath = path.join(baseDir, "article.md");
  await fs.writeFile(filePath, String(markdown || ""), "utf8");
  return filePath;
}

async function pickMarkdownTextarea(page) {
  for (const selector of MARKDOWN_TEXTAREA_SELECTORS) {
    const locator = page.locator(selector);
    const count = await locator.count().catch(() => 0);
    for (let index = 0; index < count; index += 1) {
      const item = locator.nth(index);
      if (!await isVisibleLocator(item)) {
        continue;
      }
      const meta = await item.evaluate((node) => ({
        placeholder: String(node.getAttribute?.("placeholder") || ""),
        ariaLabel: String(node.getAttribute?.("aria-label") || ""),
        rows: Number(node.getAttribute?.("rows") || 0),
        valueLength: typeof node.value === "string" ? node.value.length : 0,
      })).catch(() => null);
      const placeholder = normalizeText(`${meta?.placeholder || ""} ${meta?.ariaLabel || ""}`);
      if (placeholder.includes("标题") || placeholder.includes("摘要") || placeholder.includes("标签")) {
        continue;
      }
      return { selector, locator: item };
    }
  }
  return null;
}

async function tryFillBodyViaMarkdownMode(page, markdown) {
  const normalized = trimText(markdown);
  if (!normalized) {
    return {
      applied: false,
      selector: "",
      method: "",
      reason: "markdown_missing",
    };
  }
  const entry = await firstVisibleLocator(page, MARKDOWN_ENTRY_SELECTORS);
  if (!entry) {
    return {
      applied: false,
      selector: "",
      method: "",
      reason: "markdown_entry_not_found",
    };
  }
  try {
    await entry.locator.click({ timeout: 2000 });
  } catch {
    try {
      await entry.locator.click({ timeout: 2000, force: true });
    } catch {
      return {
        applied: false,
        selector: entry.selector,
        method: "",
        reason: "markdown_entry_click_failed",
      };
    }
  }
  await page.waitForTimeout(1200);

  const fileInput = await firstVisibleLocator(page, MARKDOWN_FILE_INPUT_SELECTORS);
  if (fileInput) {
    const markdownFile = await createTempMarkdownFile(normalized);
    try {
      await fileInput.locator.setInputFiles(markdownFile);
      await page.waitForTimeout(1500);
      await clickFirstVisible(page, MARKDOWN_APPLY_SELECTORS, { timeoutMs: 1500 }).catch(() => "");
      return {
        applied: true,
        selector: entry.selector,
        method: "markdown_file_upload",
        markdown_file: markdownFile,
        reason: "",
      };
    } catch {
      return {
        applied: false,
        selector: entry.selector,
        method: "markdown_file_upload",
        markdown_file: markdownFile,
        reason: "markdown_file_upload_failed",
      };
    }
  }

  const markdownTextarea = await pickMarkdownTextarea(page);
  if (markdownTextarea) {
    const applied = await setLocatorValue(markdownTextarea.locator, page, normalized);
    if (applied) {
      await page.waitForTimeout(500);
      await clickFirstVisible(page, MARKDOWN_APPLY_SELECTORS, { timeoutMs: 1500 }).catch(() => "");
      return {
        applied: true,
        selector: `${entry.selector} -> ${markdownTextarea.selector}`,
        method: "markdown_textarea",
        reason: "",
      };
    }
    return {
      applied: false,
      selector: `${entry.selector} -> ${markdownTextarea.selector}`,
      method: "markdown_textarea",
      reason: "markdown_textarea_fill_failed",
    };
  }

  return {
    applied: false,
    selector: entry.selector,
    method: "",
    reason: "markdown_mode_surface_not_found",
  };
}

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderInlineMarkdownToHtml(text) {
  let html = escapeHtml(text);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return html;
}

function inferImageRole(alt) {
  const normalized = trimText(alt);
  if (!normalized) {
    return "body";
  }
  if (normalized === "封面图") {
    return "cover";
  }
  if (normalized === "文末收口图") {
    return "footer";
  }
  if (normalized.startsWith("SVGDIAGRAM::")) {
    return "svg";
  }
  return "body";
}

function sanitizeImageCaption(caption, fallbackAlt) {
  const normalizedCaption = trimText(caption);
  if (normalizedCaption) {
    return normalizedCaption;
  }
  const normalizedAlt = trimText(fallbackAlt);
  if (!normalizedAlt || normalizedAlt === "封面图" || normalizedAlt === "文末收口图") {
    return "";
  }
  if (normalizedAlt.startsWith("SVGDIAGRAM::")) {
    return trimText(normalizedAlt.replace(/^SVGDIAGRAM::/, ""));
  }
  return normalizedAlt;
}

function expandCompactMarkdownTables(markdown) {
  const raw = String(markdown || "");
  if (!raw.includes("| |") || !raw.includes("---")) {
    return raw;
  }
  const lines = raw.split(/\r?\n/);
  return lines.map((line) => {
    const trimmed = trimText(line);
    if (!trimmed.startsWith("|") || !trimmed.includes("| |") || !trimmed.includes("---")) {
      return line;
    }
    return line.replace(/\|\s+\|/g, "|\n|");
  }).join("\n");
}

function parseMarkdownBodyBlocks(markdown) {
  const text = trimText(expandCompactMarkdownTables(markdown));
  if (!text) {
    return [];
  }
  const lines = text.split(/\r?\n/);
  const blocks = [];
  let paragraph = [];
  let listBlock = null;
  let quoteBlock = [];
  let codeBlock = null;
  let tableBlock = null;

  const flushParagraph = () => {
    const merged = trimText(paragraph.join("\n"));
    if (merged) {
      blocks.push({ type: "text", text: merged });
    }
    paragraph = [];
  };

  const flushList = () => {
    if (!listBlock || !Array.isArray(listBlock.items) || !listBlock.items.length) {
      listBlock = null;
      return;
    }
    blocks.push(listBlock);
    listBlock = null;
  };

  const flushQuote = () => {
    const merged = trimText(quoteBlock.join("\n"));
    if (merged) {
      blocks.push({ type: "quote", text: merged });
    }
    quoteBlock = [];
  };

  const flushCode = () => {
    if (!codeBlock) {
      return;
    }
    blocks.push(codeBlock);
    codeBlock = null;
  };

  const flushTable = () => {
    if (!tableBlock || !Array.isArray(tableBlock.header) || !tableBlock.header.length) {
      tableBlock = null;
      return;
    }
    if (!Array.isArray(tableBlock.rows)) {
      tableBlock.rows = [];
    }
    blocks.push(tableBlock);
    tableBlock = null;
  };

  const parseMarkdownTableRow = (raw) => {
    const line = trimText(raw);
    if (!line.includes("|")) {
      return null;
    }
    const normalized = line.replace(/^\|/, "").replace(/\|$/, "");
    const cells = normalized.split("|").map((cell) => trimText(cell));
    return cells.some(Boolean) ? cells : null;
  };

  const isMarkdownTableDivider = (raw) => {
    const cells = parseMarkdownTableRow(raw);
    if (!cells || !cells.length) {
      return false;
    }
    return cells.every((cell) => /^:?-{3,}:?$/.test(cell));
  };

  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const rawLine = lines[lineIndex];
    const line = trimText(rawLine);
    if (codeBlock) {
      if (/^```/.test(line)) {
        flushCode();
      } else {
        codeBlock.code.push(rawLine.replace(/\r$/, ""));
      }
      continue;
    }

    if (!line || line === "---") {
      flushParagraph();
      flushList();
      flushQuote();
      flushTable();
      continue;
    }

    if (/^```/.test(line)) {
      flushParagraph();
      flushList();
      flushQuote();
      flushTable();
      codeBlock = {
        type: "code",
        language: trimText(line.replace(/^```/, "")),
        code: [],
      };
      continue;
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      flushQuote();
      flushTable();
      blocks.push({
        type: "heading",
        level: Math.min(4, headingMatch[1].length),
        text: trimText(headingMatch[2]),
      });
      continue;
    }

    const imageMatch = line.match(/^!\[(.*?)\]\((https?:\/\/[^\s)]+)\)$/i);
    if (imageMatch) {
      flushParagraph();
      flushList();
      flushQuote();
      flushTable();
      blocks.push({
        type: "image",
        alt: trimText(imageMatch[1]) || "配图",
        url: trimText(imageMatch[2]),
        role: inferImageRole(imageMatch[1]),
        caption: "",
      });
      continue;
    }

    const quoteMatch = rawLine.match(/^\s*>\s?(.*)$/);
    if (quoteMatch) {
      const quoteText = trimText(quoteMatch[1]);
      const lastBlock = blocks.at(-1);
      if (lastBlock?.type === "image" && quoteText) {
        lastBlock.caption = quoteText;
      } else if (quoteText) {
        flushParagraph();
        flushList();
        flushTable();
        quoteBlock.push(quoteText);
      }
      continue;
    }

    const currentRow = parseMarkdownTableRow(rawLine);
    if (currentRow) {
      const nextRawLine = lines[lineIndex + 1];
      if (!tableBlock && nextRawLine && isMarkdownTableDivider(nextRawLine)) {
        flushParagraph();
        flushList();
        flushQuote();
        tableBlock = {
          type: "table",
          header: currentRow,
          rows: [],
        };
        continue;
      }
      if (tableBlock) {
        if (!isMarkdownTableDivider(rawLine)) {
          tableBlock.rows.push(currentRow);
        }
        continue;
      }
    } else if (tableBlock) {
      flushTable();
    }

    const orderedMatch = line.match(/^\d+\.\s+(.+)$/);
    if (orderedMatch) {
      flushParagraph();
      flushQuote();
      flushTable();
      if (!listBlock || listBlock.ordered !== true) {
        flushList();
        listBlock = { type: "list", ordered: true, items: [] };
      }
      listBlock.items.push(trimText(orderedMatch[1]));
      continue;
    }

    const unorderedMatch = line.match(/^[-*+]\s+(.+)$/);
    if (unorderedMatch) {
      flushParagraph();
      flushQuote();
      flushTable();
      if (!listBlock || listBlock.ordered !== false) {
        flushList();
        listBlock = { type: "list", ordered: false, items: [] };
      }
      listBlock.items.push(trimText(unorderedMatch[1]));
      continue;
    }

    flushList();
    flushQuote();
    flushTable();
    paragraph.push(line);
  }
  flushParagraph();
  flushList();
  flushQuote();
  flushTable();
  flushCode();
  return blocks;
}

function blocksToRichEditorHtml(blocks) {
  return blocks.map((block) => {
    if (block.type === "heading") {
      const level = Number(block.level || 2);
      const tag = level <= 2 ? "h2" : level === 3 ? "h3" : "h4";
      const fontSize = tag === "h2" ? "28px" : tag === "h3" ? "22px" : "18px";
      return `<${tag} style="margin:28px 0 12px;font-size:${fontSize};font-weight:700;line-height:1.5;">${renderInlineMarkdownToHtml(block.text || "")}</${tag}>`;
    }
    if (block.type === "image") {
      const src = escapeHtml(block.url);
      const alt = escapeHtml(block.alt || "配图");
      const caption = sanitizeImageCaption(block.caption, block.alt);
      const captionHtml = caption
        ? `<figcaption style="margin-top:6px;color:#8590a6;font-size:13px;line-height:1.6;">${escapeHtml(caption)}</figcaption>`
        : "";
      if (block.role === "cover" || block.role === "footer") {
        return `<p style="margin:20px 0;text-align:center;"><img src="${src}" alt="${alt}" style="max-width:100%;height:auto;" /></p><p><br></p>`;
      }
      return `<figure data-aimagician-block="image" style="margin:20px 0;text-align:center;"><img src="${src}" alt="${alt}" style="max-width:100%;height:auto;" />${captionHtml}</figure><p><br></p>`;
    }
    if (block.type === "quote") {
      return `<blockquote style="margin:16px 0;padding:6px 0 6px 14px;border-left:3px solid #dfe2e5;color:#646a73;">${String(block.text || "").split(/\n+/).map((line) => `<p>${renderInlineMarkdownToHtml(line)}</p>`).join("")}</blockquote>`;
    }
    if (block.type === "list") {
      const tag = block.ordered ? "ol" : "ul";
      const items = (Array.isArray(block.items) ? block.items : [])
        .map((item) => `<li>${renderInlineMarkdownToHtml(item)}</li>`)
        .join("");
      return `<${tag} style="margin:14px 0 14px 22px;line-height:1.8;">${items}</${tag}>`;
    }
    if (block.type === "code") {
      const language = trimText(block.language || "");
      const code = escapeHtml(Array.isArray(block.code) ? block.code.join("\n") : "");
      const languageBadge = language
        ? `<div style="margin:0 0 6px;color:#8590a6;font-size:12px;">${escapeHtml(language)}</div>`
        : "";
      return `<div style="margin:18px 0;">${languageBadge}<pre style="margin:0;padding:14px 16px;background:#f6f8fa;border-radius:6px;overflow:auto;"><code>${code}</code></pre></div>`;
    }
    if (block.type === "table") {
      const header = Array.isArray(block.header) ? block.header : [];
      const rows = Array.isArray(block.rows) ? block.rows : [];
      const thead = header.length
        ? `<thead><tr>${header.map((cell) => `<th style="padding:10px 12px;border:1px solid #e5e6eb;background:#f6f8fa;font-weight:600;text-align:left;">${renderInlineMarkdownToHtml(cell)}</th>`).join("")}</tr></thead>`
        : "";
      const tbody = rows.length
        ? `<tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td style="padding:10px 12px;border:1px solid #e5e6eb;vertical-align:top;">${renderInlineMarkdownToHtml(cell)}</td>`).join("")}</tr>`).join("")}</tbody>`
        : "";
      return `<div style="margin:18px 0;overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:14px;line-height:1.7;">${thead}${tbody}</table></div>`;
    }
    const lines = String(block.text || "")
      .split(/\n+/)
      .map((line) => trimText(line))
      .filter(Boolean)
      .map((line) => `<p>${renderInlineMarkdownToHtml(line)}</p>`);
    return lines.join("");
  }).join("");
}

async function fillEditableLocator(locator, page, text) {
  try {
    const info = await locator.evaluate((node) => ({
      tagName: String(node.tagName || "").toLowerCase(),
      contentEditable: String(node.getAttribute("contenteditable") || ""),
    })).catch(() => ({ tagName: "", contentEditable: "" }));
    if (info.tagName === "input" || info.tagName === "textarea") {
      await locator.click({ timeout: 5000 });
      await locator.fill(text, { timeout: 5000 });
      return true;
    }
    await locator.click({ timeout: 5000 });
    await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A").catch(() => null);
    await page.keyboard.press("Backspace").catch(() => null);
    await page.keyboard.insertText(text);
    return true;
  } catch {
    return false;
  }
}

async function fillRichBodyLocator(locator, page, markdown, fallbackText) {
  if (!locator) {
    return false;
  }
  const blocks = parseMarkdownBodyBlocks(markdown);
  if (!blocks.length) {
    return fillEditableLocator(locator, page, fallbackText);
  }
  try {
    await locator.click({ timeout: 5000 });
    await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A").catch(() => null);
    await page.keyboard.press("Backspace").catch(() => null);
    const html = blocksToRichEditorHtml(blocks);
    const applied = await locator.evaluate((node, payload) => {
      node.focus();
      node.innerHTML = payload.html;
      node.dispatchEvent(new InputEvent("input", {
        bubbles: true,
        cancelable: true,
        inputType: "insertFromPaste",
        data: payload.fallbackText,
      }));
      node.dispatchEvent(new Event("change", { bubbles: true }));
      return Boolean(String(node.innerHTML || "").trim());
    }, {
      html,
      fallbackText: String(fallbackText || "").slice(0, 120),
    }).catch(() => false);
    if (applied) {
      return true;
    }
  } catch {}
  return fillEditableLocator(locator, page, fallbackText);
}

async function collectDialogTagTexts(page) {
  const tags = await page.locator(".dialog-setting .label-item").evaluateAll((nodes) => (
    nodes.map((node) => {
      const raw = String(node.innerText || "").trim();
      return raw.split(/\n+/)[0].trim();
    }).filter(Boolean)
  )).catch(() => []);
  return uniqueStrings(tags);
}

async function fillSummary(page, summaryText) {
  const desired = truncateByChars(trimText(summaryText), 120);
  const selector = await findVisibleSelector(page, SUMMARY_TEXTAREA_SELECTORS);
  if (!selector) {
    return {
      applied: false,
      selector: "",
      reason: desired ? "summary_input_not_found" : "",
      length: Array.from(desired).length,
    };
  }
  if (!desired) {
    return {
      applied: true,
      selector,
      reason: "",
      length: 0,
    };
  }
  const locator = await resolveLocator(page, selector);
  const applied = await setLocatorValue(locator, page, desired);
  return {
    applied,
    selector,
    reason: applied ? "" : "summary_fill_failed",
    length: Array.from(desired).length,
  };
}

async function dismissBlockingPrompts(page) {
  const selectors = [];
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const selector = await clickFirstVisible(page, BLOCKING_MODAL_ACK_SELECTORS, { timeoutMs: 800 });
    if (!selector) {
      break;
    }
    selectors.push(selector);
    await page.waitForTimeout(500);
  }
  return {
    dismissed: selectors.length > 0,
    selectors,
  };
}

async function ensureAgreementAccepted(page) {
  for (const selector of AGREEMENT_CHECKBOX_SELECTORS) {
    const locator = await resolveLocator(page, selector);
    if (!await isVisibleLocator(locator)) {
      continue;
    }
    const checked = await locator.isChecked().catch(() => false);
    if (checked) {
      return {
        ok: true,
        selector,
        alreadyChecked: true,
      };
    }
    try {
      await locator.check({ timeout: 1500 });
    } catch {
      try {
        await locator.click({ timeout: 1500, force: true });
      } catch {
        continue;
      }
    }
    const nowChecked = await locator.isChecked().catch(() => false);
    if (nowChecked) {
      return {
        ok: true,
        selector,
        alreadyChecked: false,
      };
    }
  }
  return {
    ok: false,
    selector: "",
    alreadyChecked: false,
  };
}

async function writeStorageState(context, stateFile) {
  await fs.mkdir(path.dirname(stateFile), { recursive: true });
  await context.storageState({ path: stateFile });
}

async function applyStealthInitScript(context) {
  await context.addInitScript(() => {
    Object.defineProperty(navigator, "webdriver", {
      get: () => undefined,
      configurable: true,
    });
    Object.defineProperty(navigator, "languages", {
      get: () => ["zh-CN", "zh", "en-US", "en"],
      configurable: true,
    });
    Object.defineProperty(navigator, "platform", {
      get: () => "Win32",
      configurable: true,
    });
    Object.defineProperty(navigator, "vendor", {
      get: () => "Google Inc.",
      configurable: true,
    });
    if (!window.chrome) {
      Object.defineProperty(window, "chrome", {
        value: { runtime: {} },
        configurable: true,
      });
    }
  });
}

function browserProfileDir() {
  const raw = trimText(process.env.INFOQ_BROWSER_PROFILE_DIR);
  if (!raw) {
    return DEFAULT_PROFILE_DIR;
  }
  return path.isAbsolute(raw) ? raw : path.resolve(AIMAGICIAN_ROOT, raw);
}

async function launchInfoQContext(options) {
  const { headless, stateFile, preferPersistent = false } = options;
  const persistent = preferPersistent && parseBool(process.env.INFOQ_PERSISTENT_BROWSER, true);
  const launchOptions = {
    headless,
    locale: DEFAULT_LOCALE,
    timezoneId: DEFAULT_TIMEZONE,
    userAgent: DEFAULT_USER_AGENT,
    viewport: { width: 1440, height: 960 },
    extraHTTPHeaders: {
      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    },
    ignoreDefaultArgs: ["--enable-automation"],
    args: [
      "--start-maximized",
      "--lang=zh-CN,zh",
      "--disable-blink-features=AutomationControlled",
    ],
  };

  const launchNonPersistentContext = async () => {
    const browser = await chromium.launch(launchOptions);
    const contextOptions = {
      locale: DEFAULT_LOCALE,
      timezoneId: DEFAULT_TIMEZONE,
      userAgent: DEFAULT_USER_AGENT,
      viewport: { width: 1440, height: 960 },
      extraHTTPHeaders: {
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
      },
    };
    if (stateFile && await pathExists(stateFile)) {
      contextOptions.storageState = stateFile;
    }
    const context = await browser.newContext(contextOptions);
    await applyStealthInitScript(context);
    const page = await context.newPage();
    return { browser, context, page, persistent: false, profileDir: browserProfileDir() };
  };

  if (persistent) {
    const profileDir = browserProfileDir();
    try {
      await clearStaleChromiumSingletonLocks(profileDir);
      const context = await chromium.launchPersistentContext(profileDir, launchOptions);
      await applyStealthInitScript(context);
      const page = context.pages()[0] || await context.newPage();
      return { browser: null, context, page, persistent, profileDir };
    } catch (error) {
      if (!stateFile || !await pathExists(stateFile)) {
        throw error;
      }
    }
  }

  return await launchNonPersistentContext();
}

async function closeRuntime(runtime) {
  const { browser, context } = runtime;
  for (const page of context.pages()) {
    await page.close({ runBeforeUnload: false }).catch(() => null);
  }
  await context.close().catch(() => null);
  if (browser) {
    await browser.close().catch(() => null);
  }
}

function parseSessionCookies(rawSession) {
  const raw = trimText(rawSession);
  if (!raw || !raw.includes("=")) {
    return [];
  }
  const cookies = [];
  for (const part of raw.split(";")) {
    const item = part.trim();
    if (!item || !item.includes("=")) {
      continue;
    }
    const index = item.indexOf("=");
    const name = item.slice(0, index).trim();
    const value = item.slice(index + 1).trim();
    if (!name) {
      continue;
    }
    cookies.push({ name, value });
  }
  return cookies;
}

async function injectSessionCookies(context) {
  const cookies = parseSessionCookies(process.env.INFOQ_SESSION || "");
  if (!cookies.length) {
    return {
      injected: false,
      cookieNames: [],
      reason: "cookie_header_missing",
    };
  }
  const playrightCookies = [];
  for (const cookie of cookies) {
    playrightCookies.push({
      name: cookie.name,
      value: cookie.value,
      domain: ".infoq.cn",
      path: "/",
      httpOnly: false,
      secure: true,
      sameSite: "Lax",
    });
  }
  try {
    await context.addCookies(playrightCookies);
    return {
      injected: true,
      cookieNames: cookies.map((item) => item.name),
      reason: "",
    };
  } catch (error) {
    return {
      injected: false,
      cookieNames: cookies.map((item) => item.name),
      reason: String(error?.message || error),
    };
  }
}

async function fetchAuthState(page) {
  const responseText = await page.evaluate(async (url) => {
    const response = await fetch(url, {
      method: "GET",
      credentials: "include",
      headers: {
        Accept: "application/json, text/plain, */*",
      },
    });
    return await response.text();
  }, INFOQ_AUTH_URL).catch(() => "");
  if (!responseText) {
    return {
      authenticated: false,
      responseCode: -1,
      errorMessage: "auth_probe_failed",
      raw: {},
    };
  }
  let payload = {};
  try {
    payload = JSON.parse(responseText);
  } catch {
    return {
      authenticated: false,
      responseCode: -1,
      errorMessage: "auth_probe_invalid_json",
      raw: {},
    };
  }
  const code = Number(payload.code);
  const errorMessage = trimText(payload?.error?.msg);
  return {
    authenticated: code === 0,
    responseCode: code,
    errorMessage,
    raw: payload,
  };
}

async function pickBestBodySelector(page) {
  for (const selector of BODY_SELECTORS) {
    const locator = await resolveLocator(page, selector);
    if (!await isVisibleLocator(locator)) {
      continue;
    }
    const text = trimText(await locator.innerText().catch(() => ""));
    const isContentEditable = await locator.evaluate((node) => Boolean(node.isContentEditable)).catch(() => false);
    const tagName = await locator.evaluate((node) => node.tagName).catch(() => "");
    if (selector === ".ProseMirror" || isContentEditable || tagName === "TEXTAREA" || text.length >= 0) {
      return selector;
    }
  }
  return "";
}

async function detectSurface(page) {
  const url = trimText(page.url());
  const bodyText = await safeInnerText(page);
  const authState = await fetchAuthState(page);
  const loginMarker = firstMatchingMarker(bodyText, LOGIN_HINT_MARKERS);
  const manualClearanceMarker = firstMatchingMarker(bodyText, MANUAL_CLEARANCE_MARKERS);
  const draftLimitMarker = firstMatchingMarker(bodyText, DRAFT_LIMIT_MARKERS);
  const titleSelector = await findVisibleSelector(page, TITLE_SELECTORS);
  const bodySelector = await pickBestBodySelector(page);
  const tagInputSelector = await findVisibleSelector(page, TAG_INPUT_SELECTORS);
  const publishButtonSelector = await findVisibleSelector(page, PUBLISH_BUTTON_SELECTORS);
  const currentPath = (() => {
    try {
      return new URL(url).pathname || "";
    } catch {
      return "";
    }
  })();
  const previewSurface = /\/preview\/article\//i.test(url);
  const publicSurface = PUBLIC_URL_PATTERN.test(url);
  const authorRoute = AUTHOR_ROUTE_PATTERN.test(url);
  const draftboxSurface = /\/draftbox$/i.test(currentPath);
  const loginSurface = url.includes("account.geekbang.org/infoq/login")
    || Boolean(loginMarker)
    || (!authState.authenticated && authorRoute);
  const editorReady = authorRoute && (
    Boolean(titleSelector || bodySelector || tagInputSelector || publishButtonSelector)
    || (authState.authenticated && !previewSurface && !publicSurface)
  );
  let surface = "unknown";
  if (manualClearanceMarker) {
    surface = "risk";
  } else if (loginSurface) {
    surface = "signin";
  } else if (previewSurface) {
    surface = "preview";
  } else if (publicSurface) {
    surface = "published";
  } else if (draftboxSurface) {
    surface = "draftbox";
  } else if (editorReady) {
    surface = "editor";
  }
  return {
    url,
    currentPath,
    surface,
    authenticated: authState.authenticated,
    authState,
    loginMarker,
    manualClearanceRequired: Boolean(manualClearanceMarker),
    manualClearanceMarker,
    draftLimitReached: Boolean(draftLimitMarker),
    draftLimitMarker,
    titleSelector,
    bodySelector,
    tagInputSelector,
    publishButtonSelector,
    editorReady,
    previewSurface,
    publicSurface,
    bodyExcerpt: bodyText.slice(0, 2000),
  };
}

async function clickWriteButton(page) {
  return await clickFirstVisible(page, [
    ...CREATE_DRAFT_SELECTORS,
    ".write-btn",
    ".write-btn-warp .write-btn",
    "text=写点什么",
    "text=创作",
  ], { timeoutMs: 3000 });
}

async function openDraftbox(page) {
  const clicked = await clickFirstVisible(page, DRAFTBOX_ENTRY_SELECTORS, { timeoutMs: 3000 });
  await page.waitForTimeout(1000);
  const clickedSurface = await detectSurface(page);
  if (clicked && clickedSurface.surface === "draftbox") {
    return clickedSurface;
  }
  await page.goto(DEFAULT_DRAFTBOX_URL, { waitUntil: "domcontentloaded", timeout: 15000 }).catch(() => null);
  await page.waitForTimeout(1200);
  return await detectSurface(page);
}

async function openWriteSurface(page, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let lastSurface = await detectSurface(page);
  let attemptedClickWrite = false;
  let attemptedReload = false;

  if (!lastSurface.url || !AUTHOR_ROUTE_PATTERN.test(lastSurface.url)) {
    await page.goto(DEFAULT_EDITOR_URL, { waitUntil: "domcontentloaded", timeout: Math.min(timeoutMs, 30000) }).catch(() => null);
    await page.waitForTimeout(1200);
    lastSurface = await detectSurface(page);
  }

  while (Date.now() < deadline) {
    lastSurface = await detectSurface(page);
    if (lastSurface.surface === "editor") {
      return lastSurface;
    }
    if (lastSurface.surface === "signin" || lastSurface.surface === "risk") {
      return lastSurface;
    }
    if (lastSurface.draftLimitReached) {
      lastSurface = await openDraftbox(page);
      continue;
    }
    if (lastSurface.surface === "draftbox") {
      const draftLink = page.locator("a[href*='/draft/'], a[href*='/edit/']").first();
      if (await isVisibleLocator(draftLink)) {
        const href = trimText(await draftLink.getAttribute("href").catch(() => ""));
        if (href) {
          await page.goto(new URL(href, DEFAULT_HOME_URL).href, { waitUntil: "domcontentloaded", timeout: 15000 }).catch(() => null);
        } else {
          await draftLink.click({ timeout: 3000 }).catch(() => null);
        }
      } else if (await clickFirstVisible(page, DRAFT_EDIT_SELECTORS, { timeoutMs: 3000 })) {
        // Reuse an existing draft when InfoQ refuses new drafts because the draftbox is full.
      } else if (!attemptedClickWrite) {
        attemptedClickWrite = Boolean(await clickWriteButton(page));
      }
      await page.waitForTimeout(1200);
      continue;
    }
    if (lastSurface.authenticated && !attemptedClickWrite) {
      attemptedClickWrite = Boolean(await clickWriteButton(page));
      await page.waitForTimeout(1200);
      const clickedSurface = await detectSurface(page);
      if (clickedSurface.draftLimitReached) {
        lastSurface = await openDraftbox(page);
      }
      continue;
    }
    if (lastSurface.authenticated && !attemptedReload) {
      attemptedReload = true;
      if (lastSurface.currentPath !== "/write") {
        await page.goto(DEFAULT_EDITOR_URL, { waitUntil: "domcontentloaded", timeout: 15000 }).catch(() => null);
      } else {
        await page.reload({ waitUntil: "domcontentloaded", timeout: 15000 }).catch(() => null);
      }
      await page.waitForTimeout(1500);
      continue;
    }
    await page.waitForTimeout(1000);
  }
  return lastSurface;
}

function isBlankWriteSurface(surface) {
  return Boolean(
    surface
    && surface.authenticated
    && surface.currentPath === "/write"
    && !surface.titleSelector
    && !surface.bodySelector
    && !surface.tagInputSelector
    && !surface.publishButtonSelector
  );
}

async function createDraftFromHome(page, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  await page.goto(DEFAULT_HOME_URL, { waitUntil: "domcontentloaded", timeout: Math.min(timeoutMs, 30000) }).catch(() => null);
  await page.waitForTimeout(1200);
  const createSelector = await clickFirstVisible(page, CREATE_DRAFT_SELECTORS, { timeoutMs: 5000 });
  if (!createSelector) {
    return {
      surface: await detectSurface(page),
      createSelector: "",
      reason: "create_draft_button_missing",
    };
  }
  while (Date.now() < deadline) {
    const surface = await detectSurface(page);
    if (surface.authenticated && surface.currentPath.startsWith("/draft/") && (surface.titleSelector || surface.bodySelector)) {
      return {
        surface,
        createSelector,
        reason: "",
      };
    }
    await page.waitForTimeout(500);
  }
  return {
    surface: await detectSurface(page),
    createSelector,
    reason: "create_draft_route_not_reached",
  };
}

function resolveSmsCodeFile(args) {
  const raw = trimText(args["sms-code-file"] || process.env.INFOQ_SMS_CODE_FILE || DEFAULT_SMS_CODE_FILE);
  return path.isAbsolute(raw) ? raw : path.resolve(AIMAGICIAN_ROOT, raw);
}

function resolvePhoneNumber(args) {
  return trimText(
    args["phone-number"]
    || process.env.INFOQ_PHONE
    || process.env.INFOQ_USERNAME
    || process.env.AIMAGICIAN_PLATFORM_LOGIN_PHONE
    || DEFAULT_PHONE_NUMBER,
  );
}

async function waitForSmsCodeFile(smsCodeFile, timeoutMs) {
  if (!smsCodeFile) {
    return "";
  }
  const deadline = Date.now() + Math.max(timeoutMs, 1000);
  while (Date.now() < deadline) {
    const value = await readOptionalTrimmedFile(smsCodeFile);
    if (/^\d{4,8}$/.test(value)) {
      return value;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return "";
}

async function submitLoginForm(page) {
  const selector = await clickFirstVisible(page, LOGIN_SUBMIT_SELECTORS, { timeoutMs: 2500 });
  if (selector) {
    return {
      submitted: true,
      selector,
    };
  }
  try {
    await page.keyboard.press("Enter");
    return {
      submitted: true,
      selector: "keyboard:Enter",
    };
  } catch {
    return {
      submitted: false,
      selector: "",
    };
  }
}

async function attemptSmsLogin(page, args, timeoutMs, phoneNumber, smsCodeFile) {
  const phone = trimText(phoneNumber);
  const result = {
    ok: false,
    reason: "",
    phone_number: phone,
    sms_code_file: smsCodeFile,
    sms_login_supported: false,
    sms_code_applied: false,
    phone_selector: "",
    code_selector: "",
    send_code_selector: "",
    send_code_text_after_click: "",
    agreement_selector: "",
    submit_selector: "",
    risk_marker_after_click: "",
    sms_code_file_reset: false,
  };
  if (!phone) {
    result.reason = "phone_number_missing";
    return result;
  }

  const phoneMatch = await waitForFirstVisibleLocator(page, SMS_PHONE_INPUT_SELECTORS, Math.min(timeoutMs, 10000));
  const codeMatch = await waitForFirstVisibleLocator(page, SMS_CODE_INPUT_SELECTORS, 4000);
  const sendMatch = await waitForFirstVisibleLocator(page, SMS_SEND_CODE_SELECTORS, 4000);
  result.sms_login_supported = Boolean(phoneMatch && (codeMatch || sendMatch));
  if (!result.sms_login_supported) {
    result.reason = "sms_login_surface_not_detected";
    return result;
  }

  result.phone_selector = phoneMatch?.selector || "";
  const phoneFilled = phoneMatch ? await setLocatorValue(phoneMatch.locator, page, phone) : false;
  if (!phoneFilled) {
    result.reason = "sms_phone_input_not_found";
    return result;
  }

  const agreementResult = await ensureAgreementAccepted(page);
  result.agreement_selector = agreementResult.selector;
  if (!agreementResult.ok) {
    result.reason = "agreement_checkbox_not_found";
    return result;
  }

  const preloadedSmsCode = await readOptionalTrimmedFile(smsCodeFile);
  if (/^\d{4,8}$/.test(preloadedSmsCode)) {
    const refreshedCodeMatch = await waitForFirstVisibleLocator(page, SMS_CODE_INPUT_SELECTORS, 4000);
    result.code_selector = refreshedCodeMatch?.selector || codeMatch?.selector || "";
    const codeFilled = refreshedCodeMatch
      ? await setLocatorValue(refreshedCodeMatch.locator, page, preloadedSmsCode)
      : false;
    if (!codeFilled) {
      result.reason = "sms_code_input_not_found";
      return result;
    }
    result.sms_code_applied = true;

    const submitResult = await submitLoginForm(page);
    result.submit_selector = submitResult.selector;
    if (!submitResult.submitted) {
      result.reason = "sms_login_submit_not_found";
      return result;
    }

    result.ok = true;
    result.reason = "sms_login_submitted";
    return result;
  }

  result.send_code_selector = await clickFirstVisible(page, SMS_SEND_CODE_SELECTORS, { timeoutMs: 2500 });
  if (!result.send_code_selector) {
    result.reason = "sms_send_code_control_not_found";
    return result;
  }
  await page.waitForTimeout(1200);

  const surfaceSignals = await detectSurface(page);
  const sendCodeText = await readFirstVisibleText(page, SMS_SEND_CODE_SELECTORS);
  result.send_code_text_after_click = sendCodeText.text;
  result.risk_marker_after_click = trimText(surfaceSignals.manualClearanceMarker || "");
  if (surfaceSignals.manualClearanceRequired) {
    result.reason = "manual_clearance_required";
    return result;
  }

  const refreshedCodeMatch = await waitForFirstVisibleLocator(page, SMS_CODE_INPUT_SELECTORS, 4000);
  result.code_selector = refreshedCodeMatch?.selector || codeMatch?.selector || "";
  result.sms_code_file_reset = await resetSmsCodeFile(smsCodeFile);
  await checkpointProgress(args, "bootstrap_wait_sms_code", {
    login_mode: "sms",
    phone_number: phone,
    sms_code_file: smsCodeFile,
    sms_login_supported: true,
    sms_send_code_selector: result.send_code_selector,
    sms_send_code_text_after_click: result.send_code_text_after_click,
    agreement_selector: result.agreement_selector,
    risk_marker_after_click: result.risk_marker_after_click,
  });
  const waitedCode = await waitForSmsCodeFile(smsCodeFile, Math.max(timeoutMs - 15000, 60000));
  if (!/^\d{4,8}$/.test(waitedCode || "")) {
    result.reason = "sms_code_required";
    return result;
  }
  const waitedCodeMatch = await waitForFirstVisibleLocator(page, SMS_CODE_INPUT_SELECTORS, 4000);
  result.code_selector = waitedCodeMatch?.selector || result.code_selector;
  const waitedCodeFilled = waitedCodeMatch ? await setLocatorValue(waitedCodeMatch.locator, page, waitedCode) : false;
  if (!waitedCodeFilled) {
    result.reason = "sms_code_input_not_found";
    return result;
  }
  result.sms_code_applied = true;
  const submitResult = await submitLoginForm(page);
  result.submit_selector = submitResult.selector;
  if (!submitResult.submitted) {
    result.reason = "sms_login_submit_not_found";
    return result;
  }
  result.ok = true;
  result.reason = "sms_login_submitted";
  return result;
}

async function bootstrapSession(runtime, args, stateFile, timeoutMs) {
  const { context, page } = runtime;
  const loginMode = trimText(args["login-mode"] || process.env.INFOQ_LOGIN_MODE || "password").toLowerCase();
  const phoneNumber = resolvePhoneNumber(args);
  const smsCodeFile = resolveSmsCodeFile(args);
  await checkpointProgress(args, "bootstrap_open_login", {
    requested_url: DEFAULT_LOGIN_URL,
    login_mode: loginMode,
    phone_number: phoneNumber ? `${phoneNumber.slice(0, 3)}****${phoneNumber.slice(-4)}` : "",
    sms_code_file: smsCodeFile,
  });
  await page.goto(DEFAULT_LOGIN_URL, { waitUntil: "domcontentloaded", timeout: Math.min(timeoutMs, 30000) }).catch(() => null);
  let smsLoginAttempt = {
    ok: false,
    reason: "",
    phone_number: phoneNumber,
    sms_code_file: smsCodeFile,
    sms_login_supported: false,
    sms_code_applied: false,
    phone_selector: "",
    code_selector: "",
    send_code_selector: "",
    agreement_selector: "",
    submit_selector: "",
    sms_code_file_reset: false,
  };
  if (loginMode === "sms") {
    smsLoginAttempt = await attemptSmsLogin(page, args, timeoutMs, phoneNumber, smsCodeFile);
    if (!smsLoginAttempt.ok) {
      const blockedEvidence = await capturePageEvidence(page, args, "bootstrap-session-sms-blocked", {
        login_mode: loginMode,
        phone_number: phoneNumber ? `${phoneNumber.slice(0, 3)}****${phoneNumber.slice(-4)}` : "",
        sms_login_attempt: smsLoginAttempt,
      });
      return {
        status: "blocked",
        mode: "bootstrap-session",
        live_ready: false,
        session_valid: false,
        final_url: page.url(),
        surface: (await detectSurface(page)).surface,
        manual_clearance_required: smsLoginAttempt.reason === "manual_clearance_required",
        final_blocker: smsLoginAttempt.reason || "sms_login_not_completed",
        evidence: blockedEvidence,
        reason: smsLoginAttempt.reason || "sms_login_not_completed",
        sms_login_attempt: smsLoginAttempt,
      };
    }
  }
  const deadline = Date.now() + timeoutMs;
  let lastSurface = await detectSurface(page);

  while (Date.now() < deadline) {
    lastSurface = await detectSurface(page);
    await checkpointProgress(args, "bootstrap_wait_manual_login", {
      current_url: lastSurface.url,
      surface: lastSurface.surface,
      authenticated: lastSurface.authenticated,
      manual_clearance_required: lastSurface.manualClearanceRequired,
    });
    if (lastSurface.authenticated) {
      if (!AUTHOR_ROUTE_PATTERN.test(lastSurface.url)) {
        await page.goto(DEFAULT_EDITOR_URL, { waitUntil: "domcontentloaded", timeout: 15000 }).catch(() => null);
        await page.waitForTimeout(1500);
      }
      const authorSurface = await openWriteSurface(page, Math.min(15000, Math.max(3000, deadline - Date.now())));
      if (authorSurface.authenticated && (authorSurface.surface === "editor" || AUTHOR_ROUTE_PATTERN.test(authorSurface.url))) {
        await writeStorageState(context, stateFile);
        const evidence = await capturePageEvidence(page, args, "bootstrap-session", {
          surface: authorSurface.surface,
          authenticated: authorSurface.authenticated,
        });
        return {
          status: "ok",
          mode: "bootstrap-session",
          live_ready: true,
          session_valid: true,
          final_url: page.url(),
          surface: authorSurface.surface,
          evidence,
          reason: "editor_surface_reached_after_manual_login",
          sms_login_attempt: smsLoginAttempt,
        };
      }
      lastSurface = authorSurface;
    }
    await page.waitForTimeout(1000);
  }

  const evidence = await capturePageEvidence(page, args, "bootstrap-session-timeout", {
    surface: lastSurface.surface,
    authenticated: lastSurface.authenticated,
  });
  return {
    status: "blocked",
    mode: "bootstrap-session",
    live_ready: false,
    session_valid: false,
    final_url: page.url(),
    surface: lastSurface.surface,
    manual_clearance_required: lastSurface.manualClearanceRequired,
    final_blocker: lastSurface.surface === "signin"
      ? (loginMode === "sms" ? "sms_login_not_completed" : "bootstrap_session_timed_out_on_login_surface")
      : (lastSurface.manualClearanceRequired ? "manual_clearance_required" : "author_surface_not_reached_after_auth"),
    evidence,
    reason: lastSurface.surface === "signin"
      ? (loginMode === "sms" ? "sms_login_not_completed" : "bootstrap_session_timed_out_on_login_surface")
      : (lastSurface.manualClearanceRequired ? "manual_clearance_required" : "author_surface_not_reached_after_auth"),
    sms_login_attempt: smsLoginAttempt,
  };
}

async function checkSession(runtime, args, stateFile, timeoutMs) {
  const { context, page } = runtime;
  const cookieInjection = await injectSessionCookies(context);
  await checkpointProgress(args, "check_session_open_write", {
    requested_url: DEFAULT_EDITOR_URL,
  });
  await page.goto(DEFAULT_EDITOR_URL, { waitUntil: "domcontentloaded", timeout: Math.min(timeoutMs, 30000) }).catch(() => null);
  const surface = await openWriteSurface(page, timeoutMs);
  const sessionValid = surface.authenticated && (surface.surface === "editor" || AUTHOR_ROUTE_PATTERN.test(surface.url));
  if (sessionValid) {
    await writeStorageState(context, stateFile).catch(() => null);
  }
  const evidence = await capturePageEvidence(page, args, "check-session", {
    surface: surface.surface,
    authenticated: surface.authenticated,
    cookie_injection: cookieInjection,
  });
  return {
    status: sessionValid ? "ok" : "blocked",
    mode: "check-session",
    live_ready: sessionValid,
    session_valid: sessionValid,
    final_url: page.url(),
    surface: surface.surface,
    cookie_injection: cookieInjection,
    manual_clearance_required: surface.manualClearanceRequired,
    evidence,
    reason: sessionValid
      ? "editor_surface_reached"
      : (surface.manualClearanceRequired ? "manual_clearance_required" : "session_invalid_or_missing"),
    final_blocker: sessionValid
      ? ""
      : (surface.manualClearanceRequired ? "manual_clearance_required" : "session_invalid_or_missing"),
  };
}

async function fillTitle(page, title) {
  const selector = await findVisibleSelector(page, TITLE_SELECTORS);
  if (!selector) {
    return { applied: false, selector: "", reason: "title_input_not_found" };
  }
  const locator = await resolveLocator(page, selector);
  const applied = await setLocatorValue(locator, page, title);
  return {
    applied,
    selector,
    reason: applied ? "" : "title_fill_failed",
  };
}

function expectedMarkdownCompletionMarkers(markdown) {
  const text = trimText(markdown);
  if (!text) {
    return [];
  }
  const markers = [];
  if (text.includes("## 延伸入口")) {
    markers.push("延伸入口");
  }
  if (text.includes("## 参考文献")) {
    markers.push("参考文献");
  }
  const headingMatches = Array.from(text.matchAll(/^##\s+(.+)$/gm))
    .map((match) => trimText(match[1]))
    .filter(Boolean);
  for (const heading of headingMatches.slice(-3)) {
    if (!markers.includes(heading)) {
      markers.push(heading);
    }
  }
  return uniqueStrings(markers);
}

async function readEditorSurfaceText(page) {
  const selector = await pickBestBodySelector(page);
  if (selector) {
    const locator = await resolveLocator(page, selector);
    const text = await locator.innerText().catch(() => "");
    if (trimText(text)) {
      return trimText(text);
    }
  }
  return trimText(await page.locator("body").innerText().catch(() => ""));
}

async function markdownImportLooksComplete(page, markdown) {
  const markers = expectedMarkdownCompletionMarkers(markdown);
  if (!markers.length) {
    return true;
  }
  const bodyText = await readEditorSurfaceText(page);
  if (!bodyText) {
    return false;
  }
  return markers.every((marker) => bodyText.includes(marker));
}

async function fillBody(page, text, markdown = "") {
  const markdownMode = await tryFillBodyViaMarkdownMode(page, markdown);
  if (markdownMode.applied) {
    await page.waitForTimeout(1200);
    const complete = await markdownImportLooksComplete(page, markdown);
    if (complete) {
      return {
        ...markdownMode,
        import_verified: true,
      };
    }
  }
  const selector = await pickBestBodySelector(page);
  if (!selector) {
    return {
      applied: false,
      selector: markdownMode.selector || "",
      method: markdownMode.method || "",
      reason: markdownMode.reason || "editor_input_not_found",
      markdown_mode_verified: false,
    };
  }
  const locator = await resolveLocator(page, selector);
  const applied = await fillRichBodyLocator(locator, page, markdown, text);
  return {
    applied,
    selector,
    method: "rich_editor_html",
    reason: applied ? "" : (markdownMode.reason || "editor_fill_failed"),
    markdown_mode_verified: false,
  };
}

async function ensurePublishPanel(page) {
  await dismissBlockingPrompts(page);
  const dialogSelector = await findVisibleSelector(page, PUBLISH_DIALOG_SELECTORS);
  if (dialogSelector) {
    return {
      opened: true,
      triggerSelector: "",
      panelSelector: dialogSelector,
    };
  }
  const triggerSelector = await clickFirstVisible(page, PUBLISH_BUTTON_SELECTORS, { timeoutMs: 5000 });
  if (!triggerSelector) {
    return {
      opened: false,
      triggerSelector: "",
      panelSelector: "",
      reason: "publish_button_missing",
    };
  }
  await dismissBlockingPrompts(page);
  const dialogMatch = await waitForFirstVisibleLocator(page, PUBLISH_DIALOG_SELECTORS, 5000);
  if (!dialogMatch) {
    return {
      opened: false,
      triggerSelector,
      panelSelector: "",
      reason: "publish_panel_not_opened",
    };
  }
  return {
    opened: true,
    triggerSelector,
    panelSelector: dialogMatch.selector,
  };
}

async function applyTags(page, rawTags) {
  const tags = uniqueStrings(Array.isArray(rawTags) ? rawTags : []);
  if (!tags.length) {
    return {
      appliedCount: 0,
      selector: "",
      tags,
      reason: "tags_missing",
    };
  }
  let selector = await findVisibleSelector(page, TAG_INPUT_SELECTORS);
  if (!selector) {
    return {
      appliedCount: 0,
      selector: "",
      tags,
      reason: "tag_input_not_found",
    };
  }
  const locator = await resolveLocator(page, selector);
  const applied = await collectDialogTagTexts(page);
  for (const tag of tags) {
    if (applied.some((item) => normalizeText(item) === normalizeText(tag))) {
      continue;
    }
    try {
      await locator.click({ timeout: 1500 }).catch(() => null);
      await setLocatorValue(locator, page, tag);
      await page.waitForTimeout(500);
      const option = await clickVisibleOptionByText(page, [
        ".Select_select-option_1LHGz",
        "[role='option']",
        ".el-select-dropdown__item",
        ".ant-select-item-option",
      ], tag, { timeoutMs: 1200 });
      if (!option) {
        await page.keyboard.press("Enter").catch(() => null);
      }
      await page.waitForTimeout(500);
      const currentTags = await collectDialogTagTexts(page);
      const addedTag = currentTags.find((item) => normalizeText(item) === normalizeText(tag));
      if (addedTag && !applied.some((item) => normalizeText(item) === normalizeText(addedTag))) {
        applied.push(addedTag);
      }
    } catch {
      continue;
    }
  }
  return {
    appliedCount: applied.length,
    selector,
    tags: applied,
    reason: applied.length ? "" : "tag_apply_failed",
  };
}

async function chooseSimpleDropdownOption(page, openSelectors, desiredText) {
  const hints = uniqueStrings([desiredText]).map((item) => normalizeText(item)).filter(Boolean);
  if (!hints.length) {
    return {
      applied: false,
      openSelector: "",
      selector: "",
      matchedText: "",
      reason: "dropdown_value_missing",
    };
  }
  const opener = await clickFirstVisible(page, openSelectors, { timeoutMs: 3000 });
  if (!opener) {
    return {
      applied: false,
      openSelector: "",
      selector: "",
      matchedText: "",
      reason: "dropdown_input_missing",
    };
  }
  await page.waitForTimeout(800);
  const selected = await clickFirstMatchingText(
    page,
    [
      "[role='option']",
      ".el-select-dropdown__item",
      ".ant-select-item-option",
      "li",
      "label",
      "span",
    ],
    hints,
  );
  return {
    applied: Boolean(selected),
    openSelector: opener,
    selector: selected?.selector || "",
    matchedText: selected?.matchedText || "",
    reason: selected ? "" : "dropdown_option_not_found",
  };
}

function resolveInfoQCopyrightOption(payload) {
  const combined = normalizeText([
    payload?.copyright_notice,
    payload?.copyright,
    payload?.statement,
    payload?.content_type,
  ].filter(Boolean).join(" "));
  if (combined.includes("禁止") || combined.includes("谢绝")) {
    return "禁止转载";
  }
  if (combined.includes("授权")) {
    return "联系作者授权转载";
  }
  return "无需联系作者授权转载";
}

async function applyCopyright(page, payload) {
  const desiredNotice = resolveInfoQCopyrightOption(payload);
  const currentSelector = await findVisibleSelector(page, COPYRIGHT_SELECT_SELECTORS);
  const currentLabel = trimText(
    await page.locator(".dialog-setting .copyright-select, .dialog-setting .copyright").first().innerText().catch(() => ""),
  );
  if (currentSelector && normalizeText(currentLabel).includes(normalizeText(desiredNotice))) {
    return {
      applied: true,
      notice: desiredNotice,
      openSelector: currentSelector,
      selector: currentSelector,
      matchedText: currentLabel,
      declaration: trimText(await page.locator(".dialog-setting .copy").first().innerText().catch(() => "")),
      reason: "",
    };
  }
  const openSelector = await clickFirstVisible(page, COPYRIGHT_SELECT_SELECTORS, { timeoutMs: 3000 });
  if (!openSelector) {
    return {
      applied: false,
      notice: desiredNotice,
      openSelector: "",
      selector: "",
      matchedText: "",
      declaration: "",
      reason: "copyright_control_not_found",
    };
  }
  await page.waitForTimeout(500);
  const selected = await clickVisibleOptionByText(page, COPYRIGHT_OPTION_SELECTORS, desiredNotice, { timeoutMs: 3000 });
  await page.waitForTimeout(500);
  const selectedLabel = trimText(
    await page.locator(".dialog-setting .copyright-select, .dialog-setting .copyright").first().innerText().catch(() => ""),
  );
  const declaration = trimText(await page.locator(".dialog-setting .copy").first().innerText().catch(() => ""));
  const applied = Boolean(
    selected
    && normalizeText(selectedLabel).includes(normalizeText(desiredNotice))
  );
  return {
    applied,
    notice: desiredNotice,
    openSelector,
    selector: selected?.selector || openSelector,
    matchedText: selectedLabel || selected?.matchedText || "",
    declaration,
    reason: applied ? "" : "copyright_control_not_found",
  };
}

async function clickFinalPublish(page) {
  const selector = await clickFirstVisible(page, FINAL_PUBLISH_SELECTORS, { timeoutMs: 5000 });
  return {
    clicked: Boolean(selector),
    selector,
    reason: selector ? "" : "final_publish_button_missing",
  };
}

async function resolvePublishedUrl(runtime, page, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let successSeen = false;
  while (Date.now() < deadline) {
    const currentUrl = trimText(page.url());
    if (PUBLIC_URL_PATTERN.test(currentUrl)) {
      return {
        url: currentUrl,
        source: "page_url",
        validationMessage: "",
      };
    }
    for (const candidatePage of runtime.context.pages()) {
      if (candidatePage.isClosed()) {
        continue;
      }
      const candidateUrl = trimText(candidatePage.url());
      if (PUBLIC_URL_PATTERN.test(candidateUrl)) {
        return {
          url: candidateUrl,
          source: "context_page_url",
          validationMessage: "",
        };
      }
      const anchorHref = trimText(
        await candidatePage.locator("a[href*='xie.infoq.cn/article/']").first().getAttribute("href").catch(() => ""),
      );
      if (PUBLIC_URL_PATTERN.test(anchorHref)) {
        return {
          url: anchorHref,
          source: "context_anchor",
          validationMessage: "",
        };
      }
    }
    const surface = await detectSurface(page);
    if (surface.manualClearanceRequired) {
      return {
        url: "",
        source: "",
        validationMessage: "manual_clearance_required_after_publish_click",
      };
    }
    if (surface.surface === "signin") {
      return {
        url: "",
        source: "",
        validationMessage: "session_invalid_or_missing_after_publish_click",
      };
    }
    const anchorHref = trimText(
      await page.locator("a[href*='xie.infoq.cn/article/']").first().getAttribute("href").catch(() => ""),
    );
    if (PUBLIC_URL_PATTERN.test(anchorHref)) {
      return {
        url: anchorHref,
        source: "page_anchor",
        validationMessage: "",
      };
    }
    const bodyText = await safeInnerText(page);
    if (textIncludesAny(bodyText, PUBLISH_SUCCESS_MARKERS)) {
      successSeen = true;
    }
    await page.waitForTimeout(800);
  }
  return {
    url: "",
    source: "",
    validationMessage: successSeen ? "publish_success_seen_but_public_url_not_resolved" : "public_url_not_resolved",
  };
}

async function prepareArticle(runtime, args, stateFile, timeoutMs, payload, submit) {
  const { context, page } = runtime;
  const cookieInjection = await injectSessionCookies(context);
  await checkpointProgress(args, "prepare_open_write", {
    requested_url: DEFAULT_EDITOR_URL,
    submit_requested: submit,
  });
  await page.goto(DEFAULT_EDITOR_URL, { waitUntil: "domcontentloaded", timeout: Math.min(timeoutMs, 30000) }).catch(() => null);
  let surface = await openWriteSurface(page, timeoutMs);
  if (isBlankWriteSurface(surface)) {
    await checkpointProgress(args, "prepare_fallback_create_draft", {
      current_url: surface.url,
      reason: "blank_write_surface",
    });
    const created = await createDraftFromHome(page, Math.min(timeoutMs, 20000));
    surface = created.surface;
  }
  if (surface.authenticated && !AUTHOR_ROUTE_PATTERN.test(surface.url)) {
    const latestSurface = await detectSurface(page);
    if (latestSurface.draftLimitReached) {
      await checkpointProgress(args, "prepare_fallback_draftbox_full", {
        current_url: latestSurface.url,
        reason: latestSurface.draftLimitMarker || "draft_limit_reached",
      });
      await openDraftbox(page);
      surface = await openWriteSurface(page, Math.min(timeoutMs, 30000));
    }
  }
  if (!surface.authenticated || surface.surface === "signin" || surface.surface === "risk" || surface.surface === "draftbox" || !AUTHOR_ROUTE_PATTERN.test(surface.url)) {
    const evidence = await capturePageEvidence(page, args, "prepare-article-blocked", {
      surface: surface.surface,
      authenticated: surface.authenticated,
      cookie_injection: cookieInjection,
    });
    return {
      status: "blocked",
      mode: submit ? "submit" : "prepare-article",
      live_ready: false,
      final_url: page.url(),
      surface: surface.surface,
      final_blocker: surface.manualClearanceRequired
        ? "manual_clearance_required"
        : (surface.surface === "draftbox" ? "draft_editor_not_opened" : (surface.authenticated ? "author_surface_not_reached_after_auth" : "session_invalid_or_missing")),
      cookie_injection: cookieInjection,
      evidence,
      reason: surface.manualClearanceRequired
        ? "manual_clearance_required"
        : (surface.surface === "draftbox" ? "draft_editor_not_opened" : (surface.authenticated ? "author_surface_not_reached_after_auth" : "session_invalid_or_missing")),
    };
  }

  const draft = payload?.draft || {};
  const titleResult = await fillTitle(page, trimText(draft.title));
  if (!titleResult.applied) {
    const evidence = await capturePageEvidence(page, args, "prepare-title-blocked", {
      surface: surface.surface,
      title_selector: titleResult.selector,
    });
    return {
      status: "blocked",
      mode: submit ? "submit" : "prepare-article",
      live_ready: false,
      final_url: page.url(),
      surface: surface.surface,
      final_blocker: titleResult.reason,
      cookie_injection: cookieInjection,
      evidence,
      reason: titleResult.reason,
    };
  }

  await checkpointProgress(args, "prepare_fill_body", {
    title_selector: titleResult.selector,
  });
  const bodyResult = await fillBody(page, trimText(draft.editor_body_text), trimText(draft.markdown));
  if (!bodyResult.applied) {
    const evidence = await capturePageEvidence(page, args, "prepare-body-blocked", {
      body_selector: bodyResult.selector,
    });
    return {
      status: "blocked",
      mode: submit ? "submit" : "prepare-article",
      live_ready: false,
      final_url: page.url(),
      surface: surface.surface,
      final_blocker: bodyResult.reason,
      cookie_injection: cookieInjection,
      evidence,
      reason: bodyResult.reason,
    };
  }

  await page.waitForTimeout(1200);
  const publishPanel = await ensurePublishPanel(page);
  if (!publishPanel.opened) {
    const evidence = await capturePageEvidence(page, args, "prepare-publish-panel-blocked", {
      trigger_selector: publishPanel.triggerSelector,
    });
    return {
      status: "blocked",
      mode: submit ? "submit" : "prepare-article",
      live_ready: false,
      final_url: page.url(),
      surface: surface.surface,
      final_blocker: publishPanel.reason || "publish_panel_not_opened",
      cookie_injection: cookieInjection,
      evidence,
      reason: publishPanel.reason || "publish_panel_not_opened",
    };
  }

  await checkpointProgress(args, "prepare_fill_metadata", {
    publish_trigger_selector: publishPanel.triggerSelector,
  });
  const summaryResult = await fillSummary(
    page,
    trimText(draft.summary || draft.editor_summary || draft.meta_summary || payload?.summary || ""),
  );
  const tagResult = await applyTags(page, Array.isArray(draft.tags) ? draft.tags : []);
  const copyrightResult = await applyCopyright(page, draft);
  const blockers = [];
  if (Number(draft.required_total_tags || 0) > 0 && tagResult.appliedCount < Number(draft.required_total_tags || 0)) {
    blockers.push("tag_apply_failed");
  }
  if (!copyrightResult.applied) {
    blockers.push(copyrightResult.reason || "copyright_control_not_found");
  }
  const publishBoundaryEvidence = await capturePageEvidence(
    page,
    args,
    submit ? "prepare-before-submit" : "prepare-ready",
    {
      publish_panel_selector: publishPanel.panelSelector,
      summary_selector: summaryResult.selector,
      title_selector: titleResult.selector,
      body_selector: bodyResult.selector,
      publish_trigger_selector: publishPanel.triggerSelector,
      topic_selector: tagResult.selector,
      topic_tags_applied: tagResult.appliedCount,
      copyright_selector: copyrightResult.selector,
      copyright_notice: copyrightResult.notice,
    },
  );

  if (!submit) {
    return {
      status: blockers.length ? "blocked" : "ok",
      mode: "prepare-article",
      live_ready: !blockers.length,
      final_url: page.url(),
      surface: surface.surface,
      title_selector: titleResult.selector,
      body_selector: bodyResult.selector,
      publish_trigger_selector: publishPanel.triggerSelector,
      draft_prepared: true,
      title_applied: true,
      body_applied: true,
      topic_tags_applied: tagResult.appliedCount,
      copyright_applied: copyrightResult.applied,
      publish_confirmed: false,
      blockers,
      final_blocker: blockers[0] || "",
      cookie_injection: cookieInjection,
      evidence: publishBoundaryEvidence,
      reason: blockers[0] || "draft_prepared_and_publish_boundary_ready",
    };
  }

  if (blockers.length) {
    return {
      status: "blocked",
      mode: "submit",
      live_ready: false,
      final_url: page.url(),
      surface: surface.surface,
      draft_prepared: true,
      title_applied: true,
      body_applied: true,
      topic_tags_applied: tagResult.appliedCount,
      copyright_applied: copyrightResult.applied,
      publish_confirmed: false,
      blockers,
      final_blocker: blockers[0],
      cookie_injection: cookieInjection,
      evidence: publishBoundaryEvidence,
      reason: blockers[0],
    };
  }

  await checkpointProgress(args, "prepare_click_final_publish", {});
  const finalPublish = await clickFinalPublish(page);
  if (!finalPublish.clicked) {
    const evidence = await capturePageEvidence(page, args, "prepare-final-publish-blocked", {
      final_publish_selector: finalPublish.selector,
    });
    return {
      status: "blocked",
      mode: "submit",
      live_ready: false,
      final_url: page.url(),
      surface: surface.surface,
      draft_prepared: true,
      title_applied: true,
      body_applied: true,
      topic_tags_applied: tagResult.appliedCount,
      copyright_applied: copyrightResult.applied,
      publish_confirmed: false,
      final_blocker: finalPublish.reason,
      cookie_injection: cookieInjection,
      evidence: evidence || publishBoundaryEvidence,
      reason: finalPublish.reason,
    };
  }

  await page.waitForTimeout(2500);
  const published = await resolvePublishedUrl(runtime, page, Math.min(timeoutMs, 20000));
  const postSubmitEvidence = await capturePageEvidence(page, args, "publish-result", {
    published_article_url: published.url,
    resolution_source: published.source,
    validation_message: published.validationMessage,
  });
  const publishConfirmed = Boolean(published.url);
  const finalBlocker = publishConfirmed ? "" : (published.validationMessage || "public_url_not_resolved");
  return {
    status: publishConfirmed ? "ok" : "blocked",
    mode: "submit",
    live_ready: publishConfirmed,
    final_url: published.url || page.url(),
    surface: publishConfirmed ? "published" : surface.surface,
    draft_prepared: true,
    title_applied: true,
    body_applied: true,
    topic_tags_applied: tagResult.appliedCount,
    copyright_applied: copyrightResult.applied,
    publish_requested: true,
    publish_confirmed: publishConfirmed,
    published_article_url: published.url,
    publish_resolution_source: published.source,
    final_blocker: finalBlocker,
    cookie_injection: cookieInjection,
    evidence: postSubmitEvidence || publishBoundaryEvidence,
    reason: publishConfirmed ? "publish_confirmed" : finalBlocker,
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const action = trimText(args.action || "check-session");
  const stateFile = trimText(args["state-file"]);
  const timeoutMs = Number.parseInt(args["timeout-ms"] || "45000", 10) || 45000;
  const headless = parseBool(args.headless, action === "check-session");
  const payloadFile = trimText(args["payload-file"]);
  const loginMode = trimText(args["login-mode"] || "password");
  const phoneNumber = resolvePhoneNumber(args);
  const smsCodeFile = resolveSmsCodeFile(args);
  let payload = {};
  if (payloadFile) {
    try {
      payload = JSON.parse(await fs.readFile(payloadFile, "utf8"));
    } catch {
      payload = {};
    }
  }

  const runtime = await launchInfoQContext({
    headless,
    stateFile,
    preferPersistent: true,
  });

  try {
    let result;
    if (action === "bootstrap-session") {
      result = await bootstrapSession(runtime, args, stateFile, timeoutMs);
    } else if (action === "check-session") {
      result = await checkSession(runtime, args, stateFile, timeoutMs);
    } else if (action === "prepare-article") {
      result = await prepareArticle(runtime, args, stateFile, timeoutMs, payload, parseBool(args.submit, false));
    } else {
      result = {
        status: "error",
        mode: action,
        reason: "unsupported_action",
      };
    }

    result = {
      ...result,
      login_mode: loginMode,
      phone_number_configured: Boolean(phoneNumber),
      sms_code_file: smsCodeFile,
      browser_profile_dir: browserProfileDir(),
      state_file: stateFile,
      evidence_dir: evidenceDirFromArgs(args),
      result_summary: {
        status: result.status,
        mode: result.mode || action,
        live_ready: Boolean(result.live_ready),
        session_valid: Boolean(result.session_valid || result.live_ready),
        published_article_url: trimText(result.published_article_url),
        final_blocker: trimText(result.final_blocker),
        reason: trimText(result.reason),
        topic_tags_applied: Number(result.topic_tags_applied || 0),
        copyright_applied: Boolean(result.copyright_applied),
      },
    };
    await checkpointResult(args, result);
    console.log(JSON.stringify(result, null, 2));
    if (result.status !== "ok") {
      process.exitCode = 1;
    }
  } finally {
    await closeRuntime(runtime);
  }
}

main().catch(async (error) => {
  const message = String(error?.stack || error?.message || error);
  console.error(message);
  process.exitCode = 1;
});
