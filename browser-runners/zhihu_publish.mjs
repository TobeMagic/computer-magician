import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { clearStaleChromiumSingletonLocks } from "./profile_lock.mjs";
import { decideZhihuImagePublish } from "./zhihu_image_policy.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const AIMAGICIAN_ROOT = path.resolve(__dirname, "..");
const DEFAULT_PROFILE_DIR = path.resolve(__dirname, "credentials/zhihu-browser-profile");
const DEFAULT_SMS_CODE_FILE = process.env.ZHIHU_SMS_CODE_FILE
  || path.resolve(__dirname, "credentials/zhihu-sms-code.txt");
const DEFAULT_EDITOR_URL = process.env.ZHIHU_WRITE_URL || "https://zhuanlan.zhihu.com/write";
const DEFAULT_CREATOR_URL = process.env.ZHIHU_CREATOR_URL || "https://www.zhihu.com/creator";
const DEFAULT_SIGNIN_URL = process.env.ZHIHU_SIGNIN_URL
  || "https://www.zhihu.com/signin?next=http%3A%2F%2Fzhuanlan.zhihu.com%2Fwrite";
const DEFAULT_LOCALE = process.env.ZHIHU_BROWSER_LOCALE || "zh-CN";
const DEFAULT_TIMEZONE = process.env.ZHIHU_BROWSER_TIMEZONE || "Asia/Shanghai";
const DEFAULT_USER_AGENT = process.env.ZHIHU_BROWSER_USER_AGENT
  || "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36";
const PUBLIC_URL_RE = /^https?:\/\/zhuanlan\.zhihu\.com\/p\/\d+(?:\/)?(?:[?#].*)?$/;
const PUBLIC_EDIT_URL_RE = /^https?:\/\/zhuanlan\.zhihu\.com\/p\/(\d+)\/edit(?:[/?#].*)?$/;
const LOGIN_MARKERS = [
  "登录",
  "注册",
  "手机号登录",
  "密码登录",
  "短信登录",
  "扫码登录",
  "立即登录",
];
const RISK_MARKERS = [
  "安全验证",
  "请完成验证",
  "滑块",
  "人机验证",
  "异常访问",
  "账号异常",
  "进入知乎",
  "开始验证",
  "网络环境存在异常",
];
const CREATOR_MARKERS = [
  "创作中心",
  "创作者中心",
  "内容管理",
  "数据概览",
];
const EDITOR_MARKERS = [
  "写文章",
  "发布文章",
  "文章标题",
  "正文",
  "封面",
  "摘要",
];
const PUBLISH_PANEL_MARKERS = [
  "摘要",
  "封面",
  "话题",
  "发布文章",
];
const SUCCESS_MARKERS = [
  "发布成功",
  "文章已发布",
  "发表成功",
  "审核中",
  "已发布",
];
const TITLE_SELECTORS = [
  "textarea[placeholder*='标题']",
  "input[placeholder*='标题']",
  "textarea[aria-label*='标题']",
  "input[aria-label*='标题']",
  "div[contenteditable='true'][data-placeholder*='标题']",
  "div[contenteditable='true'][placeholder*='标题']",
  "[role='textbox'][data-placeholder*='标题']",
];
const SUMMARY_SELECTORS = [
  "textarea[placeholder*='摘要']",
  "textarea[placeholder*='简介']",
  "textarea[aria-label*='摘要']",
  "textarea[aria-label*='简介']",
  "div[contenteditable='true'][data-placeholder*='摘要']",
  "div[contenteditable='true'][placeholder*='摘要']",
];
const BODY_SELECTORS = [
  "div[contenteditable='true'][data-placeholder*='正文']",
  "div[contenteditable='true'][data-placeholder*='写']",
  "div[contenteditable='true'][placeholder*='正文']",
  "div[contenteditable='true'][aria-label*='正文']",
  "div[contenteditable='true'][role='textbox']",
  "[role='textbox'][contenteditable='true']",
  "div[contenteditable='true']",
];
const TOPIC_INPUT_SELECTORS = [
  "input[placeholder*='话题']",
  "input[placeholder*='标签']",
  "input[aria-label*='话题']",
  "input[aria-label*='标签']",
];
const PUBLISH_TRIGGER_SELECTORS = [
  "button:text-is('发布文章')",
  "button:text-is('下一步')",
  "[role='button']:text-is('发布文章')",
  "[role='button']:text-is('下一步')",
];
const FINAL_PUBLISH_SELECTORS = [
  "button:text-is('确认发布')",
  "button:text-is('发布文章')",
  "button:text-is('立即发布')",
  "button:text-is('发布')",
  "[role='button']:text-is('确认发布')",
  "[role='button']:text-is('发布文章')",
  "[role='button']:text-is('立即发布')",
  "[role='button']:text-is('发布')",
];
const FINAL_PUBLISH_MODAL_SELECTORS = [
  "button:text-is('继续发布')",
  "button:text-is('确认发布')",
  "button:text-is('立即发布')",
  "[role='dialog'] button:text-is('继续发布')",
  "[role='dialog'] button:text-is('确认发布')",
  "[role='dialog'] button:text-is('立即发布')",
  "[role='dialog'] button:text-is('发布文章')",
  ".Modal button:text-is('继续发布')",
  ".Modal button:text-is('确认发布')",
  ".Modal button:text-is('立即发布')",
  ".Modal button:text-is('发布文章')",
  "div[class*='Publish'] button:text-is('继续发布')",
  "div[class*='Publish'] button:text-is('确认发布')",
  "div[class*='Publish'] button:text-is('立即发布')",
  "div[class*='Publish'] button:text-is('发布文章')",
];
const COVER_TRIGGER_SELECTORS = [
  "button:has-text('上传封面')",
  "button:has-text('添加封面')",
  "button:has-text('更换封面')",
  "[role='button']:has-text('上传封面')",
  "[role='button']:has-text('添加封面')",
  "[role='button']:has-text('更换封面')",
  "label:has-text('上传封面')",
  "label:has-text('添加封面')",
];
const COVER_CONFIRM_SELECTORS = [
  "button:has-text('确认上传')",
  "button:has-text('确认裁剪')",
  "button:has-text('完成裁剪')",
  "button:has-text('保存封面')",
  "button:has-text('完成')",
  "[role='button']:has-text('确认上传')",
  "[role='button']:has-text('确认裁剪')",
  "[role='button']:has-text('完成裁剪')",
  "[role='button']:has-text('保存封面')",
  "[role='button']:has-text('完成')",
];
const COVER_SUCCESS_SELECTORS = [
  "button:has-text('更换封面')",
  "button:has-text('删除封面')",
  "[role='button']:has-text('更换封面')",
  "[role='button']:has-text('删除封面')",
  "[class*='cover'] img[src]",
  "[class*='cover'] [style*='background-image']",
  "[data-testid*='cover'] img[src]",
  "[data-testid*='cover'] [style*='background-image']",
  "[aria-label*='封面'] img[src]",
];
const COVER_SUCCESS_MARKERS = [
  "更换封面",
  "删除封面",
  "封面预览",
  "裁剪完成",
];
const COVER_FAILURE_MARKERS = [
  "上传失败",
  "上传出错",
  "请重新上传",
  "图片过大",
  "格式不支持",
  "上传异常",
];
const IMAGE_TOOLBAR_SELECTORS = [
  "button[aria-label*='图片']",
  "[role='button'][aria-label*='图片']",
  "button:text-is('图片')",
  "[role='button']:text-is('图片')",
];
const IMAGE_UPLOAD_INPUT_SELECTORS = [
  "input[accept*='image/png']",
  "input[accept*='image/jpeg']",
  "input[accept*='image/webp']",
  "input[accept*='image']",
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

function isPublicArticleUrl(value) {
  const normalized = trimText(value);
  if (!normalized) {
    return false;
  }
  if (/\/edit(?:[/?#]|$)/.test(normalized)) {
    return false;
  }
  return PUBLIC_URL_RE.test(normalized);
}

function isPublishedArticleUnavailablePage(title, bodyText) {
  const merged = `${trimText(title)}\n${trimText(bodyText)}`;
  return /没有知识存在的荒原|页面不存在|内容不存在|已删除|404/.test(merged);
}

async function verifyPublishedArticleAccessible(page, url, timeoutMs = 15000) {
  const target = trimText(url);
  if (!isPublicArticleUrl(target)) {
    return false;
  }
  try {
    await page.goto(target, {
      waitUntil: "domcontentloaded",
      timeout: Math.max(5000, timeoutMs),
    });
    await page.waitForTimeout(2500);
    const title = trimText(await page.title().catch(() => ""));
    const bodyText = await safeInnerText(page);
    if (isPublishedArticleUnavailablePage(title, bodyText)) {
      return false;
    }
    if (page.url().includes("/signin") || textIncludesAny(bodyText, LOGIN_MARKERS)) {
      return false;
    }
    return isPublicArticleUrl(page.url()) || bodyText.length > 300;
  } catch {
    return false;
  }
}

function normalizePublicArticleUrlFromEdit(value) {
  const match = trimText(value).match(PUBLIC_EDIT_URL_RE);
  if (!match) {
    return "";
  }
  return `https://zhuanlan.zhihu.com/p/${match[1]}`;
}

function extractArticleUrlsFromText(text, preSubmitDraftId, allowEditFallback) {
  const normalized = trimText(text);
  if (!normalized) {
    return [];
  }
  const results = [];
  const seen = new Set();
  const preSubmit = trimText(preSubmitDraftId);
  const add = (url, source) => {
    const trimmed = trimText(url);
    if (!trimmed || seen.has(trimmed)) {
      return;
    }
    seen.add(trimmed);
    results.push({ url: trimmed, source });
  };

  const publicCandidates = normalized.match(/https?:\/\/zhuanlan\.zhihu\.com\/p\/\d+(?:[?#]|$)/g) || [];
  for (const candidate of publicCandidates) {
    const match = candidate.match(/^https?:\/\/zhuanlan\.zhihu\.com\/p\/(\d+)(?:[?#]|$)/);
    if (match) {
      add(`https://zhuanlan.zhihu.com/p/${match[1]}`, "text_public");
    }
  }

  if (!allowEditFallback) {
    return results;
  }

  const editCandidates = normalized.match(/https?:\/\/zhuanlan\.zhihu\.com\/p\/\d+\/edit(?:[/?#].*)?/g) || [];
  for (const candidate of editCandidates) {
    const normalizedEdit = normalizePublicArticleUrlFromEdit(candidate);
    if (normalizedEdit) {
      add(normalizedEdit, "edit_fallback");
    }
  }
  return results;
}

async function collectPublishedArticleUrlCandidates(page, preSubmitDraftId, allowEditFallback = false) {
  const candidates = [];
  const seen = new Set();
  const addCandidate = (candidate) => {
    const url = trimText(candidate?.url || "");
    if (!url || seen.has(url)) {
      return;
    }
    seen.add(url);
    candidates.push(candidate);
  };

  const collectFromPage = async (candidatePage) => {
    if (candidatePage.isClosed()) {
      return;
    }
    const candidateUrl = trimText(candidatePage.url());
    for (const item of extractArticleUrlsFromText(candidateUrl, preSubmitDraftId, allowEditFallback)) {
      addCandidate(item);
    }

    const linkHrefs = await candidatePage.locator("a[href*='zhuanlan.zhihu.com/p/']").evaluateAll((elements) =>
      elements.map((element) => element.getAttribute("href") || "").filter(Boolean)
    ).catch(() => []);
    for (const href of linkHrefs) {
      for (const item of extractArticleUrlsFromText(href, preSubmitDraftId, allowEditFallback)) {
        addCandidate(item);
      }
    }

    const shortHrefs = await candidatePage.locator("a[href^='/p/']").evaluateAll((elements) =>
      elements.map((element) => element.getAttribute("href") || "").filter(Boolean)
    ).catch(() => []);
    for (const href of shortHrefs) {
      for (const item of extractArticleUrlsFromText(`https://zhuanlan.zhihu.com${href}`, preSubmitDraftId, allowEditFallback)) {
        addCandidate(item);
      }
    }

    const pageText = await safeInnerText(candidatePage);
    for (const item of extractArticleUrlsFromText(pageText, preSubmitDraftId, allowEditFallback)) {
      addCandidate(item);
    }
  };

  const pages = page.context().pages();
  for (const candidatePage of pages) {
    await collectFromPage(candidatePage);
  }

  for (const item of extractArticleUrlsFromText(trimText(page.url()), preSubmitDraftId, allowEditFallback)) {
    addCandidate(item);
  }

  return candidates;
}

async function writeJson(jsonPath, value) {
  await fs.mkdir(path.dirname(jsonPath), { recursive: true });
  await fs.writeFile(jsonPath, JSON.stringify(value, null, 2), "utf8");
}

async function checkpointResult(args, value) {
  const outputFile = args["output-file"];
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

async function loadJsonFile(jsonPath) {
  if (!jsonPath) {
    return null;
  }
  const raw = await fs.readFile(jsonPath, "utf8");
  return JSON.parse(raw);
}

async function readOptionalTrimmedFile(targetPath) {
  if (!targetPath) {
    return "";
  }
  try {
    return trimText(await fs.readFile(targetPath, "utf8"));
  } catch {
    return "";
  }
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

async function directoryHasEntries(targetPath) {
  if (!targetPath) {
    return false;
  }
  try {
    const entries = await fs.readdir(targetPath);
    return entries.length > 0;
  } catch {
    return false;
  }
}

async function writeStorageState(context, stateFile) {
  if (!stateFile) {
    return false;
  }
  await fs.mkdir(path.dirname(stateFile), { recursive: true });
  await context.storageState({ path: stateFile });
  return true;
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
  const raw = trimText(process.env.ZHIHU_BROWSER_PROFILE_DIR);
  if (!raw) {
    return DEFAULT_PROFILE_DIR;
  }
  return path.isAbsolute(raw) ? raw : path.resolve(AIMAGICIAN_ROOT, raw);
}

function parseSessionCookies(rawCookieString) {
  const raw = trimText(rawCookieString);
  if (!raw || !raw.includes("=")) {
    return [];
  }
  const cookies = [];
  const seen = new Set();
  for (const part of raw.split(";")) {
    const item = part.trim();
    const index = item.indexOf("=");
    if (index <= 0) {
      continue;
    }
    const name = item.slice(0, index).trim();
    const value = item.slice(index + 1).trim();
    const lowered = name.toLowerCase();
    if (!name || !value || seen.has(lowered)) {
      continue;
    }
    seen.add(lowered);
    cookies.push({
      name,
      value,
      domain: ".zhihu.com",
      path: "/",
      httpOnly: false,
      secure: true,
      sameSite: "Lax",
    });
  }
  return cookies;
}

async function cookiesFromStateFile(stateFile) {
  const target = trimText(stateFile) || trimText(process.env.ZHIHU_SESSION_STATE_FILE);
  if (!target) {
    return [];
  }
  const resolved = path.isAbsolute(target) ? target : path.resolve(__dirname, target);
  try {
    const parsed = JSON.parse(await fs.readFile(resolved, "utf8"));
    return Array.isArray(parsed?.cookies) ? parsed.cookies : [];
  } catch {
    return [];
  }
}

async function injectSessionCookies(context, stateFile = "") {
  const merged = [
    process.env.ZHIHU_SESSION || "",
    process.env.ZHIHU_COOKIE || "",
  ]
    .filter(Boolean)
    .join("; ");
  const cookies = [];
  const seen = new Set();
  for (const cookie of [...await cookiesFromStateFile(stateFile), ...parseSessionCookies(merged)]) {
    const name = trimText(cookie?.name);
    if (!name || seen.has(name.toLowerCase())) {
      continue;
    }
    seen.add(name.toLowerCase());
    cookies.push({
      name,
      value: String(cookie.value || ""),
      domain: cookie.domain || ".zhihu.com",
      path: cookie.path || "/",
      httpOnly: Boolean(cookie.httpOnly),
      secure: cookie.secure !== false,
      sameSite: cookie.sameSite || "Lax",
    });
  }
  if (!cookies.length) {
    return { applied: false, names: [] };
  }
  await context.addCookies(cookies);
  return {
    applied: true,
    names: cookies.map((item) => item.name),
  };
}

async function launchContext(options) {
  const {
    headless,
    stateFile,
    preferPersistent = false,
    allowFreshPersistentProfile = false,
  } = options;
  const profileDir = browserProfileDir();
  const persistentRequested = preferPersistent && parseBool(process.env.ZHIHU_PERSISTENT_BROWSER, true);
  const profileReady = await directoryHasEntries(profileDir);
  const stateFileReady = stateFile ? await pathExists(stateFile) : false;
  const persistent = persistentRequested && (profileReady || allowFreshPersistentProfile || !stateFileReady);
  const launchOptions = {
    headless,
    locale: DEFAULT_LOCALE,
    timezoneId: DEFAULT_TIMEZONE,
    userAgent: DEFAULT_USER_AGENT,
    viewport: null,
    permissions: ["clipboard-read", "clipboard-write"],
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

  let persistentLaunchError = "";
  if (persistent) {
    try {
      await clearStaleChromiumSingletonLocks(profileDir);
      const context = await chromium.launchPersistentContext(profileDir, launchOptions);
      await applyStealthInitScript(context);
      const page = context.pages()[0] || await context.newPage();
      return {
        browser: null,
        context,
        page,
        persistent,
        profileDir,
        persistentFallbackReason: "",
      };
    } catch (error) {
      persistentLaunchError = trimText(error?.message || error);
    }
  }

  const browser = await chromium.launch(launchOptions);
  const contextOptions = {
    locale: DEFAULT_LOCALE,
    timezoneId: DEFAULT_TIMEZONE,
    userAgent: DEFAULT_USER_AGENT,
    viewport: null,
    permissions: ["clipboard-read", "clipboard-write"],
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
  return {
    browser,
    context,
    page,
    persistent: false,
    profileDir,
    persistentFallbackReason: persistentLaunchError,
  };
}

async function withTimeout(promise, timeoutMs) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((resolve) => {
        timer = setTimeout(() => resolve(null), timeoutMs);
      }),
    ]);
  } finally {
    if (timer) {
      clearTimeout(timer);
    }
  }
}

async function closeRuntime(runtime) {
  const { browser, context } = runtime;
  const pages = context.pages();
  for (const page of pages) {
    await withTimeout(page.close({ runBeforeUnload: false }).catch(() => null), 3000);
  }
  await withTimeout(context.close().catch(() => null), 5000);
  if (browser) {
    await withTimeout(browser.close().catch(() => null), 5000);
  }
}

async function safeInnerText(page) {
  try {
    const body = page.locator("body");
    return trimText(await body.innerText({ timeout: 3000 }));
  } catch {
    return "";
  }
}

async function capturePageEvidence(page, args, label, extra = {}) {
  const evidenceDir = args["evidence-dir"];
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const screenshotPath = evidenceDir ? path.resolve(evidenceDir, `${timestamp}-${label}.png`) : "";
  const metadataPath = evidenceDir ? path.resolve(evidenceDir, `${timestamp}-${label}.json`) : "";
  const pageTitle = trimText(await page.title().catch(() => ""));
  const payload = {
    label,
    url: page.url(),
    title: pageTitle,
    timestamp: new Date().toISOString(),
    ...extra,
  };
  if (evidenceDir) {
    await fs.mkdir(evidenceDir, { recursive: true });
    await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => null);
    await writeJson(metadataPath, payload);
  }
  return {
    dir: evidenceDir || "",
    snapshots: [
      {
        label,
        screenshot_path: screenshotPath,
        metadata_path: metadataPath,
      },
    ],
  };
}

function combineEvidence(...items) {
  const snapshots = [];
  let dir = "";
  for (const item of items) {
    if (!item || typeof item !== "object") {
      continue;
    }
    if (!dir && item.dir) {
      dir = item.dir;
    }
    if (Array.isArray(item.snapshots)) {
      snapshots.push(...item.snapshots);
    }
  }
  return {
    dir,
    snapshots,
  };
}

async function isVisibleLocator(locator) {
  try {
    if (!await locator.count()) {
      return false;
    }
    return await locator.isVisible();
  } catch {
    return false;
  }
}

async function findVisibleSelector(page, selectors, options = {}) {
  const pickLast = Boolean(options.pickLast);
  for (const selector of selectors) {
    const locator = pickLast ? page.locator(selector).last() : page.locator(selector).first();
    if (await isVisibleLocator(locator)) {
      return selector;
    }
  }
  return "";
}

async function scrollPublishPanelIntoView(page) {
  await page.evaluate(() => {
    window.scrollTo(0, document.body.scrollHeight);
  }).catch(() => null);
  await page.waitForTimeout(700);
  for (const selector of FINAL_PUBLISH_SELECTORS) {
    const locator = page.locator(selector).last();
    if (!await locator.count().catch(() => 0)) {
      continue;
    }
    await locator.scrollIntoViewIfNeeded().catch(() => null);
    if (await isVisibleLocator(locator)) {
      break;
    }
  }
  await page.waitForTimeout(400);
}

async function findVisibleTextSelector(page, texts, element = "button") {
  for (const text of texts) {
    const selector = `${element}:has-text('${text}')`;
    const locator = page.locator(selector).first();
    if (await isVisibleLocator(locator)) {
      return selector;
    }
  }
  return "";
}

async function isEnabledLocator(locator) {
  try {
    return await locator.isEnabled();
  } catch {
    return false;
  }
}

async function clickFirstVisible(page, selectors, options = {}) {
  const timeoutMs = options.timeoutMs || 5000;
  const requireEnabled = Boolean(options.requireEnabled);
  for (const selector of selectors) {
    const locator = page.locator(selector).first();
    if (!await isVisibleLocator(locator)) {
      continue;
    }
    if (requireEnabled && !await isEnabledLocator(locator)) {
      continue;
    }
    try {
      await locator.scrollIntoViewIfNeeded().catch(() => null);
      await locator.click({ timeout: timeoutMs });
      return selector;
    }
    catch {}
    if (!requireEnabled) {
      try {
        await locator.click({ timeout: timeoutMs, force: true });
        return selector;
      } catch {}
      try {
        await locator.evaluate((node) => node.click());
        return selector;
      } catch {}
    }
  }
  return "";
}

async function waitForEnabledPublishButton(page, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const selector of FINAL_PUBLISH_SELECTORS) {
      const locator = page.locator(selector).last();
      if (await isVisibleLocator(locator) && await isEnabledLocator(locator)) {
        return {
          ready: true,
          selector,
        };
      }
    }
    await page.waitForTimeout(500);
  }
  return {
    ready: false,
    selector: "",
  };
}

async function fillFirstVisibleInput(page, selectors, value) {
  const normalized = trimText(value);
  if (!normalized) {
    return "";
  }
  for (const selector of selectors) {
    const locator = page.locator(selector).first();
    if (!await isVisibleLocator(locator)) {
      continue;
    }
    try {
      await locator.click({ timeout: 3000 });
      await locator.fill("", { timeout: 3000 }).catch(() => null);
      await locator.fill(normalized, { timeout: 5000 });
      return selector;
    } catch {
      continue;
    }
  }
  return "";
}

async function submitCredentialForm(page, passwordSelector) {
  let submitSelector = "";
  if (passwordSelector) {
    const passwordLocator = page.locator(passwordSelector).first();
    try {
      if (await isVisibleLocator(passwordLocator)) {
        await passwordLocator.focus().catch(() => null);
        await page.keyboard.press("Enter").catch(() => null);
        await page.waitForTimeout(1200);
      }
    } catch {}
  }

  const submitSelectors = [
    "button:has-text('登录')",
    "button[type='submit']",
    "[role='button']:has-text('登录')",
    "div[role='button']:has-text('登录')",
    "span:has-text('登录')",
  ];
  for (const selector of submitSelectors) {
    const locator = page.locator(selector).first();
    if (!await isVisibleLocator(locator)) {
      continue;
    }
    submitSelector = selector;
    try {
      await locator.scrollIntoViewIfNeeded().catch(() => null);
      await locator.click({ timeout: 3000 });
      await page.waitForTimeout(1200);
      return submitSelector;
    } catch {}
    try {
      await locator.click({ timeout: 3000, force: true });
      await page.waitForTimeout(1200);
      return submitSelector;
    } catch {}
    try {
      await locator.evaluate((node) => {
        if (node instanceof HTMLElement) {
          node.click();
        }
      });
      await page.waitForTimeout(1200);
      return submitSelector;
    } catch {}
  }

  try {
    const submitted = await page.evaluate(() => {
      const active = document.activeElement;
      const form = active instanceof HTMLElement ? active.closest("form") : document.querySelector("form");
      if (!(form instanceof HTMLFormElement)) {
        return false;
      }
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit();
      } else {
        form.submit();
      }
      return true;
    });
    if (submitted) {
      await page.waitForTimeout(1200);
      return submitSelector || "form:submit";
    }
  } catch {}

  return submitSelector;
}

async function maybeAcceptAgreement(page) {
  const selectors = [
    "label:has-text('我已阅读')",
    "label:has-text('同意')",
    "[role='checkbox']:has-text('同意')",
    "[role='checkbox']:has-text('协议')",
    "input[type='checkbox']",
  ];
  for (const selector of selectors) {
    const locator = page.locator(selector).first();
    if (!await isVisibleLocator(locator)) {
      continue;
    }
    try {
      const isChecked = await locator.evaluate((node) => {
        if (node instanceof HTMLInputElement && node.type === "checkbox") {
          return node.checked;
        }
        return node.getAttribute("aria-checked") === "true";
      }).catch(() => false);
      if (!isChecked) {
        await locator.click({ timeout: 3000 }).catch(() => null);
        await page.waitForTimeout(300);
      }
      return selector;
    } catch {
      continue;
    }
  }
  return "";
}

async function attemptSmsLogin(page, args = {}) {
  const phone = trimText(
    args["phone-number"]
    || process.env.ZHIHU_PHONE
    || process.env.AIMAGICIAN_PLATFORM_LOGIN_PHONE
    || process.env.ZHIHU_USERNAME
    || process.env.ZHIHU_EMAIL
    || ""
  );
  const result = {
    sms_login_configured: Boolean(phone),
    sms_login_tab_selector: "",
    phone_selector: "",
    code_selector: "",
    get_code_selector: "",
    agreement_selector: "",
    reason: "",
  };
  if (!phone) {
    result.reason = "phone_number_missing";
    return result;
  }

  result.sms_login_tab_selector = await clickFirstVisible(page, [
    "button:has-text('验证码登录')",
    "button:has-text('短信登录')",
    "[role='tab']:has-text('验证码登录')",
    "[role='tab']:has-text('短信登录')",
    "div[role='button']:has-text('验证码登录')",
    "div[role='button']:has-text('短信登录')",
    "span:has-text('验证码登录')",
    "span:has-text('短信登录')",
  ], { timeoutMs: 2500 });
  if (result.sms_login_tab_selector) {
    await page.waitForTimeout(800);
  }

  result.phone_selector = await fillFirstVisibleInput(page, [
    "input[autocomplete='tel']",
    "input[type='tel']",
    "input[name='username']",
    "input[name='account']",
    "input[inputmode='numeric']",
    "input[placeholder*='手机号']",
    "input[placeholder*='手机号码']",
    "input[aria-label*='手机号']",
  ], phone);
  result.code_selector = await fillFirstVisibleInput(page, [
    "input[placeholder*='验证码']",
    "input[aria-label*='验证码']",
    "input[name*='code']",
    "input[inputmode='numeric']",
  ], "");
  result.agreement_selector = await maybeAcceptAgreement(page);
  result.get_code_selector = await clickFirstVisible(page, [
    "button:has-text('获取验证码')",
    "button:has-text('发送验证码')",
    "button:has-text('发送短信')",
    "[role='button']:has-text('获取验证码')",
    "[role='button']:has-text('发送验证码')",
    "span:has-text('获取验证码')",
    "span:has-text('发送验证码')",
  ], { timeoutMs: 3000 });
  if (result.get_code_selector) {
    await page.waitForTimeout(1200);
  } else {
    result.reason = "sms_send_code_control_not_found";
  }
  return result;
}

async function fillSmsCodeIfAvailable(page, smsCodeFile, state = {}) {
  if (!smsCodeFile || state.codeFilled) {
    return state;
  }
  const smsCode = await readOptionalTrimmedFile(smsCodeFile);
  if (!/^\d{4,8}$/.test(smsCode)) {
    return state;
  }
  const codeSelector = await fillFirstVisibleInput(page, [
    "input[placeholder*='验证码']",
    "input[aria-label*='验证码']",
    "input[name*='code']",
    "input[inputmode='numeric']",
    "input[type='number']",
    "input[type='text']",
  ], smsCode);
  const submitSelector = await submitCredentialForm(page, codeSelector);
  return {
    ...state,
    codeFilled: Boolean(codeSelector),
    codeSelector,
    submitSelector,
  };
}

async function attemptCredentialLogin(page) {
  const username = trimText(
    process.env.ZHIHU_USERNAME
    || process.env.ZHIHU_PHONE
    || process.env.AIMAGICIAN_PLATFORM_LOGIN_PHONE
    || process.env.ZHIHU_EMAIL
    || ""
  );
  const password = trimText(process.env.ZHIHU_PASSWORD || "");
  const passwordModeSelector = await clickFirstVisible(page, [
    "button:has-text('密码登录')",
    "[role='tab']:has-text('密码登录')",
    "div[role='button']:has-text('密码登录')",
    "span:has-text('密码登录')",
  ], { timeoutMs: 2500 });
  if (passwordModeSelector) {
    await page.waitForTimeout(800);
  }
  const usernameSelector = await fillFirstVisibleInput(page, [
    "input[autocomplete='username']",
    "input[name='username']",
    "input[name='account']",
    "input[type='tel']",
    "input[inputmode='numeric']",
    "input[placeholder*='手机号']",
    "input[placeholder*='邮箱']",
    "input[placeholder*='用户名']",
    "input[aria-label*='手机号']",
    "input[aria-label*='邮箱']",
  ], username);
  const passwordSelector = await fillFirstVisibleInput(page, [
    "input[type='password']",
    "input[autocomplete='current-password']",
    "input[name='password']",
    "input[placeholder*='密码']",
    "input[aria-label*='密码']",
  ], password);
  const agreementSelector = await maybeAcceptAgreement(page);
  const submitSelector = await submitCredentialForm(page, passwordSelector);
  return {
    credential_login_configured: Boolean(username && password),
    password_mode_selector: passwordModeSelector,
    username_selector: usernameSelector,
    password_selector: passwordSelector,
    agreement_selector: agreementSelector,
    submit_selector: submitSelector,
  };
}

async function pickBestBodySelector(page) {
  for (const selector of BODY_SELECTORS) {
    const locator = page.locator(selector).first();
    if (await isVisibleLocator(locator)) {
      return selector;
    }
  }
  const generic = page.locator("div[contenteditable='true'], [role='textbox'][contenteditable='true']");
  const count = await generic.count().catch(() => 0);
  let bestIndex = -1;
  let bestArea = 0;
  for (let index = 0; index < Math.min(count, 12); index += 1) {
    const locator = generic.nth(index);
    if (!await isVisibleLocator(locator)) {
      continue;
    }
    const box = await locator.boundingBox().catch(() => null);
    if (!box) {
      continue;
    }
    const area = box.width * box.height;
    if (box.height >= 120 && box.width >= 300 && area > bestArea) {
      bestArea = area;
      bestIndex = index;
    }
  }
  if (bestIndex >= 0) {
    return `__GENERIC_CONTENTEDITABLE__:${bestIndex}`;
  }
  return "";
}

function modifierSelectAll() {
  return process.platform === "darwin" ? "Meta+A" : "Control+A";
}

async function resolveLocator(page, selector) {
  if (!selector) {
    return null;
  }
  if (selector.startsWith("__GENERIC_CONTENTEDITABLE__:")) {
    const index = Number(selector.split(":")[1] || "0");
    return page.locator("div[contenteditable='true'], [role='textbox'][contenteditable='true']").nth(index);
  }
  return page.locator(selector).first();
}

async function fillEditableLocator(locator, page, value) {
  if (!locator || !trimText(value)) {
    return false;
  }
  try {
    const info = await locator.evaluate((node) => ({
      tagName: node.tagName.toLowerCase(),
      contentEditable: node.getAttribute("contenteditable"),
    })).catch(() => ({ tagName: "", contentEditable: "" }));
    if (info.tagName === "input" || info.tagName === "textarea") {
      await locator.click({ timeout: 5000 });
      await locator.fill(value, { timeout: 5000 });
      return true;
    }
    await locator.click({ timeout: 5000 });
    await page.keyboard.press(modifierSelectAll()).catch(() => null);
    await page.keyboard.press("Backspace").catch(() => null);
    await page.keyboard.insertText(value);
    return true;
  } catch {
    return false;
  }
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

function splitMarkdownTableRow(line) {
  const raw = String(line || "").trim();
  if (!raw.includes("|")) {
    return [];
  }
  const trimmed = raw.replace(/^\|/, "").replace(/\|$/, "");
  return trimmed.split("|").map((cell) => trimText(cell));
}

function isMarkdownTableDivider(line) {
  const cells = splitMarkdownTableRow(line);
  if (cells.length < 2) {
    return false;
  }
  return cells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s+/g, "")));
}

function isMarkdownTableRow(line) {
  const raw = trimText(line);
  return Boolean(raw) && raw.includes("|") && splitMarkdownTableRow(raw).length >= 2;
}

function parseMarkdownTable(lines, startIndex) {
  const headerLine = trimText(lines[startIndex] || "");
  const dividerLine = trimText(lines[startIndex + 1] || "");
  if (!isMarkdownTableRow(headerLine) || !isMarkdownTableDivider(dividerLine)) {
    return null;
  }
  const headers = splitMarkdownTableRow(headerLine);
  const rows = [];
  let index = startIndex + 2;
  while (index < lines.length && isMarkdownTableRow(trimText(lines[index])) && !isMarkdownTableDivider(trimText(lines[index]))) {
    const cells = splitMarkdownTableRow(trimText(lines[index]));
    const padded = headers.map((_, cellIndex) => trimText(cells[cellIndex] || ""));
    rows.push(padded);
    index += 1;
  }
  return {
    block: {
      type: "table",
      headers,
      rows,
    },
    nextIndex: index,
  };
}

function parseMarkdownBodyBlocks(markdown) {
  const text = trimText(markdown);
  if (!text) {
    return [];
  }
  const lines = text.split(/\r?\n/);
  const blocks = [];
  let paragraph = [];
  let listBlock = null;
  let quoteBlock = [];
  let codeBlock = null;

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

    const table = parseMarkdownTable(lines, lineIndex);
    if (table) {
      flushParagraph();
      flushList();
      flushQuote();
      blocks.push(table.block);
      lineIndex = table.nextIndex - 1;
      continue;
    }

    if (!line || line === "---") {
      flushParagraph();
      flushList();
      flushQuote();
      continue;
    }

    if (/^```/.test(line)) {
      flushParagraph();
      flushList();
      flushQuote();
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
        quoteBlock.push(quoteText);
      }
      continue;
    }

    const orderedMatch = line.match(/^\d+\.\s+(.+)$/);
    if (orderedMatch) {
      flushParagraph();
      flushQuote();
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
      if (!listBlock || listBlock.ordered !== false) {
        flushList();
        listBlock = { type: "list", ordered: false, items: [] };
      }
      listBlock.items.push(trimText(unorderedMatch[1]));
      continue;
    }

    flushList();
    flushQuote();
    paragraph.push(line);
  }
  flushParagraph();
  flushList();
  flushQuote();
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
      const cellStyle = "border:1px solid #e5e7eb;padding:10px 12px;vertical-align:top;line-height:1.7;";
      const headerCells = (Array.isArray(block.headers) ? block.headers : [])
        .map((cell) => `<th style="${cellStyle}background:#f6f8fa;font-weight:600;text-align:left;">${renderInlineMarkdownToHtml(cell)}</th>`)
        .join("");
      const bodyRows = (Array.isArray(block.rows) ? block.rows : [])
        .map((row) => `<tr>${(Array.isArray(row) ? row : []).map((cell) => `<td style="${cellStyle}">${renderInlineMarkdownToHtml(cell)}</td>`).join("")}</tr>`)
        .join("");
      return `<figure data-aimagician-block="table" style="margin:20px 0;overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:15px;line-height:1.7;">${headerCells ? `<thead><tr>${headerCells}</tr></thead>` : ""}<tbody>${bodyRows}</tbody></table></figure>`;
    }
    const lines = String(block.text || "")
      .split(/\n+/)
      .map((line) => trimText(line))
      .filter(Boolean)
      .map((line) => `<p>${renderInlineMarkdownToHtml(line)}</p>`);
    return lines.join("");
  }).join("");
}

async function downloadRemoteImageToTemp(sourceUrl) {
  const response = await fetch(sourceUrl);
  if (!response.ok) {
    throw new Error(`image_download_failed:${response.status}`);
  }
  const bytes = Buffer.from(await response.arrayBuffer());
  const url = new URL(sourceUrl);
  const ext = path.extname(url.pathname || "").trim() || ".png";
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "aimagician-zhihu-img-"));
  const filePath = path.join(tempDir, `image${ext}`);
  await fs.writeFile(filePath, bytes);
  return { filePath, temporary: true, tempDir };
}

async function resolveBodyImageUpload(block) {
  const sourcePath = trimText(block?.source_path || "");
  if (sourcePath && await pathExists(sourcePath)) {
    return { filePath: sourcePath, temporary: false, tempDir: "" };
  }
  const sourceUrl = trimText(block?.url || "");
  if (sourceUrl.startsWith("http://") || sourceUrl.startsWith("https://")) {
    return downloadRemoteImageToTemp(sourceUrl);
  }
  return { filePath: "", temporary: false, tempDir: "" };
}

async function appendRichHtmlChunk(locator, page, html) {
  if (!trimText(html)) {
    return true;
  }
  return locator.evaluate((node, chunk) => {
    node.focus();
    let inserted = false;
    if (document.execCommand) {
      try {
        inserted = document.execCommand("insertHTML", false, chunk);
      } catch {
        inserted = false;
      }
    }
    if (!inserted) {
      if ("insertAdjacentHTML" in node) {
        node.insertAdjacentHTML("beforeend", chunk);
      } else if ("innerHTML" in node) {
        node.innerHTML = `${String(node.innerHTML || "")}${chunk}`;
      } else {
        return false;
      }
    }
    node.dispatchEvent(new InputEvent("input", {
      bubbles: true,
      cancelable: true,
      inputType: "insertFromPaste",
    }));
    node.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }, html).catch(() => false);
}

function imageUploadAnchorText(block) {
  if (Number.isInteger(block?.uploadSlot)) {
    return `[[AIMG-${block.uploadSlot}]]`;
  }
  const caption = sanitizeImageCaption(block.caption, block.alt);
  if (caption) {
    return caption.slice(0, 48);
  }
  const alt = trimText(block.alt || "");
  if (!alt || alt === "封面图" || alt === "文末收口图") {
    return block.footerAnchor || "";
  }
  if (alt.startsWith("SVGDIAGRAM::")) {
    return trimText(alt.replace(/^SVGDIAGRAM::/, "")).slice(0, 48);
  }
  return alt.slice(0, 48);
}

async function focusEditorBeforeTextAnchor(locator, anchorText) {
  const anchor = trimText(anchorText);
  if (!anchor) {
    return false;
  }
  return locator.evaluate((node, needle) => {
    const normalizedNeedle = String(needle || "").replace(/\s+/g, " ").trim();
    if (!normalizedNeedle) {
      return false;
    }
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const text = (walker.currentNode.textContent || "").replace(/\s+/g, " ").trim();
      if (!text) {
        continue;
      }
      if (!text.includes(normalizedNeedle) && !normalizedNeedle.includes(text.slice(0, Math.min(24, text.length)))) {
        continue;
      }
      let block = walker.currentNode.parentElement;
      while (block && block !== node) {
        if (block.dataset?.block === "true" || block.classList?.contains("public-DraftStyleDefault-block")) {
          break;
        }
        block = block.parentElement;
      }
      const target = block || walker.currentNode.parentElement;
      target?.scrollIntoView({ block: "center" });
      const range = document.createRange();
      range.setStartBefore(target);
      range.collapse(true);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      node.focus();
      return true;
    }
    return false;
  }, anchor).catch(() => false);
}

async function countEditorZhihuImages(page) {
  const selector = await pickBestBodySelector(page);
  if (!selector) {
    return 0;
  }
  return page.locator(`${selector} img`).count().catch(() => 0);
}

async function waitForImageUploadComplete(page, minCount, timeoutMs = 45000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const count = await countEditorZhihuImages(page);
    if (count >= minCount) {
      await page.waitForTimeout(1800);
      return { ready: true, count };
    }
    await page.waitForTimeout(900);
  }
  return { ready: false, count: await countEditorZhihuImages(page) };
}

async function removeEditorTextMarker(locator, markerText) {
  const marker = trimText(markerText);
  if (!marker) {
    return false;
  }
  return locator.evaluate((node, needle) => {
    const normalizedNeedle = String(needle || "").trim();
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const current = walker.currentNode;
      const text = current.textContent || "";
      if (!text.includes(normalizedNeedle)) {
        continue;
      }
      current.textContent = text.replace(normalizedNeedle, "").replace(/^\s+|\s+$/g, "");
      let block = current.parentElement;
      while (block && block !== node) {
        if (block.dataset?.block === "true" || block.classList?.contains("public-DraftStyleDefault-block")) {
          break;
        }
        block = block.parentElement;
      }
      if (block && !(block.textContent || "").replace(/\s+/g, "").length) {
        block.remove();
      }
      node.dispatchEvent(new InputEvent("input", { bubbles: true }));
      return true;
    }
    return false;
  }, marker).catch(() => false);
}

async function uploadInlineImageViaToolbar(page, locator, block) {
  let upload = { filePath: "", temporary: false, tempDir: "" };
  try {
    upload = await resolveBodyImageUpload(block);
    if (!upload.filePath) {
      return { uploaded: false, reason: "body_image_missing", selector: "" };
    }
    const anchor = imageUploadAnchorText(block);
    let positioned = false;
    if (block.role === "footer") {
      const footerAnchor = imageUploadAnchorText(block);
      if (footerAnchor) {
        positioned = await focusEditorBeforeTextAnchor(locator, footerAnchor);
      }
      if (!positioned) {
        await locator.click({ timeout: 3000 }).catch(() => null);
        await page.keyboard.press("End").catch(() => null);
        positioned = true;
      }
    } else {
      positioned = await focusEditorBeforeTextAnchor(locator, anchor);
    }
    if (!positioned) {
      return { uploaded: false, reason: "image_anchor_not_found", selector: "" };
    }
    await page.waitForTimeout(250);
    const beforeCount = await countEditorZhihuImages(page);
    let uploadInput = null;
    for (const inputSelector of IMAGE_UPLOAD_INPUT_SELECTORS) {
      const candidate = page.locator(inputSelector).first();
      if (await candidate.count().catch(() => 0)) {
        uploadInput = candidate;
        break;
      }
    }
    if (!uploadInput) {
      const selector = await clickFirstVisible(page, IMAGE_TOOLBAR_SELECTORS, { timeoutMs: 4000 });
      if (!selector) {
        throw new Error("image_toolbar_missing");
      }
      await page.waitForTimeout(500);
      for (const inputSelector of IMAGE_UPLOAD_INPUT_SELECTORS) {
        const candidate = page.locator(inputSelector).first();
        if (await candidate.count().catch(() => 0)) {
          uploadInput = candidate;
          break;
        }
      }
    }
    if (!uploadInput) {
      throw new Error("image_upload_input_missing");
    }
    await uploadInput.setInputFiles(upload.filePath, { timeout: 12000 });
    const uploadWait = await waitForImageUploadComplete(page, beforeCount + 1);
    if (!uploadWait.ready) {
      return {
        uploaded: false,
        reason: "body_image_not_rendered",
        selector: "direct-file-input",
        imageCount: uploadWait.count,
      };
    }
    await page.keyboard.press("Escape").catch(() => null);
    await removeEditorTextMarker(locator, anchor);
    return { uploaded: true, reason: "", selector: "direct-file-input", imageCount: uploadWait.count };
  } catch (error) {
    return {
      uploaded: false,
      reason: trimText(error?.message || error) || "body_image_upload_failed",
      selector: "",
    };
  } finally {
    if (upload.temporary) {
      await fs.unlink(upload.filePath).catch(() => null);
      await fs.rmdir(upload.tempDir).catch(() => null);
    }
  }
}

async function readEditorBodyTextLength(page) {
  const selector = await pickBestBodySelector(page);
  if (!selector) {
    return 0;
  }
  const locator = page.locator(selector).first();
  if (!await isVisibleLocator(locator)) {
    return 0;
  }
  return trimText(await locator.innerText().catch(() => "")).length;
}

async function readEditorWordCount(page) {
  const footerText = (await safeInnerText(page)).slice(-4000);
  const match = footerText.match(/字数[：:]\s*([\d,]+)/);
  if (!match) {
    return 0;
  }
  return Number(String(match[1]).replace(/,/g, "")) || 0;
}

function expectedEditorBodyLength(markdown, fallbackText, payload = {}) {
  const normalized = trimText(markdown) || trimText(fallbackText);
  return Math.max(1200, Math.floor(normalized.length * 0.45));
}

function expectedEditorWordCount(markdown, fallbackText, payload = {}) {
  return expectedEditorBodyLength(markdown, fallbackText, payload);
}

async function waitForEditorDraftSynced(page, minBodyLength, timeoutMs = 45000) {
  const deadline = Date.now() + timeoutMs;
  let lastLength = 0;
  let stableReads = 0;
  while (Date.now() < deadline) {
    await page.locator(TITLE_SELECTORS.join(", ")).first().click({ timeout: 2000 }).catch(() => null);
    await page.waitForTimeout(800);
    const bodyLength = await readEditorBodyTextLength(page);
    if (bodyLength >= minBodyLength) {
      if (bodyLength === lastLength) {
        stableReads += 1;
        if (stableReads >= 2) {
          return { synced: true, bodyLength, wordCount: await readEditorWordCount(page) };
        }
      } else {
        stableReads = 0;
      }
    }
    lastLength = bodyLength;
    await page.waitForTimeout(1500);
  }
  return {
    synced: false,
    bodyLength: lastLength,
    wordCount: await readEditorWordCount(page),
  };
}

function markdownWithoutImageLines(markdown) {
  return String(markdown || "")
    .split("\n")
    .filter((line) => !/^!\[[^\]]*\]\(\s*https?:\/\//i.test(line.trim()))
    .join("\n");
}

async function pasteHtmlIntoEditable(page, locator, html, plainText) {
  const normalizedHtml = trimText(html);
  const normalizedPlain = trimText(plainText);
  if (!normalizedHtml && !normalizedPlain) {
    return false;
  }
  await locator.click({ timeout: 5000 });
  await page.keyboard.press(modifierSelectAll()).catch(() => null);
  await page.keyboard.press("Backspace").catch(() => null);
  await page.evaluate(async (payload) => {
    if (payload.html && typeof ClipboardItem !== "undefined") {
      const item = new ClipboardItem({
        "text/html": new Blob([payload.html], { type: "text/html" }),
        "text/plain": new Blob([payload.plain || payload.html], { type: "text/plain" }),
      });
      await navigator.clipboard.write([item]);
      return;
    }
    await navigator.clipboard.writeText(payload.plain || payload.html);
  }, { html: normalizedHtml, plain: normalizedPlain });
  await page.keyboard.press("Control+V");
  await page.locator(TITLE_SELECTORS.join(", ")).first().click({ timeout: 3000 }).catch(() => null);
  await page.waitForTimeout(2500);
  return (await readEditorBodyTextLength(page)) > 200;
}

async function verifyDraftBodyPersisted(page, minBodyLength) {
  const draftUrl = trimText(page.url());
  await page.waitForTimeout(12000);
  if (!draftUrl.includes("/p/")) {
    return false;
  }
  await page.goto(draftUrl, { waitUntil: "domcontentloaded", timeout: 60000 }).catch(() => null);
  await page.waitForTimeout(4000);
  return (await readEditorBodyTextLength(page)) >= minBodyLength;
}

async function verifyDraftImagesPersisted(page, minImageCount) {
  const draftUrl = trimText(page.url());
  if (!draftUrl.includes("/p/") || minImageCount <= 0) {
    return { persisted: true, count: 0 };
  }
  await page.locator(TITLE_SELECTORS.join(", ")).first().click({ timeout: 3000 }).catch(() => null);
  await page.waitForTimeout(15000);
  await page.goto(draftUrl, { waitUntil: "domcontentloaded", timeout: 60000 }).catch(() => null);
  await page.waitForTimeout(6000);
  const count = await countEditorZhihuImages(page);
  return {
    persisted: count >= minImageCount,
    count,
  };
}

async function fillRichBodyLocator(locator, page, markdown, fallbackText, payload = {}) {
  if (!locator) {
    return { applied: false, wordCount: 0, synced: false };
  }
  const blocks = parseMarkdownBodyBlocks(markdown);
  const textBlocks = [];
  let imageSlot = 0;
  for (let blockIndex = 0; blockIndex < blocks.length; blockIndex += 1) {
    const block = blocks[blockIndex];
    if (block.type === "image") {
      block.uploadSlot = imageSlot;
      imageSlot += 1;
      textBlocks.push({ type: "paragraph", text: `[[AIMG-${block.uploadSlot}]]` });
      const caption = sanitizeImageCaption(block.caption, block.alt);
      if (caption) {
        textBlocks.push({ type: "paragraph", text: caption });
      }
      if (block.role === "footer") {
        for (let scanIndex = blockIndex - 1; scanIndex >= 0; scanIndex -= 1) {
          const previous = blocks[scanIndex];
          if (previous.type === "paragraph" && trimText(previous.text)) {
            block.footerAnchor = trimText(previous.text).slice(-48);
            break;
          }
        }
      }
      continue;
    }
    textBlocks.push(block);
  }
  const pasteHtml = blocksToRichEditorHtml(textBlocks.length ? textBlocks : blocks);
  const pastePlain = trimText(markdownWithoutImageLines(markdown)) || trimText(fallbackText);
  if (!pasteHtml && !pastePlain) {
    return { applied: false, wordCount: 0, synced: false };
  }
  try {
    const pasted = await pasteHtmlIntoEditable(page, locator, pasteHtml, pastePlain);
    if (!pasted) {
      return { applied: false, wordCount: 0, synced: false };
    }
    const minBodyLength = expectedEditorBodyLength(markdown, fallbackText, payload);
    const sync = await waitForEditorDraftSynced(page, minBodyLength, 30000);
    const persisted = sync.synced
      ? await verifyDraftBodyPersisted(page, minBodyLength)
      : false;
    if (!persisted) {
      return {
        applied: false,
        wordCount: sync.bodyLength,
        synced: false,
        expectedWordCount: minBodyLength,
      };
    }
    const bodySelector = await pickBestBodySelector(page);
    const bodyLocator = bodySelector ? page.locator(bodySelector).first() : locator;
    const imageBlocks = blocks.filter((block) => block.type === "image");
    let imageFailures = 0;
    const imageUploadResults = [];
    for (const block of imageBlocks) {
      const imageResult = await uploadInlineImageViaToolbar(page, bodyLocator, block);
      imageUploadResults.push({
        alt: trimText(block.alt || ""),
        role: block.role || "body",
        uploadSlot: block.uploadSlot,
        ...imageResult,
      });
      if (!imageResult.uploaded) {
        imageFailures += 1;
        await removeEditorTextMarker(bodyLocator, imageUploadAnchorText(block));
      }
    }
    const requiredImages = imageBlocks.length;
    const uploadedCount = imageUploadResults.filter((item) => item.uploaded).length;
    const imageVerify = uploadedCount > 0
      ? await verifyDraftImagesPersisted(page, uploadedCount)
      : { persisted: requiredImages === 0, count: imageBlocks.length ? await countEditorZhihuImages(page) : 0 };
    const imageDecision = decideZhihuImagePublish({
      requiredImages,
      uploadedCount,
      visibleCount: imageVerify.count,
    });
    if (!imageDecision.applied) {
      return {
        applied: false,
        wordCount: sync.bodyLength,
        synced: true,
        expectedWordCount: minBodyLength,
        imageFailures: Math.max(imageFailures, imageDecision.imageFailures),
        imagePartial: false,
        imageCount: imageVerify.count,
        expectedImageCount: imageBlocks.length,
        requiredImageCount: requiredImages,
        imageUploadResults,
      };
    }
    imageFailures = imageDecision.imageFailures;
    await page.keyboard.press("Escape").catch(() => null);
    await page.locator(TITLE_SELECTORS.join(", ")).first().click({ timeout: 3000 }).catch(() => null);
    await page.waitForTimeout(3000);
    return {
      applied: true,
      wordCount: sync.bodyLength,
      synced: true,
      expectedWordCount: minBodyLength,
      imageFailures,
      imagePartial: imageDecision.imagePartial,
      imageCount: imageVerify.count,
      expectedImageCount: imageBlocks.length,
      requiredImageCount: requiredImages,
      imageUploadResults,
    };
  } catch {}
  return { applied: false, wordCount: 0, synced: false };
}

function zhihuImageAudit(bodyResult) {
  return {
    image_count: bodyResult?.imageCount || 0,
    expected_image_count: bodyResult?.expectedImageCount || 0,
    image_failures: bodyResult?.imageFailures || 0,
    image_partial: Boolean(bodyResult?.imagePartial),
    image_upload_results: Array.isArray(bodyResult?.imageUploadResults) ? bodyResult.imageUploadResults : [],
  };
}

function textIncludesAny(text, markers) {
  return markers.some((marker) => text.includes(marker));
}

function firstMatchingMarker(text, markers) {
  return markers.find((marker) => text.includes(marker)) || "";
}

async function inspectCoverPanel(page) {
  try {
    return await page.evaluate(() => {
      const markerPattern = /(添加文章封面|添加封面|上传封面|更换封面|删除封面)/;
      const nodes = Array.from(document.querySelectorAll("button,label,div,span"))
        .filter((node) => markerPattern.test((node.innerText || node.textContent || "").trim()));
      for (const node of nodes) {
        let current = node;
        for (let depth = 0; depth < 7 && current; depth += 1) {
          const text = (current.innerText || current.textContent || "").trim();
          const rect = current.getBoundingClientRect();
          if (
            text.includes("封面")
            && text.length < 2000
            && rect.width > 0
            && rect.height > 0
          ) {
            const preview = current.querySelector("img[src], [style*='background-image']");
            return {
              text,
              hasPreview: Boolean(preview),
              hasChangeAction: text.includes("更换封面") || text.includes("删除封面"),
              hasAddAction: text.includes("添加封面") || text.includes("上传封面") || text.includes("添加文章封面"),
            };
          }
          current = current.parentElement;
        }
      }
    });
  } catch {}
  return {
    text: "",
    hasPreview: false,
    hasChangeAction: false,
    hasAddAction: false,
  };
}

async function uploadCoverWithFileChooser(page, coverPath) {
  for (const selector of COVER_TRIGGER_SELECTORS) {
    const locator = page.locator(selector).first();
    if (!await isVisibleLocator(locator)) {
      continue;
    }
    const chooserPromise = page.waitForEvent("filechooser", { timeout: 2500 }).catch(() => null);
    try {
      await locator.click({ timeout: 3000 });
    } catch {
      try {
        await locator.click({ timeout: 3000, force: true });
      } catch {
        continue;
      }
    }
    const chooser = await chooserPromise;
    if (chooser) {
      await chooser.setFiles(coverPath);
      return selector;
    }
  }
  return "";
}

async function setCoverInputFilesFallback(page, coverPath) {
  const inputSelectors = [
    "label:has-text('添加文章封面') input[type='file']",
    "label:has-text('添加封面') input[type='file']",
    "label:has-text('上传封面') input[type='file']",
    "[class*='cover'] input[type='file']",
    "input[type='file']",
  ];
  for (const selector of inputSelectors) {
    const locator = page.locator(selector).last();
    if (!await locator.count().catch(() => 0)) {
      continue;
    }
    try {
      await locator.setInputFiles(coverPath, { timeout: 8000 });
      return selector;
    } catch {}
  }
  return "";
}

async function detectSurface(page) {
  const url = page.url();
  const title = trimText(await page.title().catch(() => ""));
  const fullText = await safeInnerText(page);
  const text = fullText.slice(0, 4000);
  const footerText = fullText.slice(-3000);
  const titleSelector = await findVisibleSelector(page, TITLE_SELECTORS);
  const bodySelector = await pickBestBodySelector(page);
  const summarySelector = await findVisibleSelector(page, SUMMARY_SELECTORS);
  const topicSelector = await findVisibleSelector(page, TOPIC_INPUT_SELECTORS);
  const publishSelector = await findVisibleSelector(page, PUBLISH_TRIGGER_SELECTORS);
  const finalPublishSelector = await findVisibleSelector(page, FINAL_PUBLISH_SELECTORS, { pickLast: true });
  const fileInputVisible = await isVisibleLocator(page.locator("input[type='file']").first());
  const loginHintSeen = url.includes("/signin") || textIncludesAny(text, LOGIN_MARKERS);
  const riskHintSeen = url.includes("/account/unhuman") || textIncludesAny(text, RISK_MARKERS);
  const publicUrl = isPublicArticleUrl(url);

  let surface = "unknown";
  if (publicUrl) {
    surface = "published";
  } else if (loginHintSeen) {
    surface = "signin";
  } else if (riskHintSeen) {
    surface = "risk";
  } else if (titleSelector || bodySelector || textIncludesAny(text, EDITOR_MARKERS) || url.includes("/write")) {
    surface = "editor";
  } else if (url.includes("/creator") || textIncludesAny(text, CREATOR_MARKERS)) {
    surface = "creator";
  }

  return {
    surface,
    url,
    title,
    loginHintSeen,
    riskHintSeen,
    manualClearanceRequired: riskHintSeen,
    titleSelector,
    bodySelector,
    summarySelector,
    topicSelector,
    publishSelector,
    finalPublishSelector,
    fileInputVisible,
    publishPanelVisible: Boolean(
      finalPublishSelector
      && textIncludesAny(footerText, ["发布设置", "文章话题", "添加话题", "添加封面", "投稿至问题"])
    ),
    publishedUrlVisible: publicUrl,
  };
}

async function waitForSurface(page, timeoutMs, preferredSurfaces = []) {
  const deadline = Date.now() + timeoutMs;
  let lastSurface = await detectSurface(page);
  while (Date.now() < deadline) {
    lastSurface = await detectSurface(page);
    if (preferredSurfaces.includes(lastSurface.surface)) {
      return lastSurface;
    }
    await page.waitForTimeout(500);
  }
  return lastSurface;
}

async function openEditorSurface(page, timeoutMs) {
  await page.goto(DEFAULT_EDITOR_URL, { waitUntil: "domcontentloaded", timeout: timeoutMs }).catch(() => null);
  await page.waitForTimeout(1500);
  return waitForSurface(page, Math.min(timeoutMs, 15000), ["editor", "signin", "risk", "published", "creator"]);
}

async function redirectRiskSurfaceToSignin(page, timeoutMs) {
  await page.goto(DEFAULT_SIGNIN_URL, { waitUntil: "domcontentloaded", timeout: timeoutMs }).catch(() => null);
  await page.waitForTimeout(1500);
  return waitForSurface(page, Math.min(timeoutMs, 15000), ["signin", "editor", "risk", "creator"]);
}

async function waitForLoginCompletion(page, context, options) {
  const {
    stateFile,
    timeoutMs,
    smsCodeFile,
  } = options;
  const startedAt = Date.now();
  let lastSurface = await detectSurface(page);
  let codeAutomation = {
    codeFilled: false,
    codeSelector: "",
    submitSelector: "",
  };

  while (Date.now() - startedAt < timeoutMs) {
    lastSurface = await detectSurface(page);
    if (["editor", "creator", "published"].includes(lastSurface.surface)) {
      const stateSaved = await writeStorageState(context, stateFile);
      return {
        surface: lastSurface,
        stateSaved,
        codeAutomation,
      };
    }
    codeAutomation = await fillSmsCodeIfAvailable(page, smsCodeFile, codeAutomation);
    await page.waitForTimeout(1000);
  }

  return {
    surface: lastSurface,
    stateSaved: false,
    codeAutomation,
  };
}

async function bootstrapSession(runtime, args, stateFile, timeoutMs) {
  const { context, page } = runtime;
  const loginMode = trimText(args["login-mode"] || process.env.ZHIHU_LOGIN_MODE || "password").toLowerCase();
  const smsCodeFile = trimText(args["sms-code-file"] || process.env.ZHIHU_SMS_CODE_FILE || DEFAULT_SMS_CODE_FILE);
  await checkpointProgress(args, "bootstrap_open_editor", {
    requested_url: DEFAULT_EDITOR_URL,
    login_mode: loginMode,
    sms_code_file: smsCodeFile,
  });
  const cookieInjection = await injectSessionCookies(context, stateFile);
  let surface = await openEditorSurface(page, timeoutMs);
  if (surface.surface === "editor" || surface.surface === "creator") {
    const stateSaved = await writeStorageState(context, stateFile);
    const evidence = await capturePageEvidence(page, args, "bootstrap-session-ready", {
      surface: surface.surface,
      state_saved: stateSaved,
      cookie_injection: cookieInjection,
    });
    return {
      status: "ok",
      mode: "bootstrap-session",
      live_ready: true,
      final_url: page.url(),
      surface: surface.surface,
      state_saved: stateSaved,
      cookie_injection: cookieInjection,
      evidence,
      reason: "editor_or_creator_surface_reached",
    };
  }

  if (surface.surface === "risk" || page.url().includes("/account/unhuman")) {
    await checkpointProgress(args, "bootstrap_redirect_signin_after_risk", {
      current_surface: surface.surface,
      current_url: page.url(),
      redirected_url: DEFAULT_SIGNIN_URL,
    });
    surface = await redirectRiskSurfaceToSignin(page, timeoutMs);
  }

  let loginAttempt = {};
  if (surface.surface === "signin") {
    if (loginMode === "sms") {
      loginAttempt = await attemptSmsLogin(page, args);
    } else if (loginMode === "auto") {
      loginAttempt = await attemptCredentialLogin(page);
      if (!loginAttempt.username_selector && !loginAttempt.password_selector) {
        loginAttempt = await attemptSmsLogin(page, args);
      }
    } else {
      loginAttempt = await attemptCredentialLogin(page);
    }
  }
  await checkpointProgress(args, "bootstrap_wait_manual_login", {
    current_surface: surface.surface,
    ...loginAttempt,
    login_mode: loginMode,
    sms_code_file: smsCodeFile,
  });
  const initialSmsCode = await readOptionalTrimmedFile(smsCodeFile);
  if (loginMode === "sms" && surface.surface === "signin" && !/^\d{4,8}$/.test(initialSmsCode)) {
    const reason = loginAttempt.get_code_selector ? "sms_code_required" : (loginAttempt.reason || "sms_login_not_completed");
    const evidence = await capturePageEvidence(page, args, "bootstrap-session-sms-blocked", {
      surface: surface.surface,
      cookie_injection: cookieInjection,
      ...loginAttempt,
      login_mode: loginMode,
      sms_code_file: smsCodeFile,
      sms_code_applied: false,
      reason,
    });
    return {
      status: "blocked",
      mode: "bootstrap-session",
      live_ready: false,
      final_url: page.url(),
      surface: surface.surface,
      cookie_injection: cookieInjection,
      manual_clearance_required: false,
      login_mode: loginMode,
      sms_code_file: smsCodeFile,
      sms_code_applied: false,
      evidence,
      final_blocker: reason,
      reason,
    };
  }
  const completion = await waitForLoginCompletion(page, context, {
    stateFile,
    timeoutMs,
    smsCodeFile,
  });
  const waited = completion.surface;
  const stateSaved = completion.stateSaved;
  const evidence = await capturePageEvidence(page, args, stateSaved ? "bootstrap-session-ready" : "bootstrap-session-blocked", {
    surface: waited.surface,
    state_saved: stateSaved,
    cookie_injection: cookieInjection,
    ...loginAttempt,
    login_mode: loginMode,
    sms_code_file: smsCodeFile,
    sms_code_applied: completion.codeAutomation?.codeFilled || false,
    sms_code_selector: completion.codeAutomation?.codeSelector || "",
    sms_submit_selector: completion.codeAutomation?.submitSelector || "",
  });
  return {
    status: stateSaved ? "ok" : "blocked",
    mode: "bootstrap-session",
    live_ready: stateSaved,
    final_url: page.url(),
    surface: waited.surface,
    state_saved: stateSaved,
    cookie_injection: cookieInjection,
    manual_clearance_required: waited.manualClearanceRequired,
    login_mode: loginMode,
    sms_code_file: smsCodeFile,
    sms_code_applied: completion.codeAutomation?.codeFilled || false,
    evidence,
    reason: stateSaved
      ? "editor_or_creator_surface_reached"
      : (
        waited.manualClearanceRequired
          ? "manual_clearance_required"
          : (waited.surface === "signin" ? "session_invalid_or_missing" : "editor_surface_not_reached_after_bootstrap")
      ),
  };
}

async function checkSession(runtime, args, stateFile, timeoutMs) {
  const { context, page } = runtime;
  const cookieInjection = await injectSessionCookies(context, stateFile);
  await checkpointProgress(args, "check_session_open_editor", {
    requested_url: DEFAULT_EDITOR_URL,
  });
  const surface = await openEditorSurface(page, timeoutMs);
  const evidence = await capturePageEvidence(page, args, "check-session", {
    surface: surface.surface,
    cookie_injection: cookieInjection,
  });
  return {
    status: surface.surface === "editor" ? "ok" : "blocked",
    mode: "check-session",
    live_ready: surface.surface === "editor",
    final_url: page.url(),
    surface: surface.surface,
    editor_ready: surface.surface === "editor",
    cookie_injection: cookieInjection,
    manual_clearance_required: surface.manualClearanceRequired,
    evidence,
    reason: surface.surface === "editor"
      ? "editor_surface_reached"
      : (surface.manualClearanceRequired
        ? "manual_clearance_required"
        : (surface.surface === "signin" ? "session_invalid_or_missing" : "session_invalid_or_missing")),
  };
}

async function findTitleSelector(page) {
  for (const selector of TITLE_SELECTORS) {
    const locator = page.locator(selector).first();
    if (await isVisibleLocator(locator)) {
      return selector;
    }
  }
  return "";
}

async function fillTitle(page, title) {
  const selector = await findTitleSelector(page);
  if (!selector) {
    return { applied: false, selector: "", reason: "title_input_not_found" };
  }
  const locator = await resolveLocator(page, selector);
  const applied = await fillEditableLocator(locator, page, title);
  return {
    applied,
    selector,
    reason: applied ? "" : "title_fill_failed",
  };
}

async function fillBody(page, text, markdown = "", payload = {}) {
  const selector = await pickBestBodySelector(page);
  if (!selector) {
    return { applied: false, selector: "", reason: "editor_input_not_found", wordCount: 0, synced: false };
  }
  const locator = await resolveLocator(page, selector);
  const result = await fillRichBodyLocator(locator, page, markdown, text, payload);
  return {
    applied: Boolean(result.applied),
    selector,
    reason: result.applied
      ? ""
      : (result.imageFailures
        ? "body_image_upload_failed"
        : (result.synced === false ? "editor_draft_not_synced" : "editor_fill_failed")),
    wordCount: result.wordCount || 0,
    synced: Boolean(result.synced),
    expectedWordCount: result.expectedWordCount || 0,
    imageCount: result.imageCount || 0,
    expectedImageCount: result.expectedImageCount || 0,
    imageFailures: result.imageFailures || 0,
    imagePartial: Boolean(result.imagePartial),
    imageUploadResults: Array.isArray(result.imageUploadResults) ? result.imageUploadResults : [],
  };
}

async function ensurePublishPanel(page, timeoutMs) {
  await scrollPublishPanelIntoView(page);
  let surface = await detectSurface(page);
  if (surface.publishPanelVisible) {
    return {
      opened: true,
      triggerSelector: "",
      surface,
    };
  }
  const triggerSelector = await clickFirstVisible(page, PUBLISH_TRIGGER_SELECTORS, { timeoutMs: 5000 });
  if (!triggerSelector) {
    await scrollPublishPanelIntoView(page);
    surface = await detectSurface(page);
    if (surface.publishPanelVisible) {
      return {
        opened: true,
        triggerSelector: "",
        surface,
      };
    }
    return {
      opened: false,
      triggerSelector: "",
      surface,
      reason: "publish_button_missing",
    };
  }
  const deadline = Date.now() + Math.min(timeoutMs, 12000);
  while (Date.now() < deadline) {
    await page.waitForTimeout(500);
    await scrollPublishPanelIntoView(page);
    surface = await detectSurface(page);
    if (surface.publishPanelVisible || surface.surface === "published" || surface.surface === "risk" || surface.surface === "signin") {
      break;
    }
  }
  const opened = Boolean(surface.publishPanelVisible);
  return {
    opened,
    triggerSelector,
    surface,
    reason: opened
      ? ""
      : (
        surface.manualClearanceRequired
          ? "manual_clearance_required"
          : (surface.surface === "signin" ? "session_invalid_or_missing" : "publish_panel_not_opened")
      ),
  };
}

async function fillSummary(page, summary) {
  const normalized = trimText(summary);
  if (!normalized) {
    return { applied: false, selector: "", reason: "summary_missing", optional: true };
  }
  const selector = await findVisibleSelector(page, SUMMARY_SELECTORS);
  if (!selector) {
    return { applied: false, selector: "", reason: "summary_input_not_found", optional: true };
  }
  const locator = await resolveLocator(page, selector);
  const applied = await fillEditableLocator(locator, page, summary);
  return {
    applied,
    selector,
    reason: applied ? "" : "summary_fill_failed",
    optional: false,
  };
}

async function fillTopicTags(page, tags) {
  if (!Array.isArray(tags) || !tags.length) {
    return {
      appliedCount: 0,
      selector: "",
      reason: "topic_tags_missing",
    };
  }
  let selector = await findVisibleSelector(page, TOPIC_INPUT_SELECTORS);
  if (!selector) {
    await clickFirstVisible(page, [
      "button:has-text('添加话题')",
      "button:has-text('添加标签')",
      "[role='button']:has-text('添加话题')",
      "[role='button']:has-text('添加标签')",
    ], { timeoutMs: 3000 });
    await page.waitForTimeout(800);
    selector = await findVisibleSelector(page, TOPIC_INPUT_SELECTORS);
  }
  if (!selector) {
    return {
      appliedCount: 0,
      selector: "",
      reason: "topic_input_not_found",
    };
  }
  const locator = await resolveLocator(page, selector);
  let appliedCount = 0;
  for (const tag of tags.slice(0, 5)) {
    try {
      await locator.click({ timeout: 3000 });
      await locator.fill(tag, { timeout: 3000 });
      await page.waitForTimeout(500);
      const option = page.locator("[role='option'], .Select-option, li").filter({ hasText: tag }).first();
      if (await isVisibleLocator(option)) {
        await option.click({ timeout: 3000 }).catch(() => null);
      } else {
        await page.keyboard.press("Enter").catch(() => null);
      }
      appliedCount += 1;
      await page.waitForTimeout(400);
    } catch {
      break;
    }
  }
  return {
    appliedCount,
    selector,
    reason: appliedCount ? "" : "topic_apply_failed",
  };
}

async function uploadCover(page, coverPath) {
  const targetPath = trimText(coverPath);
  if (!targetPath) {
    return {
      attempted: false,
      uploaded: false,
      selector: "",
      triggerSelector: "",
      confirmSelector: "",
      confirmationSelector: "",
      confirmationMarker: "",
      failureMarker: "",
      reason: "cover_not_provided",
    };
  }
  if (!await pathExists(targetPath)) {
    return {
      attempted: false,
      uploaded: false,
      selector: "",
      triggerSelector: "",
      confirmSelector: "",
      confirmationSelector: "",
      confirmationMarker: "",
      failureMarker: "",
      reason: "cover_file_missing",
    };
  }
  let triggerSelector = "";
  let inputSelector = "";
  try {
    triggerSelector = await uploadCoverWithFileChooser(page, targetPath);
    if (!triggerSelector) {
      triggerSelector = await clickFirstVisible(page, COVER_TRIGGER_SELECTORS, { timeoutMs: 3000 });
      await page.waitForTimeout(1200);
      inputSelector = await setCoverInputFilesFallback(page, targetPath);
    }
    if (!triggerSelector && !inputSelector) {
      return {
        attempted: true,
        uploaded: false,
        selector: "",
        triggerSelector: "",
        confirmSelector: "",
        confirmationSelector: "",
        confirmationMarker: "",
        failureMarker: "",
        reason: "cover_upload_control_not_found",
      };
    }
    await page.waitForTimeout(2500);
    const confirmSelector = await clickFirstVisible(page, COVER_CONFIRM_SELECTORS, {
      timeoutMs: 4000,
    });
    if (confirmSelector) {
      await page.waitForTimeout(2500);
    }
    // 增加额外的等待时间，让页面有足够时间处理上传
    await page.waitForTimeout(1500);
    
    const coverPanel = await inspectCoverPanel(page);
    const coverText = coverPanel.text || "";
    const failureMarker = firstMatchingMarker(coverText, COVER_FAILURE_MARKERS);
    const confirmationSelector = await findVisibleSelector(page, COVER_SUCCESS_SELECTORS);
    const confirmationMarker = firstMatchingMarker(coverText, COVER_SUCCESS_MARKERS);
    
    const coverImageVisible = coverPanel.hasPreview || await page.locator("img[src*='zhimg'], [style*='zhimg'], [class*='cover'] img, [class*='cover-image']").first().isVisible({ timeout: 2000 }).catch(() => false);
    
    const uploaded = Boolean(confirmationSelector || confirmationMarker || coverImageVisible || coverPanel.hasChangeAction) && !failureMarker;
    return {
      attempted: true,
      uploaded,
      selector: inputSelector || "filechooser",
      triggerSelector,
      confirmSelector,
      confirmationSelector,
      confirmationMarker,
      failureMarker,
      reason: failureMarker ? "cover_upload_failed" : (uploaded ? "" : "cover_upload_unconfirmed"),
    };
  } catch {
    return {
      attempted: true,
      uploaded: false,
      selector: inputSelector || "filechooser",
      triggerSelector,
      confirmSelector: "",
      confirmationSelector: "",
      confirmationMarker: "",
      failureMarker: "",
      reason: "cover_upload_failed",
    };
  }
}

async function resolvePublishedUrl(page, timeoutMs, draftUrl = "") {
  const deadline = Date.now() + timeoutMs;
  let successSeen = false;
  const preSubmitDraftId = trimText(draftUrl).match(/\/p\/(\d+)(?:\/edit|[/?#]|$)/)?.[1] || "";
  while (Date.now() < deadline) {
    const currentUrl = trimText(page.url());
    if (isPublicArticleUrl(currentUrl)) {
      return {
        url: currentUrl,
        source: "page_url",
        validationMessage: "",
      };
    }

    const allowEditFallback = false;
    const candidates = await collectPublishedArticleUrlCandidates(page, preSubmitDraftId, allowEditFallback);
    for (const candidate of candidates) {
      if (!isPublicArticleUrl(candidate.url)) {
        continue;
      }
      const stillOnEditPage = /\/edit(?:[/?#]|$)/.test(trimText(page.url()));
      const needsVerification = candidate.source === "edit_fallback" || stillOnEditPage;
      if (needsVerification) {
        const verified = await verifyPublishedArticleAccessible(
          page,
          candidate.url,
          Math.max(5000, deadline - Date.now()),
        );
        if (!verified) {
          continue;
        }
      }
      return {
        url: candidate.url,
        source: candidate.source || "detected_publish_url",
        validationMessage: "",
      };
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

    const text = await safeInnerText(page);
    if (textIncludesAny(text, SUCCESS_MARKERS)) {
      successSeen = true;
    }
    await page.waitForTimeout(800);
  }
  return {
    url: "",
    source: "",
    validationMessage: successSeen
      ? "publish_success_seen_but_public_url_not_resolved"
      : "public_url_not_resolved",
  };
}

async function resolvePublishedUrlOnly(runtime, args, stateFile, timeoutMs, payload) {
  const { context, page } = runtime;
  const cookieInjection = await injectSessionCookies(context, stateFile);
  const surface = await openEditorSurface(page, timeoutMs);
  if (!["editor", "creator", "published"].includes(surface.surface)) {
    const evidence = await capturePageEvidence(page, args, "resolve-published-url-blocked", {
      surface: surface.surface,
      cookie_injection: cookieInjection,
    });
    return {
      status: "blocked",
      mode: "resolve-published-url",
      live_ready: false,
      final_url: page.url(),
      surface: surface.surface,
      final_blocker: surface.manualClearanceRequired
        ? "manual_clearance_required"
        : (surface.surface === "signin" ? "session_invalid_or_missing" : "published_article_not_found"),
      manual_clearance_required: surface.manualClearanceRequired,
      cookie_injection: cookieInjection,
      evidence,
      reason: surface.manualClearanceRequired
        ? "manual_clearance_required"
        : (surface.surface === "signin" ? "session_invalid_or_missing" : "published_article_not_found"),
    };
  }

  const published = await resolvePublishedUrl(page, Math.min(timeoutMs, 20000), "");
  const evidence = await capturePageEvidence(page, args, "resolve-published-url-result", {
    published_article_url: published.url,
    resolution_source: published.source,
    validation_message: published.validationMessage,
    preferred_title: trimText(payload?.article?.title || payload?.draft?.title || ""),
  });
  return {
    status: published.url ? "ok" : "blocked",
    mode: "resolve-published-url",
    live_ready: Boolean(published.url),
    final_url: published.url || page.url(),
    surface: published.url ? "published" : surface.surface,
    published_article_url: published.url || "",
    publish_resolution_source: published.source || "",
    final_blocker: published.url ? "" : (published.validationMessage || "published_article_not_found"),
    manual_clearance_required: published.validationMessage === "manual_clearance_required_after_publish_click",
    cookie_injection: cookieInjection,
    evidence,
    reason: published.url ? "publish_url_resolved" : (published.validationMessage || "published_article_not_found"),
  };
}

async function clickFinalPublish(page) {
  const publishReady = await waitForEnabledPublishButton(page, 15000);
  if (!publishReady.ready) {
    return {
      clicked: false,
      selector: "",
      reason: "publish_button_disabled",
    };
  }

  const triggerSelector = await clickFirstVisible(page, FINAL_PUBLISH_SELECTORS, {
    timeoutMs: 8000,
    requireEnabled: true,
  });
  if (!triggerSelector) {
    return {
      clicked: false,
      selector: "",
      reason: "final_publish_button_missing",
    };
  }

  const modalDeadline = Date.now() + 12000;
  let confirmSelector = "";
  while (Date.now() < modalDeadline) {
    await page.waitForTimeout(600);
    confirmSelector = await clickFirstVisible(page, FINAL_PUBLISH_MODAL_SELECTORS, {
      timeoutMs: 1500,
      requireEnabled: true,
    });
    if (confirmSelector) {
      break;
    }
    const bodyText = await safeInnerText(page);
    if (textIncludesAny(bodyText.slice(-1200), SUCCESS_MARKERS)) {
      break;
    }
    if (!textIncludesAny(bodyText.slice(-1200), ["继续发布", "确认发布", "立即发布", "未上传成功", "重新上传"])) {
      break;
    }
  }

  if (!confirmSelector) {
    const bodyText = await safeInnerText(page);
    if (textIncludesAny(bodyText.slice(-1200), ["未上传成功", "重新上传后再尝试发布", "继续发布"])) {
      return {
        clicked: false,
        selector: triggerSelector,
        triggerSelector,
        confirmSelector: "",
        reason: "publish_warning_modal_unresolved",
      };
    }
  }

  return {
    clicked: true,
    selector: confirmSelector || triggerSelector,
    triggerSelector,
    confirmSelector,
    reason: "",
  };
}

async function prepareLive(runtime, args, stateFile, timeoutMs, payload, submit) {
  const { context, page } = runtime;
  await checkpointProgress(args, "prepare_live_open_editor", {
    requested_url: DEFAULT_EDITOR_URL,
    submit_requested: submit,
  });
  const cookieInjection = await injectSessionCookies(context, stateFile);
  let surface = await openEditorSurface(page, timeoutMs);
  if (surface.surface !== "editor") {
    const evidence = await capturePageEvidence(page, args, "prepare-live-blocked", {
      surface: surface.surface,
      cookie_injection: cookieInjection,
    });
    return {
      status: "blocked",
      mode: "prepare-live",
      live_ready: false,
      final_url: page.url(),
      surface: surface.surface,
      final_blocker: surface.manualClearanceRequired
        ? "manual_clearance_required"
        : (surface.surface === "signin" ? "session_invalid_or_missing" : "session_invalid_or_missing"),
      manual_clearance_required: surface.manualClearanceRequired,
      cookie_injection: cookieInjection,
      evidence,
      reason: surface.manualClearanceRequired
        ? "manual_clearance_required"
        : (surface.surface === "signin" ? "session_invalid_or_missing" : "session_invalid_or_missing"),
    };
  }

  const draft = payload?.draft || {};
  const titleResult = await fillTitle(page, trimText(draft.title));
  if (!titleResult.applied) {
    const evidence = await capturePageEvidence(page, args, "prepare-live-title-blocked", {
      surface: surface.surface,
      title_selector: titleResult.selector,
    });
    return {
      status: "blocked",
      mode: "prepare-live",
      live_ready: false,
      final_url: page.url(),
      surface: surface.surface,
      final_blocker: titleResult.reason,
      title_selector: titleResult.selector,
      cookie_injection: cookieInjection,
      evidence,
      reason: titleResult.reason,
    };
  }

  await checkpointProgress(args, "prepare_live_fill_body", {
    title_selector: titleResult.selector,
  });
  const bodyResult = await fillBody(
    page,
    trimText(draft.editor_body_text),
    trimText(draft.markdown),
    payload || {},
  );
  if (!bodyResult.applied) {
    const evidence = await capturePageEvidence(page, args, "prepare-live-body-blocked", {
      surface: surface.surface,
      title_selector: titleResult.selector,
      body_selector: bodyResult.selector,
      word_count: bodyResult.wordCount,
      expected_word_count: bodyResult.expectedWordCount,
    });
    return {
      status: "blocked",
      mode: "prepare-live",
      live_ready: false,
      final_url: page.url(),
      surface: surface.surface,
      final_blocker: bodyResult.reason,
      title_selector: titleResult.selector,
      body_selector: bodyResult.selector,
      editor_word_count: bodyResult.wordCount,
      expected_word_count: bodyResult.expectedWordCount,
      ...zhihuImageAudit(bodyResult),
      cookie_injection: cookieInjection,
      evidence,
      reason: bodyResult.reason,
    };
  }

  await page.waitForTimeout(1200);
  const draftUrl = page.url();
  await scrollPublishPanelIntoView(page);
  await page.waitForTimeout(800);
  await checkpointProgress(args, "prepare_live_open_publish_panel", {
    draft_url: draftUrl,
    title_selector: titleResult.selector,
    body_selector: bodyResult.selector,
  });
  const publishPanel = await ensurePublishPanel(page, timeoutMs);
  if (!publishPanel.opened) {
    const evidence = await capturePageEvidence(page, args, "prepare-live-publish-panel-blocked", {
      trigger_selector: publishPanel.triggerSelector,
      draft_url: draftUrl,
    });
    return {
      status: "blocked",
      mode: "prepare-live",
      live_ready: false,
      final_url: page.url(),
      draft_url: draftUrl,
      surface: publishPanel.surface?.surface || surface.surface,
      final_blocker: publishPanel.reason || "publish_panel_not_opened",
      title_selector: titleResult.selector,
      body_selector: bodyResult.selector,
      publish_trigger_selector: publishPanel.triggerSelector,
      draft_prepared: true,
      title_applied: true,
      body_applied: true,
      ...zhihuImageAudit(bodyResult),
      cookie_injection: cookieInjection,
      evidence,
      reason: publishPanel.reason || "publish_panel_not_opened",
    };
  }

  await checkpointProgress(args, "prepare_live_fill_publish_metadata", {
    trigger_selector: publishPanel.triggerSelector,
  });
  const summaryResult = await fillSummary(page, trimText(draft.summary));
  const topicResult = await fillTopicTags(page, Array.isArray(draft.topic_tags) ? draft.topic_tags : []);
  await page.keyboard.press("Escape").catch(() => null);
  await page.waitForTimeout(500);
  const coverResult = await uploadCover(page, trimText(draft.cover_image_path));
  const publishBoundaryEvidence = await capturePageEvidence(page, args, submit ? "prepare-live-before-submit" : "prepare-live-ready", {
    draft_url: draftUrl,
    title_selector: titleResult.selector,
    body_selector: bodyResult.selector,
    publish_trigger_selector: publishPanel.triggerSelector,
    summary_selector: summaryResult.selector,
    topic_selector: topicResult.selector,
    cover_selector: coverResult.selector,
    cover_trigger_selector: coverResult.triggerSelector,
    cover_confirm_selector: coverResult.confirmSelector,
    cover_confirmation_selector: coverResult.confirmationSelector,
    cover_confirmation_marker: coverResult.confirmationMarker,
    cover_failure_marker: coverResult.failureMarker,
    topic_tags_applied: topicResult.appliedCount,
  });

  const blockers = [];
  if (!summaryResult.applied && !summaryResult.optional) {
    blockers.push(summaryResult.reason || "summary_input_not_found");
  }
  if (trimText(draft.cover_image_path) && !coverResult.uploaded) {
    blockers.push(coverResult.reason || "cover_upload_failed");
  }
  if (submit) {
    await page.waitForTimeout(5000);
    const resync = await waitForEditorDraftSynced(
      page,
      bodyResult.expectedWordCount || expectedEditorBodyLength(trimText(draft.markdown), trimText(draft.editor_body_text), payload || {}),
      Math.min(timeoutMs, 30000),
    );
    if (!resync.synced) {
      blockers.push("editor_draft_not_synced_before_submit");
    }
  }

  if (!submit) {
    return {
      status: blockers.length ? "blocked" : "ok",
      mode: "prepare-live",
      live_ready: !blockers.length,
      final_url: page.url(),
      draft_url: draftUrl,
      surface: publishPanel.surface.surface,
      title_selector: titleResult.selector,
      body_selector: bodyResult.selector,
      publish_trigger_selector: publishPanel.triggerSelector,
      summary_selector: summaryResult.selector,
      topic_selector: topicResult.selector,
      cover_selector: coverResult.selector,
      draft_prepared: true,
      title_applied: true,
      body_applied: true,
      ...zhihuImageAudit(bodyResult),
      summary_applied: summaryResult.applied,
      topic_tags_applied: topicResult.appliedCount,
      cover_upload_attempted: coverResult.attempted,
      cover_upload_confirmed: coverResult.uploaded,
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
      draft_url: draftUrl,
      surface: publishPanel.surface.surface,
      title_selector: titleResult.selector,
      body_selector: bodyResult.selector,
      publish_trigger_selector: publishPanel.triggerSelector,
      summary_selector: summaryResult.selector,
      topic_selector: topicResult.selector,
      cover_selector: coverResult.selector,
      draft_prepared: true,
      title_applied: true,
      body_applied: true,
      ...zhihuImageAudit(bodyResult),
      summary_applied: summaryResult.applied,
      topic_tags_applied: topicResult.appliedCount,
      cover_upload_attempted: coverResult.attempted,
      cover_upload_confirmed: coverResult.uploaded,
      publish_confirmed: false,
      blockers,
      final_blocker: blockers[0],
      cookie_injection: cookieInjection,
      evidence: publishBoundaryEvidence,
      reason: blockers[0],
    };
  }

  await checkpointProgress(args, "prepare_live_click_final_publish", {
    draft_url: draftUrl,
  });
  await scrollPublishPanelIntoView(page);
  const finalPublish = await clickFinalPublish(page);
  if (!finalPublish.clicked) {
    const evidence = combineEvidence(
      publishBoundaryEvidence,
      await capturePageEvidence(page, args, "prepare-live-final-publish-blocked", {
        draft_url: draftUrl,
      }),
    );
    return {
      status: "blocked",
      mode: "submit",
      live_ready: false,
      final_url: page.url(),
      draft_url: draftUrl,
      surface: publishPanel.surface.surface,
      title_selector: titleResult.selector,
      body_selector: bodyResult.selector,
      publish_trigger_selector: publishPanel.triggerSelector,
      final_publish_selector: finalPublish.selector,
      draft_prepared: true,
      title_applied: true,
      body_applied: true,
      ...zhihuImageAudit(bodyResult),
      summary_applied: summaryResult.applied,
      topic_tags_applied: topicResult.appliedCount,
      cover_upload_attempted: coverResult.attempted,
      cover_upload_confirmed: coverResult.uploaded,
      publish_confirmed: false,
      final_blocker: finalPublish.reason,
      cookie_injection: cookieInjection,
      evidence,
      reason: finalPublish.reason,
    };
  }

  await page.waitForTimeout(4000);
  try {
    await page.waitForURL((url) => !url.toString().includes("/edit"), {
      timeout: Math.min(timeoutMs, 20000),
    });
  } catch {}
  const published = await resolvePublishedUrl(page, Math.min(timeoutMs, 30000), draftUrl);
  const postSubmitEvidence = await capturePageEvidence(page, args, "publish-result", {
    published_article_url: published.url,
    resolution_source: published.source,
    validation_message: published.validationMessage,
    preferred_title: trimText(draft.title),
    article_page_id: trimText(payload?.article?.page_id || ""),
  });
  const evidence = combineEvidence(publishBoundaryEvidence, postSubmitEvidence);
  const publishConfirmed = Boolean(published.url);
  const finalBlocker = publishConfirmed ? "" : (published.validationMessage || "public_url_not_resolved");
  return {
    status: publishConfirmed ? "ok" : "blocked",
    mode: "submit",
    live_ready: publishConfirmed,
    final_url: published.url || page.url(),
    draft_url: draftUrl,
    surface: publishConfirmed ? "published" : publishPanel.surface.surface,
    title_selector: titleResult.selector,
    body_selector: bodyResult.selector,
    publish_trigger_selector: publishPanel.triggerSelector,
    final_publish_selector: finalPublish.selector,
    draft_prepared: true,
    title_applied: true,
    body_applied: true,
    summary_applied: summaryResult.applied,
    topic_tags_applied: topicResult.appliedCount,
    cover_upload_attempted: coverResult.attempted,
    cover_upload_confirmed: coverResult.uploaded,
    publish_requested: true,
    publish_confirmed: publishConfirmed,
    manual_clearance_required: published.validationMessage === "manual_clearance_required_after_publish_click",
    published_article_url: published.url,
    publish_resolution_source: published.source,
    final_blocker: finalBlocker,
    cookie_injection: cookieInjection,
    evidence,
    reason: publishConfirmed ? "publish_confirmed" : finalBlocker,
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const action = trimText(args.action);
  if (!action) {
    throw new Error("Missing required flag: --action");
  }
  const headless = parseBool(args.headless, action === "check-session");
  const timeoutMs = Number(args["timeout-ms"] || 45000);
  const stateFile = trimText(args["state-file"]);
  const payload = await loadJsonFile(args["payload-file"]).catch(() => null);
  const submit = parseBool(args.submit, false);
  const runtime = await launchContext({
    headless,
    stateFile,
    preferPersistent: true,
    allowFreshPersistentProfile: action === "bootstrap-session",
  });
  let result;
  try {
    if (action === "bootstrap-session") {
      result = await bootstrapSession(runtime, args, stateFile, timeoutMs);
    } else if (action === "check-session") {
      result = await checkSession(runtime, args, stateFile, timeoutMs);
    } else if (action === "prepare-live") {
      result = await prepareLive(runtime, args, stateFile, timeoutMs, payload || {}, submit);
    } else if (action === "resolve-published-url") {
      result = await resolvePublishedUrlOnly(runtime, args, stateFile, timeoutMs, payload || {});
    } else {
      throw new Error(`Unsupported action: ${action}`);
    }
  } catch (error) {
    result = {
      status: "error",
      mode: action,
      final_url: runtime.page?.url?.() || "",
      reason: trimText(error?.message || error),
      error: String(error?.stack || error),
    };
    await checkpointResult(args, result);
    throw error;
  } finally {
    await checkpointResult(args, result || {
      status: "error",
      mode: action,
      reason: "helper_exited_without_result",
    });
    await closeRuntime(runtime);
  }
}

main().catch((error) => {
  const message = trimText(error?.message || error);
  process.stderr.write(`${message}\n`);
  process.exit(1);
});
