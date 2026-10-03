import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { clearStaleChromiumSingletonLocks } from "./profile_lock.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DEFAULT_PROFILE_DIR = path.resolve(__dirname, "credentials/csdn-browser-profile");
const DEFAULT_LOCALE = process.env.CSDN_BROWSER_LOCALE || "zh-CN";
const DEFAULT_TIMEZONE = process.env.CSDN_BROWSER_TIMEZONE || "Asia/Shanghai";
const DEFAULT_USER_AGENT = process.env.CSDN_BROWSER_USER_AGENT
  || "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36";
const TRAFFIC_MANAGE_URL = "https://mp.csdn.net/mp_blog/manage/traffic";
const FAN_BROADCAST_URL = "https://mp.csdn.net/mp_others/tools/fanService/fanadd?spm=1011.2434.3001.10351";
const ARTICLE_MANAGE_URL_CANDIDATES = [
  "https://mp.csdn.net/mp_blog/manage/article",
  "https://mp.csdn.net/mp_blog/manage",
  "https://mp.csdn.net/",
];

function parseArgs(argv) {
  const result = { _: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith("--")) {
      result._.push(token);
      continue;
    }
    const key = token.slice(2);
    const next = argv[i + 1];
    if (next && !next.startsWith("--")) {
      result[key] = next;
      i += 1;
      continue;
    }
    result[key] = "true";
  }
  return result;
}

async function readJson(jsonPath) {
  const raw = await fs.readFile(jsonPath, "utf8");
  return JSON.parse(raw);
}

function browserProfileDir() {
  return process.env.CSDN_BROWSER_PROFILE_DIR || DEFAULT_PROFILE_DIR;
}

async function writeJson(jsonPath, value) {
  await fs.mkdir(path.dirname(jsonPath), { recursive: true });
  await fs.writeFile(jsonPath, JSON.stringify(value, null, 2), "utf8");
}

async function writeText(filePath, value) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, String(value || ""), "utf8");
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

function parseBool(value, fallback = false) {
  if (value === undefined) {
    return fallback;
  }
  return String(value).toLowerCase() === "true";
}

function evidenceDir(args) {
  const raw = String(args["evidence-dir"] || "").trim();
  return raw || "";
}

async function saveEvidenceText(args, name, value) {
  const dir = evidenceDir(args);
  if (!dir) {
    return "";
  }
  const outputPath = path.join(dir, name);
  await writeText(outputPath, value);
  return outputPath;
}

async function saveEvidenceJson(args, name, value) {
  const dir = evidenceDir(args);
  if (!dir) {
    return "";
  }
  const outputPath = path.join(dir, name);
  await writeJson(outputPath, value);
  return outputPath;
}

async function saveEvidenceScreenshot(page, args, name) {
  const dir = evidenceDir(args);
  if (!dir) {
    return "";
  }
  await fs.mkdir(dir, { recursive: true });
  const outputPath = path.join(dir, name);
  await page.screenshot({ path: outputPath, fullPage: true });
  return outputPath;
}

async function capturePageArtifacts(page, args, prefix) {
  const html = await page.content().catch(() => "");
  const text = await page.evaluate(() => String(document.body?.innerText || "")).catch(() => "");
  const htmlPath = await saveEvidenceText(args, `${prefix}.html`, html);
  const textPath = await saveEvidenceText(args, `${prefix}.txt`, text);
  const screenshotPath = await saveEvidenceScreenshot(page, args, `${prefix}.png`);
  return {
    html_path: htmlPath,
    text_path: textPath,
    screenshot_path: screenshotPath,
  };
}

async function firstVisibleLocator(page, selectors) {
  for (const selector of selectors) {
    const locator = page.locator(selector).first();
    try {
      if (await locator.isVisible({ timeout: 1000 })) {
        return { selector, locator };
      }
    } catch {
      continue;
    }
  }
  return null;
}

async function clickFirstVisible(page, selectors) {
  const match = await firstVisibleLocator(page, selectors);
  if (!match) {
    return null;
  }
  await match.locator.click();
  return match.selector;
}

async function clickLastVisible(page, selectors) {
  for (const selector of selectors) {
    const locator = page.locator(selector);
    const count = await locator.count();
    for (let index = count - 1; index >= 0; index -= 1) {
      const candidate = locator.nth(index);
      try {
        if (await candidate.isVisible({ timeout: 1000 })) {
          await candidate.click();
          return `${selector}[${index}]`;
        }
      } catch {
        continue;
      }
    }
  }
  return null;
}

async function clickByEvaluate(page, selectors) {
  for (const selector of selectors) {
    const clicked = await page.evaluate((candidate) => {
      const elements = [...document.querySelectorAll(candidate)];
      const target = elements.reverse().find((element) => {
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      });
      if (!target) {
        return false;
      }
      target.click();
      return true;
    }, selector).catch(() => false);
    if (clicked) {
      return `eval:${selector}`;
    }
  }
  return null;
}

async function selectHiddenDropdownOption(page, selector, optionIndex = 0) {
  const result = await page.evaluate(({ candidate, index }) => {
    const options = [...document.querySelectorAll(candidate)]
      .map((element) => ({
        element,
        text: (element.innerText || "").trim(),
      }))
      .filter((item) => item.text);
    const target = options[index];
    if (!target) {
      return { ok: false, clickedText: "" };
    }
    target.element.click();
    return { ok: true, clickedText: target.text };
  }, { candidate: selector, index: optionIndex }).catch(() => ({ ok: false, clickedText: "" }));
  if (!result.ok) {
    return { selector: "", clickedText: "" };
  }
  return { selector: `eval:${selector}[${optionIndex}]`, clickedText: result.clickedText };
}

async function readOptionalTrimmedFile(filePath) {
  if (!filePath) {
    return "";
  }
  try {
    const raw = await fs.readFile(filePath, "utf8");
    return raw.trim();
  } catch {
    return "";
  }
}

async function fillFirstVisible(page, selectors, value) {
  const match = await firstVisibleLocator(page, selectors);
  if (!match) {
    return null;
  }
  try {
    await match.locator.fill(value);
  } catch {
    await match.locator.click().catch(() => null);
    await match.locator.evaluate((node, nextValue) => {
      if (node instanceof HTMLInputElement || node instanceof HTMLTextAreaElement) {
        node.value = nextValue;
        node.dispatchEvent(new Event("input", { bubbles: true }));
        node.dispatchEvent(new Event("change", { bubbles: true }));
        return;
      }
      if (node instanceof HTMLElement && node.isContentEditable) {
        node.innerText = nextValue;
        node.dispatchEvent(new InputEvent("input", { bubbles: true, data: nextValue }));
      }
    }, value);
  }
  return match.selector;
}

async function fillCsdnTitle(page, title) {
  const selectors = [
    "input[placeholder*='标题']",
    "textarea[placeholder*='标题']",
    "input.article-bar__title",
    ".article-bar__title--input",
    "input",
  ];
  const visibleSelector = await fillFirstVisible(page, selectors, title);
  if (visibleSelector) {
    return visibleSelector;
  }
  const fallbackSelector = await page.evaluate((nextValue) => {
    const candidates = [
      ...document.querySelectorAll(
        "input.article-bar__title, .article-bar__title--input, input[placeholder*='标题'], textarea[placeholder*='标题']",
      ),
    ];
    const target = candidates.find((element) => (
      element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement
    ));
    if (!target) {
      return "";
    }
    const prototype = target instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
    if (descriptor?.set) {
      descriptor.set.call(target, nextValue);
    } else {
      target.value = nextValue;
    }
    target.dispatchEvent(new Event("input", { bubbles: true }));
    target.dispatchEvent(new Event("change", { bubbles: true }));
    target.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true, key: "Enter" }));
    return target.matches("input.article-bar__title") ? "eval:input.article-bar__title" : "eval:title-input-hidden";
  }, title);
  return fallbackSelector || null;
}

function normalizeInlineText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function truncateByChars(value, maxChars) {
  const normalized = String(value || "");
  if (normalized.length <= maxChars) {
    return normalized;
  }
  return normalized.slice(0, Math.max(0, maxChars - 1)).trimEnd() + "…";
}

function normalizeComparableTitle(value) {
  return String(value || "")
    .replace(/\s+/g, "")
    .replace(/[：:|｜\-—_·•·,.，。！？!?（）()【】\[\]<>《》"'“”‘’]/g, "")
    .trim()
    .toLowerCase();
}

function titleMatchScore(targetTitle, candidateTitle) {
  const target = normalizeComparableTitle(targetTitle);
  const candidate = normalizeComparableTitle(candidateTitle);
  if (!target || !candidate) {
    return 0;
  }
  if (target === candidate) {
    return 100;
  }
  if (candidate.includes(target) || target.includes(candidate)) {
    return 80;
  }
  const targetTokens = target.split(/[a-z0-9]+/i).filter(Boolean);
  const candidateTokens = candidate.split(/[a-z0-9]+/i).filter(Boolean);
  const overlap = targetTokens.filter((token) => candidateTokens.includes(token)).length;
  if (overlap > 0) {
    return overlap * 10;
  }
  return 0;
}

function buildFanBroadcastMessage(articleTitle, publishedArticleUrl) {
  const title = truncateByChars(normalizeInlineText(articleTitle), 120);
  const url = normalizeInlineText(publishedArticleUrl);
  const pieces = [];
  if (title) {
    pieces.push("新文来袭！！✨");
    pieces.push(title);
  }
  if (url) {
    pieces.push(url);
  }
  pieces.push("伙伴们走过路过不要错过呀🤞 互相支持！");
  const base = pieces.filter(Boolean).join("\n");
  return truncateByChars(base, 300);
}

function normalizeFanBroadcastAudience(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (!normalized || normalized === "all" || normalized === "全部" || normalized === "全部粉丝") {
    return "all";
  }
  if (normalized === "active" || normalized === "活跃" || normalized === "活跃粉丝") {
    return "active";
  }
  return "all";
}

function fanBroadcastAudienceSpec(audience) {
  const normalized = normalizeFanBroadcastAudience(audience);
  if (normalized === "active") {
    return {
      key: "active",
      display_label: "活跃粉丝",
      label_regex: /活跃粉丝/,
      selectors: [
        "label:has-text('活跃粉丝')",
        "span:has-text('活跃粉丝')",
        "div:has-text('活跃粉丝')",
        "p.fan_item_btn:has-text('活跃粉丝')",
      ],
    };
  }
  return {
    key: "all",
    display_label: "全部粉丝",
    label_regex: /全部粉丝|所有粉丝/,
    selectors: [
      "label:has-text('全部粉丝')",
      "span:has-text('全部粉丝')",
      "div:has-text('全部粉丝')",
      "label:has-text('所有粉丝')",
      "span:has-text('所有粉丝')",
      "p.fan_item_btn:has-text('全部粉丝')",
    ],
  };
}

async function clickConsentCheckbox(page) {
  await clickFirstVisible(page, [
    "label:has-text('同意')",
    "label:has-text('已阅读')",
    "label:has-text('隐私')",
    "input[type='checkbox']",
  ]).catch(() => null);
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
    Object.defineProperty(navigator, "maxTouchPoints", {
      get: () => 0,
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

async function applyStateFileCookies(context, stateFile) {
  if (!stateFile) {
    return 0;
  }
  try {
    const parsed = await readJson(stateFile);
    const cookies = Array.isArray(parsed?.cookies) ? parsed.cookies : [];
    if (!cookies.length) {
      return 0;
    }
    await context.addCookies(cookies);
    return cookies.length;
  } catch {
    return 0;
  }
}

async function launchCsdnContext(options) {
  const { headless, stateFile, preferPersistent = false } = options;
  const persistent = preferPersistent && parseBool(process.env.CSDN_PERSISTENT_BROWSER, true);
  const launchOptions = {
    headless,
    locale: DEFAULT_LOCALE,
    timezoneId: DEFAULT_TIMEZONE,
    userAgent: DEFAULT_USER_AGENT,
    viewport: null,
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

  if (persistent) {
    const profileDir = browserProfileDir();
    await clearStaleChromiumSingletonLocks(profileDir);
    const context = await chromium.launchPersistentContext(profileDir, launchOptions);
    await applyStealthInitScript(context);
    await applyStateFileCookies(context, stateFile);
    const page = context.pages()[0] || (await context.newPage());
    return {
      browser: null,
      context,
      page,
      persistent,
      profileDir,
    };
  }

  const browser = await chromium.launch(launchOptions);
  const contextOptions = {
    locale: DEFAULT_LOCALE,
    timezoneId: DEFAULT_TIMEZONE,
    userAgent: DEFAULT_USER_AGENT,
    viewport: null,
    extraHTTPHeaders: {
      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    },
  };
  if (stateFile) {
    contextOptions.storageState = stateFile;
  }
  const context = await browser.newContext(contextOptions);
  await applyStealthInitScript(context);
  const page = await context.newPage();
  return {
    browser,
    context,
    page,
    persistent,
    profileDir: browserProfileDir(),
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

async function extractPublishedArticleUrl(page) {
  const candidates = [
    "a:has-text('查看文章')",
    "a:has-text('阅读全文')",
    "a[href*='blog.csdn.net']",
  ];
  for (const selector of candidates) {
    const locator = page.locator(selector).first();
    try {
      if (await locator.count()) {
        const href = await locator.getAttribute("href");
        if (href && /blog\.csdn\.net\/.+\/article\/details\//.test(href)) {
          return href;
        }
      }
    } catch {
      continue;
    }
  }

  const extracted = await page.evaluate(() => {
    const links = [...document.querySelectorAll("a[href]")];
    const target = links.find((item) => {
      const href = item.getAttribute("href") || "";
      return /blog\.csdn\.net\/.+\/article\/details\//.test(href);
    });
    return target?.getAttribute("href") || "";
  }).catch(() => "");
  return extracted || "";
}

async function collectPublishedArticleCandidates(page) {
  const anchorCandidates = await page.evaluate(() => {
    function normalizeText(value) {
      return String(value || "").replace(/\s+/g, " ").trim();
    }

    function extractContextText(anchor) {
      const candidates = [];
      let node = anchor;
      for (let depth = 0; depth < 8 && node; depth += 1) {
        const text = normalizeText(node.innerText || node.textContent || "");
        if (text) {
          candidates.push(text);
        }
        node = node.parentElement;
      }
      candidates.sort((left, right) => right.length - left.length);
      return candidates[0] || "";
    }

    return Array.from(document.querySelectorAll("a[href*='blog.csdn.net']"))
      .map((anchor) => {
        const href = String(anchor.getAttribute("href") || "").trim();
        const title = normalizeText(
          anchor.getAttribute("title")
          || extractContextText(anchor)
          || anchor.innerText
          || anchor.parentElement?.innerText
          || ""
        );
        return { href, title };
      })
      .filter((item) => /blog\.csdn\.net\/.+\/article\/details\//.test(item.href));
  })
    .catch(() => []);

  const pageText = await page.evaluate(() => String(document.body?.innerText || "")).catch(() => "");
  const textCandidates = [...String(pageText || "").matchAll(/https?:\/\/blog\.csdn\.net\/[^\s)]*\/article\/details\/[^\s)]+/g)]
    .map((match) => ({
      href: String(match[0] || "").trim(),
      title: "",
    }));

  const merged = [];
  const seen = new Set();
  for (const item of [...anchorCandidates, ...textCandidates]) {
    const href = String(item?.href || "").trim();
    if (!href || seen.has(href)) {
      continue;
    }
    seen.add(href);
    merged.push({
      href,
      title: normalizeInlineText(item?.title || ""),
    });
  }
  return merged;
}

async function resolvePublishedArticleUrl(page, articleTitle, timeoutMs = 45000) {
  const title = normalizeInlineText(articleTitle);
  const urlsToInspect = [page.url(), ...ARTICLE_MANAGE_URL_CANDIDATES];
  let bestCandidate = null;

  for (const candidateUrl of urlsToInspect) {
    const targetUrl = String(candidateUrl || "").trim();
    if (!targetUrl) {
      continue;
    }
    if (page.url() !== targetUrl) {
      await gotoWithAbortTolerance(page, targetUrl, {
        timeout: Math.min(timeoutMs, 20000),
        waitUntil: "domcontentloaded",
      });
      await page.waitForSelector(".article-list-item-mp, .article_manage_list", { timeout: 5000 }).catch(() => null);
      await page.waitForTimeout(5000);
    }

    const candidates = await collectPublishedArticleCandidates(page);
    for (const candidate of candidates) {
      const score = titleMatchScore(title, candidate.title);
      if (!bestCandidate || score > bestCandidate.score) {
        bestCandidate = {
          ...candidate,
          score,
          source_page: page.url(),
        };
      }
    }
    if (bestCandidate && bestCandidate.score >= 80) {
      break;
    }
  }

  if (bestCandidate?.href && (bestCandidate.score || 0) >= 80) {
    return {
      found: true,
      url: bestCandidate.href,
      matched_title: bestCandidate.title,
      resolution_source: bestCandidate.source_page || "",
      score: bestCandidate.score || 0,
    };
  }
  return {
    found: false,
    url: "",
    matched_title: "",
    resolution_source: "",
    score: 0,
  };
}

async function fillEditor(page, content) {
  const textareaSelectors = [
    "textarea.editor-box",
    ".editor-box textarea",
    "textarea[placeholder*='内容']",
    "textarea",
  ];
  const editableSelectors = [
    ".bytemd-editor [contenteditable='true']",
    ".editor [contenteditable='true']",
    "[contenteditable='true']",
  ];

  const textarea = await firstVisibleLocator(page, textareaSelectors);
  if (textarea) {
    await textarea.locator.click().catch(() => null);
    await textarea.locator.evaluate((node, text) => {
      if (!(node instanceof HTMLTextAreaElement || node instanceof HTMLInputElement)) {
        return;
      }
      node.value = text;
      node.dispatchEvent(new Event("input", { bubbles: true }));
      node.dispatchEvent(new Event("change", { bubbles: true }));
    }, content);
    return { mode: "textarea", selector: textarea.selector };
  }

  const editable = await firstVisibleLocator(page, editableSelectors);
  if (editable) {
    await editable.locator.click();
    await editable.locator.evaluate((node, text) => {
      node.textContent = text;
    }, content);
    return { mode: "contenteditable", selector: editable.selector };
  }

  throw new Error("Could not find a visible CSDN editor surface.");
}

function markdownHasExternalImages(content) {
  return /!\[[^\]]*\]\(https?:\/\/[^)\s]+\)/i.test(String(content || ""));
}

async function waitForExternalImageTransfer(page, content) {
  if (!markdownHasExternalImages(content)) {
    return {
      waited: false,
      placeholderPresent: false,
      stable: true,
    };
  }
  await page.waitForTimeout(10000);
  const deadline = Date.now() + 60000;
  let placeholderPresent = false;
  while (Date.now() < deadline) {
    const bodyText = await page.locator("body").innerText().catch(() => "");
    placeholderPresent = bodyText.includes("外链图片转存中");
    if (!placeholderPresent) {
      return {
        waited: true,
        placeholderPresent: false,
        stable: true,
      };
    }
    await page.waitForTimeout(1000);
  }
  return {
    waited: true,
    placeholderPresent,
    stable: !placeholderPresent,
  };
}

async function fileExists(filePath) {
  if (!filePath) {
    return false;
  }
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function setInputFilesOnMatchingInput(page, selectors, filePath) {
  for (const selector of selectors) {
    const locator = page.locator(selector);
    const count = await locator.count();
    for (let index = count - 1; index >= 0; index -= 1) {
      const candidate = locator.nth(index);
      try {
        await candidate.setInputFiles(filePath);
        return `${selector}[${index}]`;
      } catch {
        continue;
      }
    }
  }
  return "";
}

async function uploadCoverImage(page, payload, args) {
  const bannerAsset = payload?.banner_asset || {};
  const sourcePath = String(bannerAsset.source_path || "").trim();
  const result = {
    status: "skipped",
    reason: "no_source_path",
    source_path: sourcePath,
    add_cover_selector: "",
    local_upload_selector: "",
    file_input_selector: "",
    confirm_upload_selector: "",
    preview_selector: "",
  };

  if (!sourcePath) {
    return result;
  }
  if (!(await fileExists(sourcePath))) {
    return {
      ...result,
      reason: "source_path_missing",
    };
  }

  result.add_cover_selector =
    (await clickFirstVisible(page, [
      "button:has-text('添加封面')",
      "span:has-text('添加封面')",
      "div:has-text('添加封面')",
    ]))
    || (await clickByEvaluate(page, [
      ".container-coverimage-box .preview-box",
      ".form-tag-box .container-coverimage-box",
      ".cover-upload-box",
    ]))
    || "";
  await page.waitForTimeout(600);

  result.file_input_selector = await setInputFilesOnMatchingInput(page, [
    ".cover-upload-box input[type='file']",
    ".el-upload input[type='file'][accept*='.png']",
    ".el-upload__input[accept*='.png']",
    ".el-upload__input[accept*='.jpg']",
    "input[type='file'][accept*='image']",
    "input[type='file'][accept*='.png']",
  ], sourcePath);

  if (!result.file_input_selector) {
    result.local_upload_selector =
      (await clickByEvaluate(page, [
        ".cover-upload-box .upload-img-box",
        ".el-upload .upload-img-box",
        ".cover-upload-box",
      ]))
      || (await clickFirstVisible(page, [
        "button:has-text('从本地上传')",
        "p:has-text('从本地上传')",
        "div:has-text('从本地上传')",
      ]))
      || "";
    await page.waitForTimeout(400);
    result.file_input_selector = await setInputFilesOnMatchingInput(page, [
      ".cover-upload-box input[type='file']",
      ".el-upload input[type='file'][accept*='.png']",
      ".el-upload__input[accept*='.png']",
      ".el-upload__input[accept*='.jpg']",
      "input[type='file'][accept*='image']",
      "input[type='file'][accept*='.png']",
    ], sourcePath);
  }

  if (!result.file_input_selector) {
    return {
      ...result,
      status: "skipped",
      reason: "cover_file_input_not_found",
    };
  }

  await page.waitForTimeout(2000);
  result.preview_selector =
    (await firstVisibleLocator(page, [
      "text=封面图预览",
      ".vicp-preview-item",
      ".vicp-crop-right",
      ".vue-image-crop-upload[aria-hidden='false']",
    ]))?.selector || "";

  result.confirm_upload_selector =
    (await clickFirstVisible(page, [
      "div:has-text('确认上传')",
      "button:has-text('确认上传')",
      "span:has-text('确认上传')",
    ]))
    || (await clickByEvaluate(page, [
      ".vicp-operate-btn",
      ".vicp-operate .vicp-operate-btn",
    ]))
    || "";

  if (result.confirm_upload_selector) {
    await page.waitForTimeout(1800);
  }

  result.preview_selector =
    result.preview_selector
    || (await firstVisibleLocator(page, [
      ".container-coverimage-box .preview-box img[src]",
      ".preview-box img[src]",
      ".container-coverimage-box .preview",
    ]))?.selector
    || "";

  return {
    ...result,
    status: "uploaded",
    reason: "",
  };
}

async function enableFollowOnlyVisibility(page) {
  let selector = "";
  await page.evaluate(() => {
    document.querySelectorAll(".mark-mask-box-div, .mask.transpatent").forEach((node) => {
      if (node instanceof HTMLElement) {
        node.style.pointerEvents = "none";
        node.style.display = "none";
        node.setAttribute("data-aimagician-suppressed", "true");
      }
    });
  }).catch(() => null);

  try {
    const applied = await page.evaluate(() => {
      const input = document.querySelector("#needfans");
      if (!(input instanceof HTMLInputElement)) {
        return false;
      }
      input.checked = true;
      input.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      const label = document.querySelector("label[for='needfans']");
      if (label instanceof HTMLElement) {
        label.click();
      }
      return input.checked === true;
    });
    if (applied) {
      selector = "eval:input#needfans";
    }
  } catch {
    selector = "";
  }
  const fansRadio = page.locator("input#needfans").first();
  try {
    if (selector) {
      await page.waitForTimeout(300);
    } else if (await fansRadio.count()) {
      await fansRadio.check({ force: true });
      selector = "input#needfans";
    }
  } catch {
    selector = selector || "";
  }
  if (!selector) {
    if (await fansRadio.count()) {
      await fansRadio.check({ force: true });
      selector = "input#needfans";
    }
  }
  if (!selector) {
    selector =
      (await clickFirstVisible(page, [
        "label[for='needfans']",
        "input#needfans",
      ]))
      || "";
  }
  if (!selector) {
    selector =
    (await clickFirstVisible(page, [
      "label:has-text('粉丝可见')",
      "span:has-text('粉丝可见')",
      "div:has-text('粉丝可见')",
      "label:has-text('仅关注可见')",
      "label:has-text('仅粉丝可见')",
      "span:has-text('仅关注可见')",
      "span:has-text('仅粉丝可见')",
      "div:has-text('仅关注可见')",
      "div:has-text('仅粉丝可见')",
    ]))
    || (await clickByEvaluate(page, [
      "[class*='fans'][class*='visible']",
      "[class*='fans'][class*='radio']",
      "[class*='follow'][class*='visible']",
      "[class*='fans'][class*='visible']",
      "[class*='private'][class*='switch']",
    ]))
    || "";
  }
  await page.waitForTimeout(600);
  const state = await page.evaluate(() => {
    const needFans = document.querySelector("#needfans");
    const text = String(document.body?.innerText || "").replace(/\s+/g, " ");
    const visibilityNodes = Array.from(document.querySelectorAll("label, span, div, li, p"))
      .filter((node) => /粉丝可见|仅关注可见|仅粉丝可见|公开可见/.test(String(node.innerText || "")))
      .map((node) => {
        const raw = String(node.innerText || "").replace(/\s+/g, " ").trim();
        const className = String(node.getAttribute("class") || "");
        const ariaChecked = String(node.getAttribute("aria-checked") || "");
        const parentClass = String(node.parentElement?.getAttribute("class") || "");
        return {
          text: raw,
          className,
          parentClass,
          ariaChecked,
        };
      });
    const hasFansVisible = /粉丝可见/.test(text);
    const hasPublicVisible = /公开可见/.test(text);
    const fansChecked = Boolean(needFans && "checked" in needFans && needFans.checked === true);
    const activeFans = visibilityNodes.some((item) => {
      if (!/粉丝可见|仅关注可见|仅粉丝可见/.test(item.text)) {
        return false;
      }
      const combined = `${item.className} ${item.parentClass} ${item.ariaChecked}`.toLowerCase();
      return /checked|active|selected|current|is-checked/.test(combined) || item.ariaChecked === "true";
    });
    return {
      hasFansVisible,
      hasPublicVisible,
      fansChecked,
      activeFans,
      visibilityNodes: visibilityNodes.slice(0, 20),
    };
  }).catch(() => false);
  const enabled = Boolean(state && (state.fansChecked || state.activeFans || (selector && state.hasFansVisible && !state.hasPublicVisible)));
  return {
    attempted: true,
    selector,
    enabled,
    state,
    reason: enabled ? "" : (selector ? "follow_only_unconfirmed" : "follow_only_toggle_not_found"),
  };
}

async function extractValidTrafficCoupons(page) {
  return await page.evaluate(() => Array.from(document.querySelectorAll(".traffic-cont-combination[data-is-valid]"))
    .map((node, index) => ({
      index,
      coupon_id: String(node.getAttribute("data-is-valid") || "").trim(),
      coupon_name: String(node.querySelector("dd span")?.textContent || "").trim(),
      exposure: String(node.querySelector(".exposure .num")?.textContent || "").trim(),
      text: String(node.innerText || "").replace(/\s+/g, " ").trim().slice(0, 200),
      button_text: String(node.querySelector(".btn")?.textContent || "").replace(/\s+/g, " ").trim(),
    }))
    .filter((item) => item.coupon_id))
    .catch(() => []);
}

async function chooseTrafficDialogArticle(page, articleMeta = {}) {
  const articleTitle = normalizeInlineText(articleMeta.title);
  const candidates = await page.evaluate(() => Array.from(document.querySelectorAll(".traffic-dialog-item"))
    .map((node, index) => ({
      index,
      title: String(node.querySelector(".title .text")?.textContent || "").replace(/\s+/g, " ").trim(),
      desc: String(node.querySelector(".desc")?.textContent || "").replace(/\s+/g, " ").trim(),
    }))
    .filter((item) => item.title))
    .catch(() => []);

  if (!candidates.length) {
    return {
      selector: "",
      chosen: null,
      candidates,
      reason: "traffic_coupon_no_promotable_articles_visible",
    };
  }

  let chosen = null;
  if (articleTitle) {
    chosen = candidates.find((item) => item.title.includes(articleTitle) || articleTitle.includes(item.title)) || null;
  }
  if (!chosen) {
    chosen = candidates[0];
  }

  const selector =
    (await clickFirstVisible(page, [
      `.traffic-dialog-item:has(.title .text:text-is('${chosen.title}'))`,
    ]))
    || (await clickByEvaluate(page, [
      `.traffic-dialog-item:nth-child(${chosen.index + 1})`,
    ]))
    || "";

  return {
    selector,
    chosen,
    candidates,
    reason: selector ? "" : "traffic_coupon_article_select_failed",
  };
}

async function applyTrafficCouponById(page, couponId, articleMeta = {}, args = {}) {
  await gotoWithAbortTolerance(page, TRAFFIC_MANAGE_URL, {
    timeout: 45000,
    waitUntil: "domcontentloaded",
  });
  await page.waitForTimeout(1800);
  const finalUrl = page.url();
  const onTrafficPage = finalUrl.includes("/mp_blog/manage/traffic");
  if (!onTrafficPage) {
    return {
      coupon_id: String(couponId || ""),
      attempted: false,
      open_selector: "",
      use_selector: "",
      article_selector: "",
      confirm_selector: "",
      coupon_text: "",
      applied: false,
      final_url: finalUrl,
      reason: "traffic_coupon_page_not_reached",
    };
  }
  const couponMeta = await page.evaluate((targetId) => {
    const items = Array.from(document.querySelectorAll(".traffic-cont-combination[data-is-valid]"));
    const target = items.find((item) => String(item.getAttribute("data-is-valid") || "").trim() === String(targetId || "").trim());
    if (!target) {
      return { text: "", name: "", exposure: "", hasButton: false, couponId: String(targetId || "").trim() };
    }
    return {
      couponId: String(target.getAttribute("data-is-valid") || "").trim(),
      text: String(target.innerText || "").replace(/\s+/g, " ").trim().slice(0, 160),
      name: String(target.querySelector("dd span")?.textContent || "").trim(),
      exposure: String(target.querySelector(".exposure .num")?.textContent || "").trim(),
      hasButton: Boolean(target.querySelector(".btn")),
    };
  }, couponId).catch(() => ({ text: "", name: "", exposure: "", hasButton: false, couponId: String(couponId || "").trim() }));
  if (!couponMeta.hasButton) {
    return {
      coupon_id: couponMeta.couponId || String(couponId || ""),
      attempted: false,
      open_selector: "",
      use_selector: "",
      article_selector: "",
      confirm_selector: "",
      coupon_text: couponMeta.text || "",
      coupon_name: couponMeta.name || "",
      exposure: couponMeta.exposure || "",
      applied: false,
      final_url: finalUrl,
      reason: "traffic_coupon_entry_not_found",
    };
  }
  const preUseArtifacts = await capturePageArtifacts(page, args, "csdn-traffic-before-use");

  const useSelector = await clickByEvaluate(page, [
      `.traffic-cont-combination[data-is-valid="${couponMeta.couponId}"] .btn`,
      `.traffic-cont-combination[data-is-valid="${couponMeta.couponId}"] p.btn`,
    ])
    || "";
  await page.waitForTimeout(5000);
  const postUseArtifacts = await capturePageArtifacts(page, args, "csdn-traffic-after-use-click");

  const selectedArticle = await chooseTrafficDialogArticle(page, articleMeta);
  const articleSelector = selectedArticle.selector || "";
  await page.waitForTimeout(800);
  const postArticleArtifacts = await capturePageArtifacts(page, args, "csdn-traffic-after-article-select");

  const confirmSelector =
    (await clickFirstVisible(page, [
      ".el_mcm-overlay-dialog .traffic-dialog-btn-box .success",
      ".el_mcm-overlay-dialog p.success:has-text('确定')",
      ".el_mcm-overlay-dialog button:has-text('确定')",
      ".el_mcm-overlay-dialog span:has-text('确定')",
    ]))
    || (await clickByEvaluate(page, [
      ".el_mcm-overlay-dialog .traffic-dialog-btn-box .success",
      ".el_mcm-overlay-dialog p.success",
    ]))
    || "";
  await page.waitForTimeout(1200);
  const postConfirmArtifacts = await capturePageArtifacts(page, args, "csdn-traffic-after-confirm");

  const couponState = await page.evaluate(() => {
    const text = String(document.body?.innerText || "").replace(/\s+/g, " ");
    const overlayVisible = Boolean(document.querySelector(".el_mcm-overlay-dialog"));
    const toastTexts = Array.from(document.querySelectorAll(".el-message, .el-notification, .toast, [role='alert'], .message, .notice"))
      .map((node) => String(node.textContent || "").replace(/\s+/g, " ").trim())
      .filter(Boolean)
      .slice(0, 10);
    const selectedArticleTexts = Array.from(document.querySelectorAll(".article-item, .content-item, .select-item, .article-list li, .post-item"))
      .map((node) => String(node.textContent || "").replace(/\s+/g, " ").trim())
      .filter(Boolean)
      .slice(0, 10);
    return {
      success: /使用成功|投放成功|已使用|已投放/.test(text),
      overlayVisible,
      toastTexts,
      selectedArticleTexts,
    };
  }).catch(() => ({ success: false, overlayVisible: true, toastTexts: [], selectedArticleTexts: [] }));
  await gotoWithAbortTolerance(page, TRAFFIC_MANAGE_URL, {
    timeout: 45000,
    waitUntil: "domcontentloaded",
  });
  await page.waitForTimeout(1500);
  const refreshedCoupons = await extractValidTrafficCoupons(page);
  const couponStillAvailable = refreshedCoupons.some((item) => item.coupon_id === couponMeta.couponId && /去使用/.test(item.button_text));
  const applied = Boolean(
    couponState.success
      || couponState.toastTexts.some((item) => /成功|已使用|已投放/.test(item))
      || (!couponState.overlayVisible && articleSelector && !couponStillAvailable)
      || (confirmSelector && !couponStillAvailable)
  );

  return {
    coupon_id: couponMeta.couponId || String(couponId || ""),
    attempted: true,
    open_selector: "direct_url",
    use_selector: useSelector,
    article_selector: articleSelector,
    confirm_selector: confirmSelector,
    coupon_text: couponMeta.text || "",
    coupon_name: couponMeta.name || "",
    exposure: couponMeta.exposure || "",
    applied,
    final_url: page.url(),
    page_artifacts: {
      before_use: preUseArtifacts,
      after_use_click: postUseArtifacts,
      after_article_select: postArticleArtifacts,
      after_confirm: postConfirmArtifacts,
    },
    coupon_state: couponState,
    selected_article: selectedArticle,
    refreshed_coupons: refreshedCoupons,
    reason: useSelector
      ? (selectedArticle.reason || (applied ? "" : "traffic_coupon_applied_unconfirmed"))
      : "traffic_coupon_use_not_found",
  };
}

async function applyTrafficCoupons(page, articleMeta = {}, args = {}) {
  await gotoWithAbortTolerance(page, TRAFFIC_MANAGE_URL, {
    timeout: 45000,
    waitUntil: "domcontentloaded",
  });
  await page.waitForTimeout(1800);
  const coupons = await extractValidTrafficCoupons(page);
  const results = [];
  const usableCoupons = coupons.filter((item) => /去使用/.test(item.button_text));
  const skippedCoupons = coupons.filter((item) => !/去使用/.test(item.button_text));
  for (const coupon of usableCoupons) {
    const result = await applyTrafficCouponById(page, coupon.coupon_id, articleMeta, args);
    results.push(result);
  }
  for (const coupon of skippedCoupons) {
    results.push({
      coupon_id: coupon.coupon_id,
      attempted: false,
      applied: false,
      coupon_name: coupon.coupon_name,
      exposure: coupon.exposure,
      reason: "traffic_coupon_not_usable",
      status: "skipped",
      current_button_text: coupon.button_text,
    });
  }
  const appliedCount = results.filter((item) => item.applied).length;
  const attemptedCount = results.filter((item) => item.attempted).length;
  const failedCount = results.filter((item) => item.attempted && !item.applied).length;
  const skippedCount = results.filter((item) => !item.attempted).length;
  return {
    attempted: true,
    final_url: page.url(),
    detected_count: coupons.length,
    usable_count: usableCoupons.length,
    attempted_count: attemptedCount,
    applied_count: appliedCount,
    failed_count: failedCount,
    skipped_count: skippedCount,
    coupons,
    results,
  };
}

async function extractFanBroadcastState(page) {
  return await page.evaluate(() => {
    const body = String(document.body?.innerText || "").replace(/\s+/g, " ").trim();
    const weeklyMatch = body.match(/本周还可群发[^0-9]*(\d+)\s*次/);
    const groups = Array.from(document.querySelectorAll(".fan-content-top .fan_item")).map((item) => {
      const groupLabel = String(item.querySelector("span")?.textContent || "")
        .replace(/\s+/g, " ")
        .trim()
        .replace(/[:：]$/, "");
      const buttons = Array.from(item.querySelectorAll(".fan_item_btn")).map((button) => {
        const label = String(button.textContent || "").replace(/\s+/g, " ").trim();
        const tooltipId = String(button.getAttribute("aria-describedby") || "").trim();
        const tooltipText = tooltipId
          ? String(document.getElementById(tooltipId)?.textContent || "").replace(/\s+/g, " ").trim()
          : "";
        const parentText = String(button.closest(".fan_item_popover, .fan_item, .el-popover__reference-wrapper")?.textContent || "")
          .replace(/\s+/g, " ")
          .trim();
        const disabledReason = tooltipText || (/群发.*上限/.test(parentText) ? parentText : "");
        return {
          label,
          active: Boolean(button.classList.contains("is_active")),
          disabled: Boolean(button.classList.contains("disabled")),
          disabled_reason: disabledReason,
          class_name: button.className,
          tooltip_id: tooltipId,
        };
      });
      return {
        group_label: groupLabel,
        buttons,
        text: String(item.textContent || "").replace(/\s+/g, " ").trim(),
      };
    });
    const audienceGroup = groups.find((item) => /群发对象/.test(item.group_label)) || null;
    const channelGroup = groups.find((item) => /发送通道/.test(item.group_label)) || null;
    return {
      body_excerpt: body.slice(0, 2000),
      weekly_remaining_count: weeklyMatch ? Number(weeklyMatch[1]) : null,
      groups,
      audiences: audienceGroup?.buttons || [],
      channels: channelGroup?.buttons || [],
    };
  }).catch(() => ({
    body_excerpt: "",
    weekly_remaining_count: null,
    groups: [],
    audiences: [],
    channels: [],
  }));
}

async function selectFanBroadcastAudience(page, audienceSpec) {
  const evalSelector = await page.evaluate((label) => {
    const target = Array.from(document.querySelectorAll(".fan-content-top .fan_item_btn"))
      .find((element) => String(element.textContent || "").replace(/\s+/g, " ").trim() === label);
    if (!target) {
      return "";
    }
    target.click();
    return `eval:fan_item_btn:${label}`;
  }, audienceSpec.display_label).catch(() => "");
  if (evalSelector) {
    return evalSelector;
  }
  const selectorClick =
    (await clickFirstVisible(page, audienceSpec.selectors))
    || "";
  return selectorClick;
}

async function inspectSentFanBroadcastHistory(page, articleTitle = "") {
  const sentTabSelector =
    (await clickFirstVisible(page, [
      "li:has-text('已发送粉丝群发')",
      "a:has-text('已发送粉丝群发')",
      "span:has-text('已发送粉丝群发')",
      "p:has-text('已发送粉丝群发')",
    ]))
    || "";
  await page.waitForTimeout(1800);
  const state = await page.evaluate((title) => {
    const body = String(document.body?.innerText || "").replace(/\s+/g, " ").trim();
    return {
      body_excerpt: body.slice(0, 3000),
      found_title: title ? body.includes(title) : false,
    };
  }, articleTitle).catch(() => ({ body_excerpt: "", found_title: false }));
  return {
    sent_tab_selector: sentTabSelector,
    ...state,
  };
}

async function triggerFanBroadcastOnce(page, publishedArticleUrl = "", articleTitle = "", audience = "all") {
  const audienceSpec = fanBroadcastAudienceSpec(audience);
  await gotoWithAbortTolerance(page, FAN_BROADCAST_URL, {
    timeout: 45000,
    waitUntil: "domcontentloaded",
  });
  await page.waitForTimeout(1800);
  const finalUrl = page.url();
  const onFanPage = finalUrl.includes("/fanService/fanadd");
  if (!onFanPage) {
    return {
      attempted: false,
      open_selector: "",
      audience_selector: "",
      message_selector: "",
      url_selector: "",
      submit_selector: "",
      submitted: false,
      final_url: finalUrl,
      message_text: "",
      reason: "fan_broadcast_entry_not_found",
    };
  }

  const initialState = await extractFanBroadcastState(page);

  const audienceSelector =
    (await selectFanBroadcastAudience(page, audienceSpec))
    || (await clickByEvaluate(page, [
      "[class*='all'][class*='fans']",
      "[class*='all'][class*='member']",
    ]))
    || "";
  await page.waitForTimeout(500);
  const selectedState = await extractFanBroadcastState(page);
  const selectedAudience = (selectedState.audiences || []).find((item) => item.active && audienceSpec.label_regex.test(item.label))
    || (selectedState.audiences || []).find((item) => audienceSpec.label_regex.test(item.label))
    || null;
  if (!selectedAudience?.active && selectedAudience?.disabled) {
    return {
      attempted: false,
      desired_audience: audienceSpec.key,
      desired_audience_label: audienceSpec.display_label,
      open_selector: "direct_url",
      audience_selector: audienceSelector,
      message_selector: "",
      url_selector: "",
      submit_selector: "",
      confirm_selector: "",
      submitted: false,
      final_url: page.url(),
      message_text: "",
      body_excerpt: selectedState.body_excerpt || initialState.body_excerpt || "",
      initial_state: initialState,
      selected_state: selectedState,
      selected_audience: selectedAudience,
      reason: "fan_broadcast_audience_limit_reached",
    };
  }
  if (!selectedAudience?.active) {
    return {
      attempted: false,
      desired_audience: audienceSpec.key,
      desired_audience_label: audienceSpec.display_label,
      open_selector: "direct_url",
      audience_selector: audienceSelector,
      message_selector: "",
      url_selector: "",
      submit_selector: "",
      confirm_selector: "",
      submitted: false,
      final_url: page.url(),
      message_text: "",
      body_excerpt: selectedState.body_excerpt || initialState.body_excerpt || "",
      initial_state: initialState,
      selected_state: selectedState,
      selected_audience: selectedAudience,
      reason: "fan_broadcast_audience_selection_not_confirmed",
    };
  }

  const messageText = buildFanBroadcastMessage(articleTitle, publishedArticleUrl);
  const messageSelector =
    (await fillFirstVisible(page, [
      "textarea[placeholder*='请输入']",
      "textarea[placeholder*='内容']",
      "textarea[placeholder*='群发']",
      "textarea",
      "div[contenteditable='true']",
    ], messageText))
    || "";

  let urlSelector = "";
  if (publishedArticleUrl) {
    urlSelector =
      (await fillFirstVisible(page, [
        "input[placeholder*='链接']",
        "input[placeholder*='文章地址']",
        "textarea[placeholder*='链接']",
      ], publishedArticleUrl))
      || "";
  }

  const submitSelector =
    (await clickFirstVisible(page, [
      "button:has-text('群发')",
      "button:has-text('发送')",
      "button:has-text('发布')",
      "span:has-text('群发')",
      "span:has-text('发送')",
    ]))
    || "";
  await page.waitForTimeout(1200);

  const confirmSelector =
    (await clickFirstVisible(page, [
      "button:has-text('确认群发')",
      "button:has-text('确认发送')",
      "button:has-text('确认')",
      "span:has-text('确认群发')",
      "span:has-text('确认发送')",
      "span:has-text('确认')",
    ]))
    || "";
  await page.waitForTimeout(1800);

  const postSubmitState = await extractFanBroadcastState(page);
  const submissionState = await page.evaluate(() => {
    const text = String(document.body?.innerText || "").replace(/\s+/g, " ");
    return {
      success: /发送成功|群发成功|提交成功/.test(text),
      body_excerpt: text.slice(0, 2000),
    };
  }).catch(() => ({ success: false, body_excerpt: "" }));
  const sentHistory = await inspectSentFanBroadcastHistory(page, articleTitle);
  const submitted = Boolean(submissionState.success || sentHistory.found_title);

  return {
    attempted: true,
    desired_audience: audienceSpec.key,
    desired_audience_label: audienceSpec.display_label,
    open_selector: "direct_url",
    audience_selector: audienceSelector,
    message_selector: messageSelector,
    url_selector: urlSelector,
    submit_selector: submitSelector,
    confirm_selector: confirmSelector,
    submitted,
    final_url: page.url(),
    message_text: messageText,
    body_excerpt: sentHistory.body_excerpt || submissionState.body_excerpt,
    initial_state: initialState,
    selected_state: selectedState,
    post_submit_state: postSubmitState,
    sent_history: sentHistory,
    reason: submitSelector
      ? (submitted ? "" : "fan_broadcast_unconfirmed")
      : "fan_broadcast_submit_not_found",
  };
}

function shouldFallbackFanBroadcast(result) {
  const reason = String(result?.reason || "");
  return [
    "fan_broadcast_audience_limit_reached",
    "fan_broadcast_audience_selection_not_confirmed",
    "fan_broadcast_submit_not_found",
    "fan_broadcast_unconfirmed",
  ].includes(reason);
}

async function triggerFanBroadcast(page, publishedArticleUrl = "", articleTitle = "", audience = "all") {
  const normalizedAudience = normalizeFanBroadcastAudience(audience);
  const primary = await triggerFanBroadcastOnce(page, publishedArticleUrl, articleTitle, normalizedAudience);
  if (primary.submitted || normalizedAudience !== "all" || !shouldFallbackFanBroadcast(primary)) {
    return primary;
  }
  const fallback = await triggerFanBroadcastOnce(page, publishedArticleUrl, articleTitle, "active");
  return {
    ...fallback,
    fallback_from_audience: "all",
    fallback_attempted: true,
    primary_result: primary,
    reason: fallback.submitted ? "" : (fallback.reason || "fan_broadcast_active_fallback_unconfirmed"),
  };
}

function normalizedTags(tags) {
  return [...new Set((tags || [])
    .map((tag) => String(tag || "").trim())
    .filter(Boolean))]
    .slice(0, 3);
}

async function completePublishModal(page, payload, args) {
  const result = {
    tagPanelSelector: "",
    tagInputSelector: "",
    tagsApplied: [],
    coverUpload: null,
    summarySelector: "",
    followOnly: null,
    activitySelector: "",
    activityOptionSelector: "",
    activityOptionText: "",
    topicSelector: "",
    topicOptionSelector: "",
    topicOptionText: "",
    finalPublishSelector: "",
  };

  await checkpointProgress(args, "publish_modal_enter", {
    final_url: page.url(),
    page_title: await page.title(),
  });

  result.tagPanelSelector =
    (await clickFirstVisible(page, [
      "text=添加文章标签",
      "span:has-text('添加文章标签')",
      "div:has-text('添加文章标签')",
    ])) || "";

  await checkpointProgress(args, "publish_modal_tag_panel", {
    tag_panel_selector: result.tagPanelSelector,
  });

  if (result.tagPanelSelector) {
    await page.waitForTimeout(1200);
    const tags = normalizedTags(payload.tags);
    for (const tag of tags) {
      const tagInputSelector =
        (await fillFirstVisible(page, [
          "input[placeholder*='Enter键入可添加自定义标签']",
          "input[placeholder*='添加自定义标签']",
          "input[placeholder*='文字搜索']",
        ], tag)) || "";
      if (!tagInputSelector) {
        break;
      }
      result.tagInputSelector = result.tagInputSelector || tagInputSelector;
      await page.keyboard.press("Enter");
      result.tagsApplied.push(tag);
      await page.waitForTimeout(500);
    }
  }

  await checkpointProgress(args, "publish_modal_tags_applied", {
    tags_applied: result.tagsApplied,
    tag_input_selector: result.tagInputSelector,
  });

  result.coverUpload = await uploadCoverImage(page, payload, args);
  await checkpointProgress(args, "publish_modal_cover_uploaded", {
    cover_upload: result.coverUpload,
  });

  result.summarySelector =
    (await fillFirstVisible(page, [
      "textarea[placeholder*='本内容会在各展现列表中展示']",
      "textarea[placeholder*='默认提取正文前256个字']",
    ], payload.summary || payload.description || "")) || "";

  await page.waitForTimeout(1000);
  await checkpointProgress(args, "publish_modal_summary_filled", {
    summary_selector: result.summarySelector,
  });

  result.followOnly = await enableFollowOnlyVisibility(page);
  await checkpointProgress(args, "publish_modal_follow_only", {
    follow_only: result.followOnly,
  });

  if (payload.activity_tag_required) {
    result.activitySelector =
      (await clickByEvaluate(page, [
        "input[placeholder*='请选择创作活动']",
        ".drop-activity .el-input__inner",
        ".drop-activity",
      ])) || "";
    await page.waitForTimeout(500);
    const activitySelection =
      await selectHiddenDropdownOption(page, ".drop-activity-popper li, .drop-activity-popper .el-select-dropdown__item", 0);
    result.activityOptionSelector = activitySelection.selector;
    result.activityOptionText = activitySelection.clickedText;
    await page.waitForTimeout(500);
  }
  await checkpointProgress(args, "publish_modal_activity_selected", {
    activity_selector: result.activitySelector,
    activity_option_selector: result.activityOptionSelector,
    activity_option_text: result.activityOptionText,
  });

  result.finalPublishSelector =
    (await clickByEvaluate(page, [
      "button.btn-b-red.ml16",
      "button.btn-b-red",
      ".button.btn-b-red.ml16",
      ".button.btn-b-red",
    ]))
    || (await clickLastVisible(page, [
      "button.btn-b-red",
      ".button.btn-b-red",
      ".button.btn-b-red.ml16",
      "button:has-text('发布文章')",
      "span:has-text('发布文章')",
      "a:has-text('发布文章')",
    ]))
    || "";

  await checkpointProgress(args, "publish_modal_final_clicked", {
    final_publish_selector: result.finalPublishSelector,
    final_url: page.url(),
    page_title: await page.title(),
  });

  return result;
}

async function isEditorSurfaceVisible(page) {
  const matches = [
    "input[placeholder*='标题']",
    "textarea[placeholder*='标题']",
    "textarea.editor-box",
    ".editor-box textarea",
    ".bytemd-editor [contenteditable='true']",
    ".editor [contenteditable='true']",
  ];
  const found = await firstVisibleLocator(page, matches);
  return Boolean(found);
}

async function attemptCredentialLogin(page, username, password) {
  const result = {
    attempted: false,
    username_selector: "",
    password_selector: "",
    submit_selector: "",
    password_login_tab_selector: "",
  };
  if (!username || !password) {
    return result;
  }

  result.attempted = true;
  result.password_login_tab_selector =
    (await clickFirstVisible(page, [
      "span.login-third-passwd",
      ".login-third-passwd",
      ".login-third-item.login-third-passwd",
    ])) || "";

  await page.waitForTimeout(1200);

  result.password_login_tab_selector =
    result.password_login_tab_selector || (await clickFirstVisible(page, [
      "text=密码登录",
      "button:has-text('密码登录')",
      "a:has-text('密码登录')",
      "[role='tab']:has-text('密码登录')",
      ".tab-item:has-text('密码登录')",
      ".login-tab:has-text('密码登录')",
    ])) || "";

  await page.waitForTimeout(1200);

  result.username_selector =
    (await fillFirstVisible(page, [
      "input[placeholder*='手机号']",
      "input[placeholder*='手机号码']",
      "input[placeholder*='用户名']",
      "input[placeholder*='账号']",
      "input[placeholder*='邮箱']",
      "input[name*='mobile']",
      "input[name*='user']",
      "input[name*='login']",
      "input[type='text']",
      "input[type='tel']",
    ], username)) || "";

  result.password_selector =
    (await fillFirstVisible(page, [
      "input[placeholder*='密码']",
      "input[type='password']",
      "input[name*='password']",
      "input[autocomplete='current-password']",
    ], password)) || "";

  await clickConsentCheckbox(page);

  result.submit_selector =
    (await clickFirstVisible(page, [
      "button:has-text('登录')",
      "button:has-text('立即登录')",
      "a:has-text('登录')",
      "input[type='submit']",
      "button[type='submit']",
    ])) || "";

  return result;
}

async function attemptSmsLogin(page, phone) {
  const result = {
    attempted: false,
    sms_login_tab_selector: "",
    phone_selector: "",
    code_selector: "",
    get_code_selector: "",
  };
  if (!phone) {
    return result;
  }

  result.attempted = true;
  result.sms_login_tab_selector =
    (await clickFirstVisible(page, [
      "text=验证码登录",
      "button:has-text('验证码登录')",
      "a:has-text('验证码登录')",
      "[role='tab']:has-text('验证码登录')",
      ".tab-item:has-text('验证码登录')",
      ".login-tab:has-text('验证码登录')",
    ])) || "";

  await page.waitForTimeout(1200);

  result.phone_selector =
    (await fillFirstVisible(page, [
      "input[placeholder*='手机号']",
      "input[placeholder*='手机号码']",
      "input[type='tel']",
      "input[name*='mobile']",
      "input[name*='phone']",
    ], phone)) || "";

  result.code_selector =
    (await fillFirstVisible(page, [
      "input[placeholder*='验证码']",
      "input[name*='code']",
      "input[inputmode='numeric']",
    ], "")) || "";

  await clickConsentCheckbox(page);

  result.get_code_selector =
    (await clickFirstVisible(page, [
      "button:has-text('获取验证码')",
      "span:has-text('获取验证码')",
      "a:has-text('获取验证码')",
    ])) || "";

  return result;
}

async function fillSmsCodeIfAvailable(page, smsCodeFile, state) {
  if (!smsCodeFile || state.codeFilled) {
    return state;
  }
  const smsCode = await readOptionalTrimmedFile(smsCodeFile);
  if (!/^\d{4,8}$/.test(smsCode)) {
    return state;
  }

  const codeSelector =
    (await fillFirstVisible(page, [
      "input[placeholder*='验证码']",
      "input[name*='code']",
      "input[inputmode='numeric']",
      "input[type='number']",
      "input[type='text']",
    ], smsCode)) || "";
  if (!codeSelector) {
    return state;
  }

  const submitSelector =
    (await clickFirstVisible(page, [
      "button:has-text('登录')",
      "button:has-text('立即登录')",
      "a:has-text('登录')",
      "input[type='submit']",
      "button[type='submit']",
    ])) || "";

  return {
    ...state,
    codeFilled: true,
    codeSelector,
    submitSelector,
  };
}

async function waitForLoginCompletion(page, context, options) {
  const {
    stateFile,
    timeoutMs,
    smsCodeFile,
  } = options;
  const startedAt = Date.now();
  let loginUrl = page.url();
  let codeAutomation = {
    codeFilled: false,
    codeSelector: "",
    submitSelector: "",
  };

  while (Date.now() - startedAt < timeoutMs) {
    loginUrl = page.url();
    if (!loginUrl.includes("passport.csdn.net/login")) {
      const cookies = await context.cookies();
      await context.storageState({ path: stateFile });
      return {
        loginCompleted: true,
        loginUrl,
        cookies,
        codeAutomation,
      };
    }
    codeAutomation = await fillSmsCodeIfAvailable(page, smsCodeFile, codeAutomation);
    await page.waitForTimeout(1000);
  }

  return {
    loginCompleted: false,
    loginUrl,
    cookies: await context.cookies(),
    codeAutomation,
  };
}

async function gotoWithAbortTolerance(page, url, options) {
  try {
    await page.goto(url, options);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (!message.includes("ERR_ABORTED")) {
      throw error;
    }
    await page.waitForTimeout(2000);
  }
}

async function detectCsdnLoginSurface(page) {
  const finalUrl = page.url();
  const title = await page.title().catch(() => "");
  const bodyText = await page.locator("body").innerText({ timeout: 1500 }).catch(() => "");
  const hasLoginControl = await firstVisibleLocator(page, [
    "text=微信登录",
    "text=验证码登录",
    "text=APP登录",
    "text=登录可享更多权益",
    "input[placeholder*='手机号']",
    "input[placeholder*='验证码']",
  ]).then(Boolean).catch(() => false);
  return {
    isLogin: finalUrl.includes("passport.csdn.net/login")
      || /登录/.test(title)
      || hasLoginControl
      || /微信登录|验证码登录|登录可享更多权益/.test(bodyText),
    finalUrl,
    title,
  };
}

async function bootstrapSession(args) {
  const stateFile = args["state-file"];
  if (!stateFile) {
    throw new Error("Missing required --state-file");
  }
  const headless = parseBool(args.headless, false);
  const timeoutMs = Number(args["timeout-ms"] || "120000");
  const username = process.env.CSDN_USERNAME || "";
  const password = process.env.CSDN_PASSWORD || "";
  const loginMode = (process.env.CSDN_LOGIN_MODE || args["login-mode"] || "auto").toLowerCase();
  const smsCodeFile = process.env.CSDN_SMS_CODE_FILE || args["sms-code-file"] || "";

  const runtime = await launchCsdnContext({ headless, preferPersistent: true });
  const { browser, context, page, profileDir, persistent } = runtime;
  await checkpointProgress(args, "launch_login_page", {
    persistent_browser: persistent,
    browser_profile_dir: profileDir,
  });
  await gotoWithAbortTolerance(page, "https://passport.csdn.net/login", {
    timeout: timeoutMs,
    waitUntil: "domcontentloaded",
  });

  let autoLogin = {};
  if (loginMode === "sms") {
    autoLogin = await attemptSmsLogin(page, username);
  } else if (loginMode === "password") {
    autoLogin = await attemptCredentialLogin(page, username, password);
  } else {
    autoLogin = username && password
      ? await attemptCredentialLogin(page, username, password)
      : await attemptSmsLogin(page, username);
  }

  const completion = await waitForLoginCompletion(page, context, {
    stateFile,
    timeoutMs,
    smsCodeFile,
  });
  const result = {
    status: "ok",
    action: "bootstrap-session",
    state_file: stateFile,
    login_url: completion.loginUrl,
    cookie_count: completion.cookies.length,
    login_completed: completion.loginCompleted,
    login_mode: loginMode,
    sms_code_file: smsCodeFile,
    browser_profile_dir: profileDir,
    persistent_browser: persistent,
    auto_login: autoLogin,
    code_automation: completion.codeAutomation,
    note: "Storage state captured after a completed manual login window.",
  };
  await checkpointResult(args, result);
  await closeRuntime(runtime);

  if (!completion.loginCompleted) {
    throw new Error(
      "CSDN login did not complete within the manual window. Finish login/captcha and rerun bootstrap-session."
    );
  }

  return result;
}

async function checkSession(args) {
  const stateFile = args["state-file"] || "";
  const headless = parseBool(args.headless, true);
  const timeoutMs = Number(args["timeout-ms"] || "60000");
  const runtime = await launchCsdnContext({
    headless,
    stateFile: stateFile || undefined,
    preferPersistent: true,
  });
  const { page, profileDir, persistent } = runtime;
  await checkpointProgress(args, "check_session_launch", {
    persistent_browser: persistent,
    browser_profile_dir: profileDir,
    state_file: stateFile || "",
  });
  await gotoWithAbortTolerance(page, "https://editor.csdn.net/md/", {
    timeout: timeoutMs,
    waitUntil: "domcontentloaded",
  });
  await page.waitForTimeout(4000);
  const editorVisible = await isEditorSurfaceVisible(page);
  const finalUrl = page.url();
  const redirectedToLogin = finalUrl.includes("passport.csdn.net/login");
  const result = {
    status: redirectedToLogin ? "blocked" : "ok",
    action: "check-session",
    persistent_browser: persistent,
    browser_profile_dir: profileDir,
    state_file: stateFile || "",
    live_ready: editorVisible && !redirectedToLogin,
    final_url: finalUrl,
    page_title: await page.title(),
    reason: redirectedToLogin
      ? "session_invalid_or_missing"
      : editorVisible
        ? "editor_surface_reached"
        : "editor_surface_not_reached",
  };
  await checkpointResult(args, result);
  await closeRuntime(runtime);
  return result;
}

async function prepareArticle(args) {
  const stateFile = args["state-file"];
  const payloadFile = args["payload-file"];
  if (!stateFile) {
    throw new Error("Missing required --state-file");
  }
  if (!payloadFile) {
    throw new Error("Missing required --payload-file");
  }

  const payload = await readJson(payloadFile);
  const headless = parseBool(args.headless, true);
  const timeoutMs = Number(args["timeout-ms"] || "60000");
  const submit = parseBool(args.submit, false);

  const runtime = await launchCsdnContext({ headless, stateFile, preferPersistent: true });
  const { browser, context, page, profileDir, persistent } = runtime;
  await checkpointProgress(args, "launch_editor", {
    persistent_browser: persistent,
    browser_profile_dir: profileDir,
  });
  await gotoWithAbortTolerance(page, "https://editor.csdn.net/md/", {
    timeout: timeoutMs,
    waitUntil: "domcontentloaded",
  });
  await page.waitForTimeout(4000);
  await checkpointProgress(args, "editor_loaded", {
    final_url: page.url(),
    page_title: await page.title(),
  });

  const loginSurface = await detectCsdnLoginSurface(page);
  if (loginSurface.isLogin) {
    const artifacts = await capturePageArtifacts(page, args, "csdn-login-blocked");
    const result = {
      status: "blocked",
      action: "prepare-article",
      platform: "CSDN",
      reason: "session_invalid_or_missing",
      failure_code: "session_invalid_or_missing",
      final_blocker: "session_invalid_or_missing",
      final_url: loginSurface.finalUrl,
      page_title: loginSurface.title,
      live_ready: false,
      evidence: artifacts,
      next_action: "Run CSDN login bootstrap before publishing.",
    };
    await checkpointResult(args, result);
    await closeRuntime(runtime);
    return result;
  }

  const titleSelector = await fillCsdnTitle(page, payload.title || "");
  if (!titleSelector) {
    throw new Error("Could not find a visible CSDN title input.");
  }
  await checkpointProgress(args, "title_filled", {
    title_selector: titleSelector,
  });

  const editorMeta = await fillEditor(page, payload.markdown || "");
  const imageTransfer = await waitForExternalImageTransfer(page, payload.markdown || "");
  await page.waitForTimeout(1500);
  await checkpointProgress(args, "editor_filled", {
    editor_selector: editorMeta.selector,
    editor_mode: editorMeta.mode,
    external_image_transfer: imageTransfer,
  });

  let publishClicked = false;
  let publishConfirmed = false;
  let publishValidationReason = "submit_not_requested";
  let publishModal = null;
  let publishedArticleUrl = "";
  let trafficCoupon = null;
  let fanBroadcast = null;
  const fanBroadcastAudience = normalizeFanBroadcastAudience(args["fan-broadcast-audience"]);
  if (submit) {
    const publishButton = await firstVisibleLocator(page, [
      "button:has-text('发布文章')",
      "button:has-text('发布')",
      "a:has-text('发布文章')",
      "a:has-text('发布')",
    ]);
    if (!publishButton) {
      throw new Error("Could not find a visible CSDN publish button.");
    }
    await publishButton.locator.click();
    publishClicked = true;
    await page.waitForTimeout(4000);
    await checkpointProgress(args, "top_publish_clicked", {
      final_url: page.url(),
      page_title: await page.title(),
    });
    publishModal = await completePublishModal(page, payload, args);
    await checkpointProgress(args, "publish_modal_completed", {
      publish_modal: publishModal,
      final_url: page.url(),
      page_title: await page.title(),
    });
    await withTimeout(
      page.waitForURL((url) => !url.toString().includes("editor.csdn.net/md"), {
        timeout: Math.min(timeoutMs, 15000),
      }).catch(() => null),
      16000,
    );
    await page.waitForTimeout(3000);
    await checkpointProgress(args, "publish_validation", {
      final_url: page.url(),
      page_title: await page.title(),
    });
    const finalUrl = page.url();
    const stillEditing = await isEditorSurfaceVisible(page);
    const onEditorPage = finalUrl.includes("editor.csdn.net/md");
    const redirectedToLogin = finalUrl.includes("passport.csdn.net/login");
    publishConfirmed = !stillEditing && !onEditorPage && !redirectedToLogin;
    if (publishConfirmed) {
      publishValidationReason = "left_editor_surface";
    } else if (redirectedToLogin) {
      publishValidationReason = "redirected_to_login";
    } else if (stillEditing) {
      publishValidationReason = "editor_surface_still_visible";
    } else {
      publishValidationReason = "final_url_not_verified";
    }
    if (publishConfirmed) {
      publishedArticleUrl = await extractPublishedArticleUrl(page);
      trafficCoupon = await applyTrafficCoupons(page, {
        title: payload.title || "",
        publishedArticleUrl,
      }, args);
      fanBroadcast = await triggerFanBroadcast(page, publishedArticleUrl, payload.title || "", fanBroadcastAudience);
    }
  }

  const result = {
    status: "ok",
    action: "prepare-article",
    persistent_browser: persistent,
    browser_profile_dir: profileDir,
    title_selector: titleSelector,
    editor_selector: editorMeta.selector,
    editor_mode: editorMeta.mode,
    submit_requested: submit,
    publish_clicked: publishClicked,
    publish_modal: publishModal,
    publish_confirmed: publishConfirmed,
    publish_validation_reason: publishValidationReason,
    final_url: page.url(),
    published_article_url: publishedArticleUrl,
    traffic_coupon: trafficCoupon,
    fan_broadcast: fanBroadcast,
    external_image_transfer: imageTransfer,
    page_title: await page.title(),
  };

  await checkpointResult(args, result);
  await closeRuntime(runtime);
  return result;
}

async function postPublishPromotions(args) {
  const stateFile = args["state-file"];
  const headless = parseBool(args.headless, true);
  const timeoutMs = Number(args["timeout-ms"] || "60000");
  const publishedArticleUrl = String(args["published-article-url"] || "").trim();
  const articleTitle = String(args["article-title"] || "").trim();
  const fanBroadcastAudience = normalizeFanBroadcastAudience(args["fan-broadcast-audience"]);

  const runtime = await launchCsdnContext({ headless, stateFile, preferPersistent: true });
  const { page, profileDir, persistent } = runtime;
  await checkpointProgress(args, "post_publish_promotions_launch", {
    persistent_browser: persistent,
    browser_profile_dir: profileDir,
    published_article_url: publishedArticleUrl,
  });

  const trafficCoupon = await applyTrafficCoupons(page, {
    title: articleTitle,
    publishedArticleUrl,
  }, args);
  await checkpointProgress(args, "post_publish_promotions_coupon", {
    traffic_coupon: trafficCoupon,
  });

  const fanBroadcast = await triggerFanBroadcast(page, publishedArticleUrl, articleTitle, fanBroadcastAudience);
  await checkpointProgress(args, "post_publish_promotions_broadcast", {
    fan_broadcast: fanBroadcast,
  });

  const result = {
    status: "ok",
    action: "post-publish-promotions",
    persistent_browser: persistent,
    browser_profile_dir: profileDir,
    final_url: page.url(),
    page_title: await page.title(),
    published_article_url: publishedArticleUrl,
    article_title: articleTitle,
    traffic_coupon: trafficCoupon,
    fan_broadcast: fanBroadcast,
  };
  await checkpointResult(args, result);
  await closeRuntime(runtime);
  return result;
}

async function applyTrafficCouponsOnly(args) {
  const stateFile = args["state-file"];
  const headless = parseBool(args.headless, true);
  const timeoutMs = Number(args["timeout-ms"] || "60000");
  const publishedArticleUrl = String(args["published-article-url"] || "").trim();
  const articleTitle = String(args["article-title"] || "").trim();

  const runtime = await launchCsdnContext({ headless, stateFile, preferPersistent: true });
  const { page, profileDir, persistent } = runtime;
  await checkpointProgress(args, "apply_traffic_coupons_launch", {
    persistent_browser: persistent,
    browser_profile_dir: profileDir,
    published_article_url: publishedArticleUrl,
  });
  const trafficCoupon = await applyTrafficCoupons(page, {
    title: articleTitle,
    publishedArticleUrl,
  }, args);
  const result = {
    status: "ok",
    action: "apply-traffic-coupons",
    persistent_browser: persistent,
    browser_profile_dir: profileDir,
    final_url: page.url(),
    page_title: await page.title(),
    published_article_url: publishedArticleUrl,
    article_title: articleTitle,
    traffic_coupon: trafficCoupon,
  };
  await checkpointResult(args, result);
  await closeRuntime(runtime);
  return result;
}

async function fanBroadcastOnly(args) {
  const stateFile = args["state-file"];
  const headless = parseBool(args.headless, true);
  const publishedArticleUrl = String(args["published-article-url"] || "").trim();
  const articleTitle = String(args["article-title"] || "").trim();
  const fanBroadcastAudience = normalizeFanBroadcastAudience(args["fan-broadcast-audience"]);

  const runtime = await launchCsdnContext({ headless, stateFile, preferPersistent: true });
  const { page, profileDir, persistent } = runtime;
  await checkpointProgress(args, "fan_broadcast_launch", {
    persistent_browser: persistent,
    browser_profile_dir: profileDir,
    published_article_url: publishedArticleUrl,
  });

  const fanBroadcast = await triggerFanBroadcast(page, publishedArticleUrl, articleTitle, fanBroadcastAudience);
  const result = {
    status: fanBroadcast.submitted ? "ok" : "blocked",
    action: "fan-broadcast",
    persistent_browser: persistent,
    browser_profile_dir: profileDir,
    final_url: page.url(),
    page_title: await page.title(),
    published_article_url: publishedArticleUrl,
    article_title: articleTitle,
    fan_broadcast: fanBroadcast,
  };
  await checkpointResult(args, result);
  await closeRuntime(runtime);
  return result;
}

async function resolvePublishedUrlOnly(args) {
  const stateFile = args["state-file"];
  const payloadFile = args["payload-file"];
  if (!stateFile) {
    throw new Error("Missing required --state-file");
  }
  if (!payloadFile) {
    throw new Error("Missing required --payload-file");
  }

  const payload = await readJson(payloadFile);
  const headless = parseBool(args.headless, true);
  const timeoutMs = Number(args["timeout-ms"] || "60000");
  const articleTitle = String(payload.title || payload.article?.title || "").trim();
  const runtime = await launchCsdnContext({ headless, stateFile, preferPersistent: true });
  const { page, profileDir, persistent } = runtime;
  await checkpointProgress(args, "resolve_published_url_launch", {
    persistent_browser: persistent,
    browser_profile_dir: profileDir,
    article_title: articleTitle,
  });

  const lookup = await resolvePublishedArticleUrl(page, articleTitle, timeoutMs);
  const result = {
    status: lookup.found ? "ok" : "blocked",
    action: "resolve-published-url",
    persistent_browser: persistent,
    browser_profile_dir: profileDir,
    final_url: lookup.url || page.url(),
    page_title: await page.title(),
    published_article_url: lookup.url || "",
    article_title: articleTitle,
    matched_title: lookup.matched_title || "",
    publish_resolution_source: lookup.resolution_source || "",
    reason: lookup.found ? "" : "published_article_not_found",
    final_blocker: lookup.found ? "" : "published_article_not_found",
  };
  await checkpointResult(args, result);
  await closeRuntime(runtime);
  return result;
}

async function inspectPublishModal(args) {
  const stateFile = args["state-file"];
  const payloadFile = args["payload-file"];
  if (!stateFile) {
    throw new Error("Missing required --state-file");
  }
  if (!payloadFile) {
    throw new Error("Missing required --payload-file");
  }

  const payload = await readJson(payloadFile);
  const headless = parseBool(args.headless, false);
  const timeoutMs = Number(args["timeout-ms"] || "60000");
  const runtime = await launchCsdnContext({ headless, stateFile, preferPersistent: true });
  const { page, profileDir, persistent } = runtime;

  await gotoWithAbortTolerance(page, "https://editor.csdn.net/md/", {
    timeout: timeoutMs,
    waitUntil: "domcontentloaded",
  });
  await page.waitForTimeout(4000);

  const titleSelector = await fillCsdnTitle(page, payload.title || "");
  if (!titleSelector) {
    throw new Error("Could not find a visible CSDN title input.");
  }
  await fillEditor(page, payload.markdown || "");
  await page.waitForTimeout(5000);

  const publishButton = await firstVisibleLocator(page, [
    "button:has-text('发布文章')",
    "button:has-text('发布')",
    "a:has-text('发布文章')",
    "a:has-text('发布')",
  ]);
  if (!publishButton) {
    throw new Error("Could not find a visible CSDN publish button.");
  }
  await publishButton.locator.click();
  await page.waitForTimeout(4000);

  const followOnly = await enableFollowOnlyVisibility(page);
  await page.waitForTimeout(500);

  const publishArtifacts = await capturePageArtifacts(page, args, "csdn-publish-modal");
  const modalState = await page.evaluate(() => {
    const collect = (selector) => Array.from(document.querySelectorAll(selector))
      .map((node) => ({
        text: String(node.textContent || "").replace(/\s+/g, " ").trim(),
        className: String(node.getAttribute("class") || ""),
        ariaChecked: String(node.getAttribute("aria-checked") || ""),
        tag: node.tagName,
      }))
      .filter((item) => item.text)
      .slice(0, 50);

    const bodyText = String(document.body?.innerText || "").replace(/\s+/g, " ");
    return {
      body_excerpt: bodyText.slice(0, 4000),
      visibility_candidates: collect("label, span, div, li, p, button").filter((item) => /粉丝可见|仅关注可见|仅粉丝可见|公开可见|权限/.test(item.text)),
      dialog_candidates: collect(".el-dialog, .el-dialog__body, .modal, [role='dialog'], .publish-modal, .common-dialog"),
    };
  }).catch(() => ({ body_excerpt: "", visibility_candidates: [], dialog_candidates: [] }));

  const result = {
    status: "ok",
    action: "inspect-publish-modal",
    persistent_browser: persistent,
    browser_profile_dir: profileDir,
    final_url: page.url(),
    page_title: await page.title(),
    follow_only: followOnly,
    modal_state: modalState,
    artifacts: publishArtifacts,
  };
  await checkpointResult(args, result);
  await closeRuntime(runtime);
  return result;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const action = args.action;
  const outputFile = args["output-file"];

  if (!action) {
    throw new Error("Missing required --action");
  }
  if (!outputFile) {
    throw new Error("Missing required --output-file");
  }

  let result;
  if (action === "bootstrap-session") {
    result = await bootstrapSession(args);
  } else if (action === "check-session") {
    result = await checkSession(args);
  } else if (action === "prepare-article") {
    result = await prepareArticle(args);
  } else if (action === "resolve-published-url") {
    result = await resolvePublishedUrlOnly(args);
  } else if (action === "inspect-publish-modal") {
    result = await inspectPublishModal(args);
  } else if (action === "apply-traffic-coupons") {
    result = await applyTrafficCouponsOnly(args);
  } else if (action === "fan-broadcast") {
    result = await fanBroadcastOnly(args);
  } else if (action === "post-publish-promotions") {
    result = await postPublishPromotions(args);
  } else {
    throw new Error(`Unsupported action: ${action}`);
  }

  await writeJson(outputFile, result);
}

main().catch(async (error) => {
  const args = parseArgs(process.argv.slice(2));
  const outputFile = args["output-file"];
  const payload = {
    status: "error",
    error: error instanceof Error ? error.message : String(error),
    cwd: process.cwd(),
    helper_dir: __dirname,
  };
  if (outputFile) {
    await writeJson(outputFile, payload);
    process.exit(1);
  }
  console.error(JSON.stringify(payload, null, 2));
  process.exit(1);
});
