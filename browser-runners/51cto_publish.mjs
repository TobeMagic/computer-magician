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
const DEFAULT_PROFILE_DIR = path.resolve(__dirname, "credentials/51cto-browser-profile");
const DEFAULT_PUBLISH_URL = process.env.CTO51_PUBLISH_URL || "https://blog.51cto.com/blogger/publish";
const DEFAULT_ACTIVITY_URL = process.env.CTO51_ACTIVITY_URL || "https://blog.51cto.com/creative-center/activity";
const DEFAULT_TASK_URL = process.env.CTO51_TASK_URL || "https://blog.51cto.com/creative-center/task";
const DEFAULT_LOCALE = process.env.CTO51_BROWSER_LOCALE || "zh-CN";
const DEFAULT_TIMEZONE = process.env.CTO51_BROWSER_TIMEZONE || "Asia/Shanghai";
  const DEFAULT_USER_AGENT = process.env.CTO51_BROWSER_USER_AGENT
    || "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36";
const DEFAULT_EXECUTABLE_PATH = process.env.CTO51_BROWSER_EXECUTABLE_PATH
    || "/ms-playwright/chromium-1223/chrome-linux64/chrome";
const CTO51_USERNAME = (process.env.CTO51_USERNAME || "").trim();
const CTO51_PASSWORD = (process.env.CTO51_PASSWORD || "").trim();
const ACTIVITY_ACTIVE_HINTS = ["进行中", "报名中", "征稿中", "投稿中", "火热进行", "参与中"];
const ACTIVITY_ENDED_HINTS = ["已结束", "活动结束", "已截止", "截止", "已完结"];
const REWARD_HINTS = [
  "现金",
  "奖金",
  "稿费",
  "礼品卡",
  "京东卡",
  "实物",
  "奖品",
  "奖励",
  "福利",
  "积分",
  "兑换",
  "流量扶持",
  "曝光",
  "证书",
  "周边",
  "红包",
  "抽奖",
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

function evidenceDirFromArgs(args) {
  const raw = String(args["evidence-dir"] || "").trim();
  if (!raw) {
    return "";
  }
  return path.isAbsolute(raw) ? raw : path.resolve(raw);
}

function evidenceStem(label) {
  return `${Date.now()}-${String(label || "evidence")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "") || "evidence"}`;
}

async function capturePageEvidence(page, args, label, extra = {}) {
  const evidenceDir = evidenceDirFromArgs(args);
  if (!evidenceDir || !page || page.isClosed()) {
    return null;
  }

  await fs.mkdir(evidenceDir, { recursive: true });
  const stem = evidenceStem(label);
  const screenshotPath = path.join(evidenceDir, `${stem}.png`);
  const metadataPath = path.join(evidenceDir, `${stem}.json`);
  const title = await page.title().catch(() => "");
  const payload = {
    label,
    captured_at: new Date().toISOString(),
    url: page.url(),
    title,
    ...extra,
  };

  let screenshotSaved = false;
  try {
    await page.screenshot({ path: screenshotPath, fullPage: true });
    screenshotSaved = true;
  } catch {
    screenshotSaved = false;
  }

  await fs.writeFile(metadataPath, JSON.stringify(payload, null, 2), "utf8");
  return {
    label,
    dir: evidenceDir,
    screenshot_path: screenshotSaved ? screenshotPath : "",
    metadata_path: metadataPath,
    url: payload.url,
    title,
  };
}

async function loadJsonFile(jsonPath) {
  if (!jsonPath) {
    return null;
  }
  const raw = await fs.readFile(jsonPath, "utf8");
  return JSON.parse(raw);
}

async function writeStorageState(context, stateFile) {
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
    Object.defineProperty(navigator, "maxTouchPoints", {
      get: () => 1,
      configurable: true,
    });
    Object.defineProperty(navigator, "hardwareConcurrency", {
      get: () => 8,
      configurable: true,
    });
    Object.defineProperty(navigator, "deviceMemory", {
      get: () => 8,
      configurable: true,
    });
    Object.defineProperty(navigator, "plugins", {
      get: () => [1, 2, 3, 4, 5],
      configurable: true,
    });
    Object.defineProperty(navigator, "mimeTypes", {
      get: () => [1, 2, 3, 4],
      configurable: true,
    });
    if (!window.chrome) {
      Object.defineProperty(window, "chrome", {
        value: {
          runtime: {},
          loadTimes: () => {},
          csi: () => {},
          app: {},
        },
        configurable: true,
      });
    }
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
      parameters.name === "notifications" ? Promise.resolve({ state: Notification.permission }) : originalQuery(parameters)
    );
  });
}

function browserProfileDir() {
  const raw = String(process.env.CTO51_BROWSER_PROFILE_DIR || "").trim();
  if (!raw) {
    return DEFAULT_PROFILE_DIR;
  }
  return path.isAbsolute(raw) ? raw : path.resolve(AIMAGICIAN_ROOT, raw);
}

async function launch51ctoContext(options) {
  const { headless, stateFile, preferPersistent = false } = options;
  const persistent = preferPersistent && parseBool(process.env.CTO51_PERSISTENT_BROWSER, true);
  const launchOptions = {
    headless,
    executablePath: DEFAULT_EXECUTABLE_PATH,
    locale: DEFAULT_LOCALE,
    timezoneId: DEFAULT_TIMEZONE,
    userAgent: DEFAULT_USER_AGENT,
    ignoreDefaultArgs: ["--enable-automation", "--hide-scrollbars", "--headless"],
    args: [
      "--start-maximized",
      "--lang=zh-CN,zh",
      "--disable-blink-features=AutomationControlled",
      "--no-sandbox",
      "--disable-gpu",
      "--enable-features=NetworkService,NetworkServiceInProcess",
      "--use-gl=angle",
      "--use-angle=swiftshader-webgl",
    ],
  };
  if (headless) {
    launchOptions.args.unshift("--headless=new");
  }

  if (persistent) {
    const profileDir = browserProfileDir();
    await clearStaleChromiumSingletonLocks(profileDir);
    const context = await chromium.launchPersistentContext(profileDir, launchOptions);
    await applyStealthInitScript(context);
    const page = context.pages()[0] || await context.newPage();
    return { browser: null, context, page, persistent, profileDir };
  }

  const browser = await chromium.launch(launchOptions);
  const contextOptions = {
    locale: DEFAULT_LOCALE,
    timezoneId: DEFAULT_TIMEZONE,
    userAgent: DEFAULT_USER_AGENT,
    viewport: { width: 1920, height: 1080 },
  };
  if (stateFile) {
    contextOptions.storageState = stateFile;
  }
  const context = await browser.newContext(contextOptions);
  await applyStealthInitScript(context);
  const page = await context.newPage();
  return { browser, context, page, persistent, profileDir: browserProfileDir() };
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

function parseSessionCookies(rawSession) {
  const raw = String(rawSession || "").trim();
  if (!raw) {
    return [];
  }
  const cookies = [];
  if (raw.includes("=")) {
    const pairs = raw.split(";").map((item) => item.trim()).filter(Boolean);
    for (const pair of pairs) {
      const index = pair.indexOf("=");
      if (index <= 0) {
        continue;
      }
      const name = pair.slice(0, index).trim();
      const value = pair.slice(index + 1).trim();
      if (!name || !value) {
        continue;
      }
      cookies.push({
        name,
        value,
        domain: ".51cto.com",
        path: "/",
        httpOnly: false,
        secure: true,
        sameSite: "Lax",
      });
    }
  }
  return cookies;
}

async function injectSessionCookies(context) {
  const cookies = parseSessionCookies(process.env.CTO51_SESSION || "");
  if (!cookies.length) {
    return { applied: false, names: [] };
  }
  await context.addCookies(cookies);
  return {
    applied: true,
    names: cookies.map((item) => item.name),
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

async function fillFirstVisible(page, selectors, value) {
  const match = await firstVisibleLocator(page, selectors);
  if (!match) {
    return null;
  }
  await match.locator.fill(value);
  return match.selector;
}

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim().toLowerCase();
}

function uniqueValues(values) {
  const result = [];
  for (const value of values) {
    const normalized = String(value || "").trim();
    if (!normalized || result.includes(normalized)) {
      continue;
    }
    result.push(normalized);
  }
  return result;
}

function buildTextHints(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return [];
  }
  const parts = raw
    .split(/[\/|,，、>]+/)
    .map((item) => item.trim())
    .filter(Boolean);
  return uniqueValues([raw, ...parts]);
}

function normalizeMultilineText(value) {
  return String(value || "").replace(/\r\n/g, "\n").trim();
}

async function setLocatorValue(locator, value) {
  const text = String(value ?? "");
  await locator.scrollIntoViewIfNeeded().catch(() => null);
  try {
    await locator.fill(text);
    return "fill";
  } catch {
    await locator.click({ force: true }).catch(() => null);
    await locator.evaluate((node, nextValue) => {
      node.value = nextValue;
      node.dispatchEvent(new Event("input", { bubbles: true }));
      node.dispatchEvent(new Event("change", { bubbles: true }));
    }, text);
    return "evaluate";
  }
}

async function clickLocatorRobust(page, locator) {
  await locator.scrollIntoViewIfNeeded().catch(() => null);
  try {
    await locator.click({ timeout: 3000 });
    return "click";
  } catch {
    // Fall through to the more aggressive click strategies below.
  }
  try {
    await locator.click({ timeout: 3000, force: true });
    return "force";
  } catch {
    // Fall through to the DOM click path.
  }
  const box = await locator.boundingBox().catch(() => null);
  if (box) {
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    return "mouse";
  }
  await locator.evaluate((node) => node.click()).catch(() => null);
  return "evaluate";
}

async function clickFirstVisibleRobust(page, selectors) {
  const match = await firstVisibleLocator(page, selectors);
  if (!match) {
    return null;
  }
  const clickMode = await clickLocatorRobust(page, match.locator);
  return {
    selector: match.selector,
    clickMode,
  };
}

async function clickFirstMatchingText(page, selectors, textHints) {
  const hints = Array.isArray(textHints)
    ? uniqueValues(textHints)
    : buildTextHints(textHints);
  if (!hints.length) {
    return null;
  }
  for (const hint of hints) {
    for (const selector of selectors) {
      const locator = page.locator(selector).filter({ hasText: hint }).first();
      try {
        if (await locator.isVisible({ timeout: 1200 })) {
          const clickMode = await clickLocatorRobust(page, locator);
          return {
            selector,
            clickMode,
            matchedText: hint,
          };
        }
      } catch {
        continue;
      }
    }
  }
  return null;
}

async function waitForVisibleLocator(page, selectors, timeoutMs, intervalMs = 250) {
  const deadline = Date.now() + Math.max(timeoutMs, intervalMs);
  while (Date.now() < deadline) {
    const match = await firstVisibleLocator(page, selectors);
    if (match) {
      return match;
    }
    await page.waitForTimeout(intervalMs);
  }
  return null;
}

async function collectVisibleTexts(page, selectors) {
  const values = [];
  for (const selector of selectors) {
    const collected = await page.locator(selector).evaluateAll((nodes) => nodes
      .map((node) => {
        const text = (node.innerText || node.textContent || "").replace(/\s+/g, " ").trim();
        const visible = Boolean(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
        return visible ? text : "";
      })
      .filter(Boolean)).catch(() => []);
    values.push(...collected);
  }
  return uniqueValues(values);
}

function markdownImageWaitMs(markdown) {
  const imageCount = (String(markdown || "").match(/!\[[^\]]*]\([^)]*\)/g) || []).length;
  return Math.min(15000, Math.max(4000, 3000 + imageCount * 2200));
}

function inferBlockedReason(surface, loginAttempt = {}) {
  if (surface.surface === "blocked") {
    return "edgeone_blocked";
  }
  if (surface.manualClearanceRequired || loginAttempt.submitted) {
    return "manual_clearance_required";
  }
  if (loginAttempt.reason === "credentials_missing") {
    return "credentials_missing";
  }
  return "session_invalid_or_missing";
}

function isAuthorBlogHomeUrl(url) {
  const raw = String(url || "").trim();
  if (!/^https:\/\/blog\.51cto\.com\/[^/?#]+(?:[/?#]|$)/.test(raw)) {
    return false;
  }
  const pathname = new URL(raw).pathname.replace(/\/$/, "");
  const slug = pathname.split("/").filter(Boolean)[0] || "";
  return !["blogger", "creative-center", "home", "index", "login"].includes(slug);
}

function isPublicArticleUrl(url) {
  return /^https:\/\/blog\.51cto\.com\/[^/?#]+\/\d+(?:[/?#]|$)/.test(String(url || "").trim());
}

function isSuccessPageUrl(url) {
  return /^https:\/\/blog\.51cto\.com\/blogger\/success\/\d+(?:[/?#]|$)/.test(String(url || "").trim());
}

function successPageArticleId(url) {
  const match = String(url || "").trim().match(/^https:\/\/blog\.51cto\.com\/blogger\/success\/(\d+)(?:[/?#]|$)/);
  return match ? match[1] : "";
}

async function extractPublicArticleUrl(page, articleTitle = "") {
  const currentUrl = page.url();
  if (isPublicArticleUrl(currentUrl)) {
    return {
      url: currentUrl,
      source: "page_url",
    };
  }
  const titleHint = normalizeText(articleTitle);
  const match = await page.evaluate((expectedTitle) => {
    const anchors = Array.from(document.querySelectorAll("a[href*='blog.51cto.com/']"));
    const matches = anchors
      .map((anchor) => ({
        href: anchor.href || "",
        text: (anchor.innerText || anchor.textContent || "").replace(/\s+/g, " ").trim(),
        containerText: (anchor.closest("li, article, .item, .list-item, .blog-item, .article-item, .media, .card")?.innerText || "").replace(/\s+/g, " ").trim(),
      }))
      .filter((item) => /^https:\/\/blog\.51cto\.com\/[^/?#]+\/\d+(?:[/?#]|$)/.test(item.href));
    if (!matches.length) {
      return null;
    }
    const isPinned = (item) => /置顶|顶置|置頂/.test(String(item?.containerText || ""));
    if (expectedTitle) {
      const titled = matches.find((item) => {
        const haystack = `${item.text} ${item.containerText}`.toLowerCase();
        return haystack.includes(expectedTitle);
      });
      if (titled) {
        return {
          url: titled.href,
          source: isPinned(titled) ? "page_anchor_title_match_pinned" : "page_anchor_title_match",
        };
      }
      return null;
    }
    const nonPinned = matches.find((item) => !isPinned(item));
    if (nonPinned) {
      return {
        url: nonPinned.href,
        source: "page_anchor_non_pinned",
      };
    }
    return {
      url: matches[0].href,
      source: isPinned(matches[0]) ? "page_anchor_pinned_fallback" : "page_anchor",
    };
  }, titleHint).catch(() => null);
  if (match?.url) {
    return match;
  }
  return {
    url: "",
    source: "",
  };
}

async function resolveAuthorBlogHome(page) {
  const match = await page.evaluate(() => {
    const anchors = Array.from(document.querySelectorAll("a[href]"));
    const preferred = anchors.find((anchor) => {
      const text = (anchor.innerText || anchor.textContent || "").replace(/\s+/g, " ").trim();
      return text === "我的博客" && /^https:\/\/blog\.51cto\.com\/[^/?#]+(?:[/?#]|$)/.test(anchor.href || "");
    });
    if (preferred) {
      return preferred.href;
    }
    const fallback = anchors.find((anchor) => /^https:\/\/blog\.51cto\.com\/[^/?#]+(?:[/?#]|$)/.test(anchor.href || ""));
    return fallback ? fallback.href : "";
  }).catch(() => "");
  const resolved = String(match || "").trim();
  return isAuthorBlogHomeUrl(resolved) ? resolved : "";
}

async function resolvePublishedArticleFromSuccessPage(page, successUrl, preferredBlogHomeUrl = "") {
  const articleId = successPageArticleId(successUrl);
  if (!articleId) {
    return {
      confirmed: false,
      url: "",
      title: "",
      source: "",
    };
  }
  const blogHomeUrl = String(preferredBlogHomeUrl || "").trim() || await resolveAuthorBlogHome(page);
  if (!blogHomeUrl) {
    return {
      confirmed: false,
      url: "",
      title: "",
      source: "",
    };
  }
  return {
    confirmed: true,
    url: `${blogHomeUrl.replace(/\/$/, "")}/${articleId}`,
    title: "",
    source: "success_page_article_id",
  };
}

function activityStateFromText(text) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  if (!normalized) {
    return "unknown";
  }
  if (ACTIVITY_ACTIVE_HINTS.some((hint) => normalized.includes(hint))) {
    return "active";
  }
  if (ACTIVITY_ENDED_HINTS.some((hint) => normalized.includes(hint))) {
    return "ended";
  }
  return "unknown";
}

function rewardHitsFromText(text) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  return REWARD_HINTS.filter((hint) => normalized.includes(hint));
}

async function clickActivityStatusTab(page) {
  return clickFirstMatchingText(page, [
    "button",
    "a",
    "li",
    "div",
    "span",
    "[role='tab']",
  ], ["进行中", "报名中", "征稿中"]);
}

async function extractActivityCards(page) {
  return page.evaluate(({ activeHints, endedHints, rewardHints }) => {
    const isVisible = (node) => Boolean(node && (node.offsetWidth || node.offsetHeight || node.getClientRects().length));
    const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
    const dateRegex = /\d{4}[./-]\d{1,2}[./-]\d{1,2}/;
    const cardSelector = [
      "a",
      "article",
      "section",
      "li",
      "div[class*='item']",
      "div[class*='card']",
      "div[class*='activity']",
    ].join(",");
    const nodes = Array.from(document.querySelectorAll(cardSelector));
    const seen = new Set();
    const cards = [];
    for (const node of nodes) {
      if (!isVisible(node)) {
        continue;
      }
      const text = normalize(node.innerText || node.textContent || "");
      if (!text || text.length < 10 || text.length > 280) {
        continue;
      }
      const hasActive = activeHints.some((hint) => text.includes(hint));
      const hasEnded = endedHints.some((hint) => text.includes(hint));
      const state = hasActive && !hasEnded
        ? "active"
        : (hasEnded && !hasActive ? "ended" : "unknown");
      const rewardHits = rewardHints.filter((hint) => text.includes(hint));
      if (state === "unknown" && !dateRegex.test(text) && !rewardHits.length) {
        continue;
      }
      const anchor = node.matches("a[href]") ? node : node.closest("a[href]");
      const href = anchor ? anchor.href || "" : "";
      if (
        !href
        && text.includes("活动状态")
        && text.includes("全部")
        && text.includes("进行中")
        && text.includes("已结束")
      ) {
        continue;
      }
      const key = `${text}::${href}`;
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      cards.push({
        text,
        href,
        state,
        reward_hits: rewardHits,
        reward_bearing: rewardHits.length > 0,
      });
    }
    return cards.slice(0, 20);
  }, {
    activeHints: ACTIVITY_ACTIVE_HINTS,
    endedHints: ACTIVITY_ENDED_HINTS,
    rewardHints: REWARD_HINTS,
  }).catch(() => []);
}

async function checkRewardActivities(runtime, args, stateFile, timeoutMs) {
  const { context, page, profileDir } = runtime;
  const cookieResult = await injectSessionCookies(context);
  await checkpointProgress(args, "check_activity_open_surface", {
    profile_dir: profileDir,
    cookie_names: cookieResult.names,
    activity_url: DEFAULT_ACTIVITY_URL,
  });

  await page.goto(DEFAULT_ACTIVITY_URL, { waitUntil: "domcontentloaded", timeout: timeoutMs }).catch(() => null);
  await page.waitForTimeout(1800);
  let surface = await detectSurface(page);
  const loginAttempt = {
    attempted: false,
    submitted: false,
    reason: "",
  };

  if (surface.surface === "login") {
    Object.assign(loginAttempt, await attemptPasswordLogin(page));
    if (loginAttempt.submitted) {
      surface = await waitForBootstrapSurface(page, timeoutMs);
      await page.goto(DEFAULT_ACTIVITY_URL, { waitUntil: "domcontentloaded", timeout: timeoutMs }).catch(() => null);
      await page.waitForTimeout(1800);
      surface = await detectSurface(page);
    }
  }

  const tabSelection = await clickActivityStatusTab(page);
  if (tabSelection) {
    await page.waitForTimeout(1200);
  }

  const pageText = await page.locator("body").innerText().catch(() => "");
  const pageRewardHits = rewardHitsFromText(pageText);
  const cards = await extractActivityCards(page);
  const activeCandidates = cards.filter((item) => item.state === "active");
  const rewardCandidates = activeCandidates.filter((item) => item.reward_bearing);
  const bestCandidate = rewardCandidates[0] || null;

  const persisted = await persistState(context, stateFile);
  const finalSurface = await detectSurface(page);
  const reason = finalSurface.surface === "blocked"
    ? inferBlockedReason(finalSurface, loginAttempt)
    : (rewardCandidates.length ? "" : "no_active_reward_activity_detected");
  const evidence = await capturePageEvidence(page, args, "check-activity", {
    surface: finalSurface.surface,
    reward_candidate_count: rewardCandidates.length,
    best_candidate_text: bestCandidate?.text || "",
    reason,
  });

  return {
    status: finalSurface.surface === "blocked" ? "blocked" : "ok",
    mode: "check-activity",
    live_ready: finalSurface.surface === "editor" || finalSurface.surface === "unknown",
    final_url: page.url(),
    page_title: await page.title().catch(() => ""),
    state_file: stateFile,
    state_file_written: persisted.stateSaved,
    state_file_write_error: persisted.stateSaveError,
    browser_profile_dir: profileDir,
    surface: finalSurface.surface,
    reason,
    session_cookie_applied: cookieResult.applied,
    session_cookie_names: cookieResult.names,
    credential_login_attempted: loginAttempt.attempted,
    credential_login_submitted: loginAttempt.submitted,
    manual_clearance_required: finalSurface.manualClearanceRequired || Boolean(loginAttempt.submitted && finalSurface.surface !== "editor"),
    activity_page_url: page.url(),
    activity_page_title: await page.title().catch(() => ""),
    activity_status_tab_clicked: Boolean(tabSelection),
    activity_status_tab_selector: tabSelection?.selector || "",
    activity_status_tab_hint: tabSelection?.matchedText || "",
    page_reward_hits: pageRewardHits,
    activity_cards_scanned: cards.length,
    active_candidates: activeCandidates,
    reward_candidates: rewardCandidates,
    best_candidate: bestCandidate,
    activity_page_excerpt: String(pageText || "").replace(/\s+/g, " ").trim().slice(0, 800),
    evidence: {
      dir: evidenceDirFromArgs(args),
      snapshots: [evidence].filter(Boolean),
    },
  };
}

function parseRewardTaskPage(text) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  const titleMatch = normalized.match(/(20\d{2}年\d{1,2}月[^。；， ]{0,24}?活动)/);
  const windowMatch = normalized.match(/任务有效期[:：]\s*(20\d{2}\/\d{2}\/\d{2}\s*-\s*20\d{2}\/\d{2}\/\d{2})/);
  const progressMatch = normalized.match(/任务完成\s*(\d+)\s*\/\s*(\d+)/);
  const taskTitle = titleMatch ? titleMatch[1].trim() : "";
  const taskWindow = windowMatch ? windowMatch[1].trim() : "";
  const completedCount = progressMatch ? Number.parseInt(progressMatch[1], 10) : 0;
  const targetCount = progressMatch ? Number.parseInt(progressMatch[2], 10) : 0;
  const taskPresent = Boolean(taskTitle || taskWindow || progressMatch);
  return {
    taskPresent,
    taskTitle,
    taskWindow,
    completedCount,
    targetCount,
    textExcerpt: normalized.slice(0, 1200),
  };
}

async function verifyRewardParticipation(runtime, args, stateFile, timeoutMs, payload) {
  const { context, page, profileDir } = runtime;
  const cookieResult = await injectSessionCookies(context);
  await checkpointProgress(args, "verify_reward_open_surface", {
    profile_dir: profileDir,
    cookie_names: cookieResult.names,
    task_url: DEFAULT_TASK_URL,
  });

  await page.goto(DEFAULT_TASK_URL, { waitUntil: "domcontentloaded", timeout: timeoutMs }).catch(() => null);
  await page.waitForTimeout(1600);
  const surface = await detectSurface(page);
  let pageText = "";
  let parsed = parseRewardTaskPage("");
  const rewardDeadline = Date.now() + 8000;
  while (Date.now() < rewardDeadline) {
    pageText = await page.locator("body").innerText().catch(() => "");
    parsed = parseRewardTaskPage(pageText);
    if (parsed.taskPresent) {
      break;
    }
    await page.waitForTimeout(1000);
  }
  const articleTitle = normalizeText(payload?.title || "");
  const articleUrl = normalizeText(payload?.published_article_url || payload?.public_url || payload?.final_url || "");
  const evidence = await capturePageEvidence(page, args, "verify-reward", {
    task_title: parsed.taskTitle,
    task_window: parsed.taskWindow,
    completed_count: parsed.completedCount,
    target_count: parsed.targetCount,
    article_title: articleTitle,
    article_url: articleUrl,
  });
  let stateSaved = false;
  let stateSaveError = "";
  try {
    stateSaved = await writeStorageState(context, stateFile);
  } catch (error) {
    stateSaveError = String(error?.message || error);
  }

  const liveReady = surface.surface !== "blocked" && Boolean(page.url());
  const rewardConfirmed = parsed.taskPresent && parsed.targetCount > 0;
  const rewardCounted = rewardConfirmed && parsed.completedCount > 0;
  const reason = rewardConfirmed ? "" : "reward_task_not_detected";

  return {
    status: liveReady ? "ok" : "blocked",
    mode: "verify-reward",
    live_ready: liveReady,
    final_url: page.url(),
    page_title: await page.title().catch(() => ""),
    state_file: stateFile,
    state_file_written: stateSaved,
    state_file_write_error: stateSaveError,
    browser_profile_dir: profileDir,
    surface: surface.surface,
    reason,
    session_cookie_applied: cookieResult.applied,
    session_cookie_names: cookieResult.names,
    reward_task_title: parsed.taskTitle,
    reward_task_window: parsed.taskWindow,
    reward_progress_completed: parsed.completedCount,
    reward_progress_target: parsed.targetCount,
    reward_participation_confirmed: rewardConfirmed,
    activity_submission_counted: rewardCounted,
    verification_method: rewardConfirmed ? "task_center_progress" : "task_center_missing",
    article_title_hint: articleTitle,
    article_url_hint: articleUrl,
    task_page_excerpt: parsed.textExcerpt,
    evidence: {
      dir: evidenceDirFromArgs(args),
      snapshots: [evidence].filter(Boolean),
    },
  };
}

async function resolvePublishedArticleFromAuthorHome(runtime, page, articleTitle, preferredBlogHomeUrl = "") {
  const blogHomeUrl = String(preferredBlogHomeUrl || "").trim() || await resolveAuthorBlogHome(page);
  if (!blogHomeUrl) {
    return {
      confirmed: false,
      url: "",
      title: "",
      source: "",
    };
  }
  const lookupPage = await runtime.context.newPage();
  try {
    await lookupPage.goto(blogHomeUrl, {
      waitUntil: "domcontentloaded",
      timeout: 30000,
    });
    await lookupPage.waitForTimeout(2000);
    const extracted = await extractPublicArticleUrl(lookupPage, articleTitle);
    if (extracted.url) {
      return {
        confirmed: true,
        url: extracted.url,
        title: await lookupPage.title().catch(() => ""),
        source: `author_home:${extracted.source}`,
      };
    }
  } catch {
    return {
      confirmed: false,
      url: "",
      title: "",
      source: "",
    };
  } finally {
    await lookupPage.close().catch(() => null);
  }
  return {
    confirmed: false,
    url: "",
    title: "",
    source: "",
  };
}

async function resolvePublishedArticleFromManager(runtime, articleTitle) {
  const lookupPage = await runtime.context.newPage();
  try {
    await lookupPage.goto("https://blog.51cto.com/creative-center/manager", {
      waitUntil: "domcontentloaded",
      timeout: 30000,
    });
    await lookupPage.waitForTimeout(2000);
    const extracted = await extractPublicArticleUrl(lookupPage, articleTitle);
    if (extracted.url) {
      return {
        confirmed: true,
        url: extracted.url,
        title: await lookupPage.title().catch(() => ""),
        source: `manager:${extracted.source}`,
      };
    }
  } catch {
    return {
      confirmed: false,
      url: "",
      title: "",
      source: "",
    };
  } finally {
    await lookupPage.close().catch(() => null);
  }
  return {
    confirmed: false,
    url: "",
    title: "",
    source: "",
  };
}

async function persistState(context, stateFile) {
  let stateSaved = false;
  let stateSaveError = "";
  try {
    stateSaved = await writeStorageState(context, stateFile);
  } catch (error) {
    stateSaveError = String(error?.message || error);
  }
  return {
    stateSaved,
    stateSaveError,
  };
}

async function ensureEditorReady(page, timeoutMs) {
  let surface = await openPublishSurface(page, timeoutMs);
  const loginAttempt = {
    attempted: false,
    submitted: false,
    reason: "",
  };
  if (surface.surface === "login") {
    Object.assign(loginAttempt, await attemptPasswordLogin(page));
    if (loginAttempt.submitted) {
      surface = await waitForBootstrapSurface(page, timeoutMs);
    }
  }
  return {
    surface,
    loginAttempt,
  };
}

async function fillEditorTitle(page, title) {
  const match = await firstVisibleLocator(page, [
    "#title",
    "input#title",
    "input[placeholder*='标题']",
    "textarea[placeholder*='标题']",
  ]);
  if (!match) {
    return {
      filled: false,
      selector: "",
      method: "",
    };
  }
  const method = await setLocatorValue(match.locator, title);
  return {
    filled: true,
    selector: match.selector,
    method,
  };
}

async function fillEditorMarkdown(page, markdown) {
  const match = await firstVisibleLocator(page, [
    "textarea[placeholder='请输入正文']",
    "textarea[placeholder*='请输入正文']",
    "textarea",
  ]);
  if (!match) {
    return {
      filled: false,
      selector: "",
      method: "",
      waitMs: 0,
    };
  }
  const method = await setLocatorValue(match.locator, markdown);
  const waitMs = markdownImageWaitMs(markdown);
  await page.waitForTimeout(waitMs);
  return {
    filled: true,
    selector: match.selector,
    method,
    waitMs,
  };
}

async function waitForDialogSurface(context, selectors, timeoutMs, intervalMs = 250) {
  const deadline = Date.now() + Math.max(timeoutMs, intervalMs);
  while (Date.now() < deadline) {
    for (const candidatePage of context.pages()) {
      if (candidatePage.isClosed()) {
        continue;
      }
      const match = await firstVisibleLocator(candidatePage, selectors);
      if (match) {
        return {
          page: candidatePage,
          selector: match.selector,
        };
      }
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  return null;
}

async function openPublishDialog(context, page, timeoutMs) {
  const publishButton = await firstVisibleLocator(page, [
    "button.edit-submit",
    "button[class*='edit-submit']",
    "button:has-text('发布文章')",
    "text=发布文章",
  ]);
  if (!publishButton) {
    return {
      opened: false,
      selector: "",
      clickMode: "",
      modalSelector: "",
      readySelector: "",
      buttonEnabled: false,
      buttonText: "",
      buttonClassName: "",
      buttonDisabledAttr: "",
    };
  }

  const waitDeadline = Date.now() + Math.min(timeoutMs, 8000);
  while (Date.now() < waitDeadline) {
    const isEnabled = await publishButton.locator.isEnabled().catch(() => false);
    if (isEnabled) {
      break;
    }
    await page.waitForTimeout(250);
  }

  const buttonEnabled = await publishButton.locator.isEnabled().catch(() => false);
  const buttonText = await publishButton.locator.innerText().catch(() => "");
  const buttonClassName = await publishButton.locator.getAttribute("class").catch(() => "");
  const buttonDisabledAttr = await publishButton.locator.getAttribute("disabled").catch(() => "");

  const dialogSelectors = [
    ".editor-dialog__wrapper",
    ".dialog-editor",
    ".el-dialog:has-text('基础信息')",
    ".el-dialog__wrapper:has-text('基础信息')",
    ".el-drawer:has-text('基础信息')",
    ".el-popover:has-text('基础信息')",
    "form:has-text('基础信息')",
    "text=基础信息",
    "#submitForm",
    ".types-select-box",
    "#tag-input",
  ];
  const controlSelectors = [
    "#submitForm",
    ".editor-dialog__wrapper #submitForm",
    ".dialog-editor #submitForm",
    "#abstractData",
    ".types-select-box",
    "#tag-input",
    ".img-upload",
    "#selfType",
    "#aticleType",
  ];

  let clickMode = "";
  let dialogRoot = null;
  let readyControl = null;
  const clickAttempts = [
    async () => clickLocatorRobust(page, publishButton.locator),
    async () => {
      await publishButton.locator.click({ timeout: 3000, force: true });
      return "force";
    },
    async () => {
      const box = await publishButton.locator.boundingBox().catch(() => null);
      if (!box) {
        return "";
      }
      await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
      return "mouse";
    },
    async () => {
      await publishButton.locator.evaluate((node) => node.click());
      return "evaluate";
    },
  ];

  for (let index = 0; index < clickAttempts.length; index += 1) {
    clickMode = await clickAttempts[index]().catch(() => clickMode || "");
    await waitAndClickContinuePublishModal(page, 6000);
    const dialogSurface = await waitForDialogSurface(context, dialogSelectors, 20000, 250);
    if (dialogSurface) {
      dialogRoot = dialogSurface;
      break;
    }
    if (index === 0) {
      await page.keyboard.press("Tab").catch(() => null);
      await page.waitForTimeout(400);
    }
  }

  if (!dialogRoot) {
    await waitAndClickContinuePublishModal(page, 6000);
    const readyOnCurrentPage = await waitForVisibleLocator(page, controlSelectors, 20000, 250);
    if (readyOnCurrentPage) {
      dialogRoot = { page, selector: readyOnCurrentPage.selector };
    }
  }
  if (dialogRoot) {
    readyControl = await waitForVisibleLocator(dialogRoot.page, controlSelectors, 15000);
  }
  const dialogPage = dialogRoot?.page || page;
  return {
    opened: Boolean(dialogRoot && readyControl),
    selector: publishButton.selector,
    clickMode,
    modalSelector: dialogRoot?.selector || "",
    readySelector: readyControl?.selector || "",
    pageUrl: dialogPage.url(),
    pageTitle: await dialogPage.title().catch(() => ""),
    samePage: dialogPage === page,
    buttonEnabled,
    buttonText,
    buttonClassName,
    buttonDisabledAttr: buttonDisabledAttr || "",
    page: dialogPage,
  };
}

async function chooseArticleCategory(page, categoryHint) {
  const primaryHint = String(categoryHint || "").trim();
  const secondaryHint = String(arguments[2] || "").trim();
  const hints = buildTextHints(primaryHint);
  if (!hints.length) {
    return {
      applied: false,
      selector: "",
      matchedText: "",
      clickMode: "",
      primaryText: "",
      secondaryText: "",
      primaryReason: "article_category_missing",
      secondaryReason: "article_subcategory_missing",
      reason: "article_category_missing",
    };
  }

  const currentPrimary = await collectVisibleTexts(page, [
    "#oneLever .select_item_check",
    "#oneLever .select_item_check span",
  ]);
  let primary = null;
  for (const current of currentPrimary) {
    if (hints.some((hint) => normalizeText(current).includes(normalizeText(hint)))) {
      primary = {
        selector: "#oneLever .select_item_check",
        matchedText: current,
        clickMode: "already_selected",
      };
      break;
    }
  }
  if (!primary) {
    primary = await clickFirstMatchingText(
      page,
      [
        "#oneLever .select_item",
        "#oneLever .select_item span",
      ],
      hints,
    );
  }
  if (!primary) {
    return {
      applied: false,
      selector: "",
      matchedText: "",
      clickMode: "",
      primaryText: "",
      secondaryText: "",
      primaryReason: "article_category_option_not_found",
      secondaryReason: "article_subcategory_option_not_found",
      reason: "article_category_option_not_found",
    };
  }

  await page.waitForTimeout(600);
  const secondaryHints = buildTextHints(secondaryHint || primaryHint);
  const currentSecondary = await collectVisibleTexts(page, [
    "#twoLever .second-types-item-check",
    "#twoLever .second-types-item-check span",
  ]);
  let secondary = null;
  for (const current of currentSecondary) {
    if (secondaryHints.some((hint) => normalizeText(current).includes(normalizeText(hint)))) {
      secondary = {
        selector: "#twoLever .second-types-item-check",
        matchedText: current,
        clickMode: "already_selected",
      };
      break;
    }
  }
  if (!secondary) {
    secondary = await clickFirstMatchingText(
      page,
      [
        "#twoLever .second-types-item",
        "#twoLever .second-types-item span",
      ],
      secondaryHints,
    );
  }
  if (!secondary) {
    const secondOptions = await collectVisibleTexts(page, [
      "#twoLever .second-types-item",
      "#twoLever .second-types-item span",
    ]);
    if (secondOptions.length) {
      secondary = await clickFirstMatchingText(
        page,
        [
          "#twoLever .second-types-item",
          "#twoLever .second-types-item span",
        ],
        [secondOptions[0]],
      );
    }
  }
  return {
    applied: Boolean(primary && secondary),
    selector: secondary?.selector || primary.selector,
    matchedText: [primary.matchedText, secondary?.matchedText || ""].filter(Boolean).join(" / "),
    clickMode: secondary?.clickMode || primary.clickMode,
    primaryText: primary.matchedText,
    secondaryText: secondary?.matchedText || "",
    primaryReason: "",
    secondaryReason: secondary ? "" : "article_subcategory_option_not_found",
    reason: secondary ? "" : "article_subcategory_option_not_found",
  };
}

async function chooseBlogCategory(page, categoryHint) {
  const hints = buildTextHints(categoryHint);
  if (!hints.length) {
    return {
      applied: false,
      selector: "",
      matchedText: "",
      clickMode: "",
      openSelector: "",
      options: [],
      addControlVisible: false,
      reason: "blog_category_missing",
      manualBlocker: false,
    };
  }
  let options = [];
  let addControlVisible = false;

  const opener = await clickFirstVisibleRobust(page, [
    "#selfType",
    "input#selfType",
    ".classification.person-type input",
    "text=博主文章分类",
  ]);
  if (!opener) {
    return {
      applied: false,
      selector: "",
      matchedText: "",
      clickMode: "",
      openSelector: "",
      options,
      addControlVisible,
      reason: "blog_category_input_missing",
      manualBlocker: false,
    };
  }
  await page.waitForTimeout(800);
  options = await collectVisibleTexts(page, [
    "#selfType_list li",
    "#selfType_list li span",
    ".el-select-dropdown__item",
    ".el-select-dropdown__item span",
  ]);
  addControlVisible = await firstVisibleLocator(page, [
    ".person-type-add",
    "text=添加个人分类",
  ]).then((match) => Boolean(match)).catch(() => false);
  const selected = await clickFirstMatchingText(
    page,
    [
      "#selfType_list li",
      "#selfType_list li span",
      ".el-select-dropdown__item",
      ".el-select-dropdown__item span",
    ],
    hints,
  );
  const manualBlocker = !selected && !options.length && addControlVisible;
  return {
    applied: Boolean(selected),
    selector: selected?.selector || "",
    matchedText: selected?.matchedText || "",
    clickMode: selected?.clickMode || "",
    openSelector: opener.selector,
    options,
    addControlVisible,
    reason: manualBlocker
      ? "personal_category_missing_and_no_existing_personal_category"
      : (selected ? "" : "blog_category_option_not_found"),
    manualBlocker,
  };
}

async function applyTags(page, rawTags) {
  const tags = uniqueValues(Array.isArray(rawTags) ? rawTags.map((item) => String(item || "").trim()) : []);
  if (!tags.length) {
    return {
      applied: false,
      selector: "",
      tags,
      clearedAutoTags: false,
      reason: "tags_missing",
    };
  }
  const match = await firstVisibleLocator(page, [
    "#tag-input",
    "input#tag-input",
    "input[placeholder*='标签']",
  ]);
  if (!match) {
    return {
      applied: false,
      selector: "",
      tags,
      clearedAutoTags: false,
      reason: "tag_input_missing",
    };
  }

  const clearedAutoTags = await match.locator.evaluate((node) => {
    const chipContainer = node.previousElementSibling;
    if (!chipContainer) {
      return false;
    }
    chipContainer.innerHTML = "";
    return true;
  }).catch(() => false);

  await setLocatorValue(match.locator, "");
  for (const tag of tags) {
    await match.locator.fill(tag).catch(() => null);
    await page.waitForTimeout(250);
    await match.locator.press("Enter").catch(() => null);
    await page.waitForTimeout(400);
  }

  return {
    applied: true,
    selector: match.selector,
    tags,
    clearedAutoTags,
    reason: "",
  };
}

async function fillSummary(page, summary) {
  const text = String(summary || "").trim();
  if (!text) {
    return {
      filled: false,
      selector: "",
      method: "",
      reason: "summary_missing",
    };
  }
  const match = await firstVisibleLocator(page, [
    "#abstractData",
    "textarea#abstractData",
    "textarea[placeholder*='摘要']",
  ]);
  if (!match) {
    return {
      filled: false,
      selector: "",
      method: "",
      reason: "summary_input_missing",
    };
  }
  const method = await setLocatorValue(match.locator, text);
  return {
    filled: true,
    selector: match.selector,
    method,
    reason: "",
  };
}

async function chooseTopic(page, topicHint) {
  const hints = buildTextHints(topicHint);
  if (!hints.length) {
    return {
      applied: false,
      openSelector: "",
      selector: "",
      matchedText: "",
      reason: "topic_missing",
    };
  }
  const opener = await clickFirstVisibleRobust(page, [
    "#subjuct",
    "input#subjuct",
    "text=话题",
  ]);
  if (!opener) {
    return {
      applied: false,
      openSelector: "",
      selector: "",
      matchedText: "",
      reason: "topic_input_missing",
    };
  }
  await page.waitForTimeout(700);
  const selected = await clickFirstMatchingText(page, [
    "#listItemList li",
    "#listItemList li span",
    "li",
  ], hints);
  return {
    applied: Boolean(selected),
    openSelector: opener.selector,
    selector: selected?.selector || "",
    matchedText: selected?.matchedText || "",
    reason: selected ? "" : "topic_option_not_found",
  };
}

async function resolveBannerUploadFile(payload) {
  const bannerAsset = payload?.banner_asset && typeof payload.banner_asset === "object" ? payload.banner_asset : {};
  const sourcePath = String(bannerAsset.source_path || "").trim();
  if (sourcePath) {
    const absolutePath = path.isAbsolute(sourcePath) ? sourcePath : path.resolve(process.cwd(), sourcePath);
    await fs.access(absolutePath);
    return {
      path: absolutePath,
      source: "source_path",
      cleanupDir: "",
    };
  }

  const directUrl = String(bannerAsset.direct_url || "").trim();
  if (!directUrl) {
    return {
      path: "",
      source: "",
      cleanupDir: "",
      reason: "banner_asset_missing",
    };
  }

  const response = await fetch(directUrl);
  if (!response.ok) {
    return {
      path: "",
      source: "",
      cleanupDir: "",
      reason: `banner_download_failed_${response.status}`,
    };
  }
  const contentType = String(response.headers.get("content-type") || "").toLowerCase();
  const extension = contentType.includes("png")
    ? ".png"
    : (contentType.includes("webp") ? ".webp" : ".jpg");
  const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), "aimagician-51cto-banner-"));
  const filePath = path.join(tmpDir, `banner${extension}`);
  const buffer = Buffer.from(await response.arrayBuffer());
  await fs.writeFile(filePath, buffer);
  return {
    path: filePath,
    source: "direct_url",
    cleanupDir: tmpDir,
  };
}

async function findBannerFileInput(page) {
  const directSelectors = [
    ".form-list.img-upload input.upload_input[name='url']",
    ".img-upload input.upload_input[name='url']",
    ".img-upload input.upload_input",
    ".img-upload input[type='file'][name='url']",
  ];
  for (const selector of directSelectors) {
    const locator = page.locator(selector).first();
    const count = await locator.count().catch(() => 0);
    if (count > 0) {
      return {
        index: 0,
        id: "",
        name: "url",
        accept: "",
        className: "upload_input",
        nearbyText: "img-upload",
        score: 20,
        selector,
      };
    }
  }

  const inputs = await page.locator("input[type='file']").evaluateAll((nodes) => nodes.map((node, index) => {
    const container = node.closest("label, div, section, li, form") || node.parentElement || node;
    const nearbyText = (container?.innerText || "").replace(/\s+/g, " ").trim();
    return {
      index,
      id: node.id || "",
      name: node.getAttribute("name") || "",
      accept: node.getAttribute("accept") || "",
      className: String(node.className || ""),
      nearbyText,
    };
  })).catch(() => []);

  if (!inputs.length) {
    return null;
  }

  const scored = inputs
    .map((item) => {
      const haystack = normalizeText([item.id, item.name, item.accept, item.className, item.nearbyText].join(" "));
      let score = 0;
      if (haystack.includes("封面") || haystack.includes("banner") || haystack.includes("cover") || haystack.includes("头图")) {
        score += 8;
      }
      if (haystack.includes("image") || haystack.includes("jpg") || haystack.includes("png")) {
        score += 2;
      }
      if (haystack.includes("正文") || haystack.includes("插图")) {
        score -= 3;
      }
      return {
        ...item,
        score,
      };
    })
    .sort((left, right) => right.score - left.score);

  const best = scored[0];
  if (!best || (best.score <= 0 && scored.length > 1)) {
    return null;
  }
  return best;
}

async function selectBannerMode(page) {
  const selected = await clickFirstMatchingText(
    page,
    [
      ".img-upload label",
      ".img-upload span",
      ".img-upload .el-radio__label",
      ".img-upload .el-checkbox__label",
    ],
    ["单图"],
  );
  if (selected) {
    await page.waitForTimeout(900);
  }
  return {
    applied: Boolean(selected),
    selector: selected?.selector || "",
    matchedText: selected?.matchedText || "",
    clickMode: selected?.clickMode || "",
  };
}

async function uploadBanner(page, payload) {
  const bannerInBody = Boolean(
    payload?.banner_asset
      && typeof payload.banner_asset === "object"
      && String(payload.banner_asset.direct_url || "").trim()
      && String(payload.markdown || "").includes(String(payload.banner_asset.direct_url || "").trim()),
  );
  let bannerFile;
  try {
    bannerFile = await resolveBannerUploadFile(payload);
  } catch (error) {
    return {
      attempted: false,
      uploaded: false,
      reason: String(error?.message || error),
      selector: "",
      source: "",
      filePath: "",
      bannerInBody,
    };
  }

  if (!bannerFile?.path) {
    return {
      attempted: false,
      uploaded: false,
      reason: bannerFile?.reason || "banner_asset_missing",
      selector: "",
      source: bannerFile?.source || "",
      filePath: "",
      bannerInBody,
    };
  }

  try {
    const bannerMode = await selectBannerMode(page);
    const match = await findBannerFileInput(page);
    if (!match) {
      return {
        attempted: false,
        uploaded: false,
        reason: "banner_file_input_not_found",
        selector: "",
        source: bannerFile.source,
        filePath: bannerFile.path,
        bannerInBody,
        modeSelected: bannerMode.applied,
        modeSelector: bannerMode.selector,
      };
    }

    const locator = match.selector
      ? page.locator(match.selector).first()
      : page.locator("input[type='file']").nth(match.index);
    await locator.setInputFiles(bannerFile.path);
    await page.waitForTimeout(2500);
    const failure = await firstVisibleLocator(page, [
      "text=上传失败",
      "text=上传出错",
      "text=请重新上传",
    ]);
    return {
      attempted: true,
      uploaded: !failure,
      reason: failure ? "banner_upload_validation_failed" : "",
      selector: match.selector || `input[type='file']#${match.index}`,
      source: bannerFile.source,
      filePath: bannerFile.path,
      nearbyText: match.nearbyText,
      bannerInBody,
      modeSelected: bannerMode.applied,
      modeSelector: bannerMode.selector,
    };
  } finally {
    if (bannerFile.cleanupDir) {
      await fs.rm(bannerFile.cleanupDir, { recursive: true, force: true }).catch(() => null);
    }
  }
}

function inferArticleType(payload) {
  const copyright = normalizeText(payload?.copyright || "");
  if (copyright.includes("翻译")) {
    return "翻译";
  }
  if (copyright.includes("转载")) {
    return "转载";
  }
  return "原创";
}

function inferCopyrightNotice(payload) {
  const copyright = normalizeText(payload?.copyright || "");
  if (copyright.includes("授权")) {
    return "转载需作者授权";
  }
  if (copyright.includes("谢绝")) {
    return "谢绝转载";
  }
  return "转载请注明出处";
}

async function chooseSimpleDropdownOption(page, openSelectors, optionSelectors, desiredText) {
  const hints = buildTextHints(desiredText);
  if (!hints.length) {
    return {
      applied: false,
      openSelector: "",
      selector: "",
      matchedText: "",
      clickMode: "",
      reason: "dropdown_value_missing",
    };
  }
  const currentInput = await firstVisibleLocator(page, openSelectors).catch(() => null);
  if (currentInput) {
    const currentValue = (await currentInput.locator.inputValue().catch(() => ""))
      || (await currentInput.locator.innerText().catch(() => ""));
    if (currentValue && hints.some((hint) => normalizeText(currentValue).includes(normalizeText(hint)))) {
      return {
        applied: true,
        openSelector: currentInput.selector,
        selector: "",
        matchedText: currentValue,
        clickMode: "already_selected",
        reason: "",
      };
    }
  }
  const opener = await clickFirstVisibleRobust(page, openSelectors);
  if (!opener) {
    return {
      applied: false,
      openSelector: "",
      selector: "",
      matchedText: "",
      clickMode: "",
      reason: "dropdown_input_missing",
    };
  }
  await page.waitForTimeout(700);
  const selected = await clickFirstMatchingText(page, optionSelectors, hints);
  return {
    applied: Boolean(selected),
    openSelector: opener.selector,
    selector: selected?.selector || "",
    matchedText: selected?.matchedText || "",
    clickMode: selected?.clickMode || "",
    reason: selected ? "" : "dropdown_option_not_found",
  };
}

async function chooseArticleType(page, payload) {
  const desiredText = inferArticleType(payload);
  const result = await chooseSimpleDropdownOption(
    page,
    [
      "#aticleType",
      "input#aticleType",
      "text=文章类型",
    ],
    [
      ".el-select-dropdown__item",
      ".el-select-dropdown__item span",
      "li",
    ],
    desiredText,
  );
  return {
    ...result,
    desiredText,
  };
}

async function chooseCopyrightNotice(page, payload) {
  const desiredText = inferCopyrightNotice(payload);
  const result = await chooseSimpleDropdownOption(
    page,
    [
      "#staRe",
      "input#staRe",
      "text=版权声明",
    ],
    [
      ".el-select-dropdown__item",
      ".el-select-dropdown__item span",
      "li",
    ],
    desiredText,
  );
  return {
    ...result,
    desiredText,
  };
}

async function extractVisibleValidationMessages(page) {
  return collectVisibleTexts(page, [
    ".el-form-item__error",
    ".el-message",
    ".el-message__content",
    ".el-notification",
    ".el-notification__content",
    ".dialog-editor .error",
  ]);
}

async function clickFinalPublish(page) {
  let clicked = await clickFirstVisibleRobust(page, [
    "#submitForm",
    "button#submitForm",
    ".editor-dialog__wrapper button:has-text('发布')",
    ".dialog-editor button:has-text('发布')",
    ".el-dialog button:has-text('发布')",
    "button:has-text('发布')",
    "text=发布",
  ]);
  if (!clicked) {
    clicked = await clickContinuePublishModal(page);
  }
  const confirmation = await clickContinuePublishModal(page);
  return {
    clicked: Boolean(clicked),
    selector: clicked?.selector || "",
    clickMode: clicked?.clickMode || "",
    confirmationClicked: Boolean(confirmation),
    confirmationSelector: confirmation?.selector || "",
    confirmationClickMode: confirmation?.clickMode || "",
  };
}

async function clickContinuePublishModal(page) {
  const clicked = await clickFirstVisibleRobust(page, [
    ".el-message-box button:has-text('继续发布')",
    ".el-dialog button:has-text('继续发布')",
    ".editor-dialog__wrapper button:has-text('继续发布')",
    ".dialog-editor button:has-text('继续发布')",
    "button:has-text('继续发布')",
    "text=继续发布",
  ]);
  if (clicked) {
    await page.waitForTimeout(1500).catch(() => null);
  }
  return clicked;
}

async function waitAndClickContinuePublishModal(page, timeoutMs = 5000) {
  const deadline = Date.now() + Math.max(timeoutMs, 500);
  while (Date.now() < deadline) {
    const clicked = await clickContinuePublishModal(page);
    if (clicked) {
      return clicked;
    }
    await page.waitForTimeout(300).catch(() => null);
  }
  return null;
}

async function waitForPublishedArticle(runtime, page, articleTitle, timeoutMs) {
  const deadline = Date.now() + Math.max(timeoutMs, 45000);
  const authorBlogHomeUrl = await resolveAuthorBlogHome(page).catch(() => "");
  let lastUrl = page.url();
  let lastTitle = await page.title().catch(() => "");
  let successMarker = "";

  while (Date.now() < deadline) {
    for (const candidatePage of runtime.context.pages()) {
      if (candidatePage.isClosed()) {
        continue;
      }
      const candidateUrl = candidatePage.url();
      const candidateTitle = await candidatePage.title().catch(() => "");
      if (isPublicArticleUrl(candidateUrl)) {
        return {
          confirmed: true,
          url: candidateUrl,
          title: candidateTitle,
          source: "context_page_url",
        };
      }
      const extracted = await extractPublicArticleUrl(candidatePage, articleTitle);
      if (extracted.url) {
        return {
          confirmed: true,
          url: extracted.url,
          title: candidateTitle,
          source: extracted.source,
        };
      }
      const successMatch = await firstVisibleLocator(candidatePage, [
        "text=发布成功",
        "text=提交成功",
        "text=审核中",
        "text=发布完成",
      ]);
      if (successMatch) {
        successMarker = successMatch.selector;
      }
    }

    const dialogRoot = await firstVisibleLocator(page, [
      ".editor-dialog__wrapper",
      ".dialog-editor",
      "#submitForm",
    ]);
    if (dialogRoot) {
      const validationMessages = await extractVisibleValidationMessages(page);
      if (validationMessages.length) {
        return {
          confirmed: false,
          url: lastUrl,
          title: lastTitle,
          validationMessage: `dialog_validation:${validationMessages.join(" | ")}`,
          source: "dialog_validation",
          validationMessages,
        };
      }
    }

    lastUrl = page.isClosed() ? lastUrl : page.url();
    lastTitle = page.isClosed() ? lastTitle : await page.title().catch(() => lastTitle);
    const surface = page.isClosed()
      ? { surface: successMarker ? "success-closed" : "closed", manualClearanceRequired: false }
      : await detectSurface(page);
    if (surface.surface === "blocked") {
      return {
        confirmed: false,
        url: lastUrl,
        title: lastTitle,
        validationMessage: "edgeone_blocked_after_submit",
        source: "blocked_surface",
      };
    }
    if (surface.surface === "success-closed" && successMarker) {
      const successPageResult = await resolvePublishedArticleFromSuccessPage(page, lastUrl, authorBlogHomeUrl);
      if (successPageResult.confirmed) {
        return successPageResult;
      }
      const managerResult = await resolvePublishedArticleFromManager(runtime, articleTitle);
      if (managerResult.confirmed) {
        return managerResult;
      }
      const authorHomeResult = await resolvePublishedArticleFromAuthorHome(runtime, page, articleTitle, authorBlogHomeUrl);
      if (authorHomeResult.confirmed) {
        return authorHomeResult;
      }
      return {
        confirmed: true,
        url: lastUrl,
        title: lastTitle,
        validationMessage: "",
        source: "success_marker_before_page_closed",
      };
    }

    if (page.isClosed()) {
      break;
    }
    await page.waitForTimeout(1500).catch(() => null);
  }

  const successPageResult = await resolvePublishedArticleFromSuccessPage(page, lastUrl, authorBlogHomeUrl);
  if (successPageResult.confirmed) {
    return successPageResult;
  }
  const managerResult = await resolvePublishedArticleFromManager(runtime, articleTitle);
  if (managerResult.confirmed) {
    return managerResult;
  }
  const authorHomeResult = await resolvePublishedArticleFromAuthorHome(runtime, page, articleTitle, authorBlogHomeUrl);
  if (authorHomeResult.confirmed) {
    return authorHomeResult;
  }

  return {
    confirmed: false,
    url: isSuccessPageUrl(lastUrl) ? "" : lastUrl,
    title: lastTitle,
    validationMessage: successMarker
      ? `success_marker_seen_without_public_url:${successMarker}`
      : "public_url_not_resolved",
    source: successMarker ? "success_marker_without_url" : "timeout",
  };
}

function resolvePublishWaitTimeoutMs(args, timeoutMs) {
  const configured = Number.parseInt(
    String(args["publish-wait-ms"] || process.env.CTO51_PUBLISH_WAIT_MS || "180000"),
    10,
  );
  const fallback = 180000;
  const waitMs = Number.isFinite(configured) && configured > 0 ? configured : fallback;
  return Math.max(45000, Math.min(waitMs, timeoutMs));
}

async function prepareArticle(runtime, args, stateFile, timeoutMs, payload, submit) {
  const { context, page, profileDir } = runtime;
  if (!payload || typeof payload !== "object") {
    throw new Error("missing_publish_payload");
  }

  const title = String(payload.title || "").trim();
  const markdown = normalizeMultilineText(payload.markdown || "");
  if (!title || !markdown) {
    throw new Error("payload_missing_title_or_markdown");
  }

  const cookieResult = await injectSessionCookies(context);
  await checkpointProgress(args, "prepare_article_open_publish_surface", {
    profile_dir: profileDir,
    cookie_names: cookieResult.names,
    submit_requested: submit,
  });

  const editorReady = await ensureEditorReady(page, timeoutMs);
  let { surface, loginAttempt } = editorReady;
  if (surface.surface !== "editor") {
    const persisted = await persistState(context, stateFile);
    const reason = inferBlockedReason(surface, loginAttempt);
    const evidence = await capturePageEvidence(page, args, "prepare-article-blocked", {
      surface: surface.surface,
      reason,
      submit_requested: submit,
    });
    return {
      status: "blocked",
      mode: "prepare-article",
      live_ready: false,
      final_url: surface.url || page.url(),
      page_title: surface.title || await page.title().catch(() => ""),
      state_file: stateFile,
      state_file_written: persisted.stateSaved,
      state_file_write_error: persisted.stateSaveError,
      browser_profile_dir: profileDir,
      surface: surface.surface,
      reason,
      session_cookie_applied: cookieResult.applied,
      session_cookie_names: cookieResult.names,
      credential_login_attempted: loginAttempt.attempted,
      credential_login_submitted: loginAttempt.submitted,
      manual_clearance_required: surface.manualClearanceRequired || Boolean(loginAttempt.submitted),
      publish_requested: submit,
      publish_confirmed: false,
      evidence: {
        dir: evidenceDirFromArgs(args),
        snapshots: [evidence].filter(Boolean),
      },
    };
  }

  await checkpointProgress(args, "prepare_article_fill_editor", {
    final_url: page.url(),
    title,
  });

  const titleFill = await fillEditorTitle(page, title);
  const markdownFill = await fillEditorMarkdown(page, markdown);
  const dialog = await openPublishDialog(context, page, timeoutMs);
  const metadataPage = dialog.page || page;
  const articleType = await chooseArticleType(metadataPage, payload);
  const copyrightNotice = await chooseCopyrightNotice(metadataPage, payload);
  const category = await chooseArticleCategory(
    metadataPage,
    payload.article_category_hint || payload.article_category || "",
    payload.article_subcategory_hint || "",
  );
  const blogCategory = await chooseBlogCategory(metadataPage, payload.blog_category_hint || payload.blog_category || "");
  const tagsApplied = await applyTags(metadataPage, payload.tags);
  const summary = await fillSummary(metadataPage, payload.abstract || payload.summary || "");
  const topic = await chooseTopic(metadataPage, payload.topic || payload.topic_hint || payload.primary_tag || "");
  const bannerUpload = await uploadBanner(metadataPage, payload);
  const draftUrl = page.url();
  const readinessIssues = [];
  if (!titleFill.filled) {
    readinessIssues.push("title_input_missing");
  }
  if (!markdownFill.filled) {
    readinessIssues.push("editor_textarea_missing");
  }
  if (!dialog.opened) {
    readinessIssues.push("publish_dialog_not_opened");
  }
  if (!articleType.applied) {
    readinessIssues.push(articleType.reason || "article_type_option_not_found");
  }
  if (!copyrightNotice.applied) {
    readinessIssues.push(copyrightNotice.reason || "copyright_notice_option_not_found");
  }
  if (!category.applied) {
    readinessIssues.push(category.reason || "article_category_option_not_found");
  }
  if (!tagsApplied.applied) {
    readinessIssues.push(tagsApplied.reason || "tag_input_missing");
  }
  if (!summary.filled) {
    readinessIssues.push(summary.reason || "summary_input_missing");
  }

  let publishConfirmed = false;
  let publishValidationReason = "";
  let publishedArticleUrl = "";
  let publishResolutionSource = "";
  let publishedPageTitle = "";
  let validationMessages = [];
  let finalPublish = {
    clicked: false,
    selector: "",
    clickMode: "",
  };

  if (submit && !dialog.opened) {
    publishValidationReason = "publish_dialog_not_opened";
  } else if (submit) {
    await checkpointProgress(args, "prepare_article_submit_publish", {
      category_applied: category.applied,
      blog_category_applied: blogCategory.applied,
      tags_applied: tagsApplied.applied,
      banner_uploaded: bannerUpload.uploaded,
      summary_filled: summary.filled,
    });
    finalPublish = await clickFinalPublish(metadataPage);
    if (!finalPublish.clicked) {
      publishValidationReason = "final_publish_button_missing";
    } else {
      const publishWaitMs = resolvePublishWaitTimeoutMs(args, timeoutMs);
      await checkpointProgress(args, "prepare_article_wait_public_url", {
        publish_wait_ms: publishWaitMs,
        full_timeout_ms: timeoutMs,
      });
      const publishResult = await waitForPublishedArticle(runtime, page, title, publishWaitMs);
      publishConfirmed = publishResult.confirmed;
      publishValidationReason = publishResult.confirmed
        ? ""
        : String(publishResult.validationMessage || "public_url_not_resolved");
      publishedArticleUrl = String(publishResult.url || "").trim();
      publishResolutionSource = String(publishResult.source || "").trim();
      publishedPageTitle = String(publishResult.title || "").trim();
      validationMessages = Array.isArray(publishResult.validationMessages) ? publishResult.validationMessages : [];
    }
  }

  const persisted = await persistState(context, stateFile);
  const finalSurface = await detectSurface(page);
  const liveReady = finalSurface.surface === "editor" || publishConfirmed;
  const finalReason = submit
    ? (publishConfirmed ? "" : (publishValidationReason || readinessIssues[0] || inferBlockedReason(finalSurface, loginAttempt)))
    : (readinessIssues[0] || "");
  const evidence = await capturePageEvidence(
    page,
    args,
    submit ? (publishConfirmed ? "submit-success" : "submit-blocked") : "prepare-article-ready",
    {
      surface: finalSurface.surface,
      submit_requested: submit,
      publish_confirmed: publishConfirmed,
      public_url: publishedArticleUrl,
      publish_validation_reason: publishValidationReason,
      manual_clearance_required: finalSurface.manualClearanceRequired || Boolean(loginAttempt.submitted && !publishConfirmed),
    },
  );

  return {
    status: finalReason ? "blocked" : "ok",
    mode: "prepare-article",
    live_ready: liveReady,
    final_url: publishedArticleUrl || page.url(),
    public_url: publishedArticleUrl,
    draft_url: draftUrl,
    page_title: publishedPageTitle || await page.title().catch(() => ""),
    state_file: stateFile,
    state_file_written: persisted.stateSaved,
    state_file_write_error: persisted.stateSaveError,
    browser_profile_dir: profileDir,
    surface: finalSurface.surface,
    reason: finalReason,
    session_cookie_applied: cookieResult.applied,
    session_cookie_names: cookieResult.names,
    credential_login_attempted: loginAttempt.attempted,
    credential_login_submitted: loginAttempt.submitted,
    manual_clearance_required: finalSurface.manualClearanceRequired || Boolean(loginAttempt.submitted && !publishConfirmed),
    title_filled: titleFill.filled,
    title_selector: titleFill.selector,
    title_fill_method: titleFill.method,
    markdown_filled: markdownFill.filled,
    markdown_selector: markdownFill.selector,
    markdown_fill_method: markdownFill.method,
    markdown_wait_ms: markdownFill.waitMs,
    publish_dialog_opened: dialog.opened,
    publish_dialog_selector: dialog.selector,
    publish_dialog_click_mode: dialog.clickMode,
    publish_dialog_modal_selector: dialog.modalSelector,
    publish_dialog_ready_selector: dialog.readySelector,
    publish_dialog_page_url: dialog.pageUrl,
    publish_dialog_page_title: dialog.pageTitle,
    publish_dialog_same_page: dialog.samePage,
    publish_button_enabled: dialog.buttonEnabled,
    publish_button_text: dialog.buttonText,
    publish_button_class_name: dialog.buttonClassName,
    publish_button_disabled_attr: dialog.buttonDisabledAttr,
    article_type_applied: articleType.applied,
    article_type_text: articleType.matchedText || articleType.desiredText,
    article_type_reason: articleType.reason,
    article_type_selector: articleType.selector,
    article_type_open_selector: articleType.openSelector,
    copyright_notice_applied: copyrightNotice.applied,
    copyright_notice_text: copyrightNotice.matchedText || copyrightNotice.desiredText,
    copyright_notice_reason: copyrightNotice.reason,
    copyright_notice_selector: copyrightNotice.selector,
    copyright_notice_open_selector: copyrightNotice.openSelector,
    article_category_applied: category.applied,
    article_category_text: category.matchedText,
    article_category_reason: category.reason,
    article_category_primary_text: category.primaryText,
    article_category_secondary_text: category.secondaryText,
    article_category_primary_reason: category.primaryReason,
    article_category_secondary_reason: category.secondaryReason,
    blog_category_applied: blogCategory.applied,
    blog_category_text: blogCategory.matchedText,
    blog_category_reason: blogCategory.reason,
    blog_category_options: blogCategory.options,
    blog_category_add_control_visible: blogCategory.addControlVisible,
    blog_category_manual_blocker: blogCategory.manualBlocker,
    tags_applied: tagsApplied.applied,
    tags: tagsApplied.tags,
    tags_selector: tagsApplied.selector,
    auto_tags_cleared: tagsApplied.clearedAutoTags,
    summary_filled: summary.filled,
    summary_selector: summary.selector,
    summary_fill_method: summary.method,
    topic_applied: topic.applied,
    topic_text: topic.matchedText,
    topic_reason: topic.reason,
    banner_upload_attempted: bannerUpload.attempted,
    banner_uploaded: bannerUpload.uploaded,
    banner_upload_reason: bannerUpload.reason,
    banner_upload_source: bannerUpload.source,
    banner_input_selector: bannerUpload.selector,
    banner_mode_selected: bannerUpload.modeSelected,
    banner_mode_selector: bannerUpload.modeSelector,
    banner_in_body: bannerUpload.bannerInBody,
    publish_requested: submit,
    final_publish_clicked: finalPublish.clicked,
    final_publish_selector: finalPublish.selector,
    final_publish_click_mode: finalPublish.clickMode,
    final_publish_confirmation_clicked: finalPublish.confirmationClicked,
    final_publish_confirmation_selector: finalPublish.confirmationSelector,
    final_publish_confirmation_click_mode: finalPublish.confirmationClickMode,
    publish_confirmed: publishConfirmed,
    publish_validation_reason: publishValidationReason,
    publish_validation_messages: validationMessages,
    published_article_url: publishedArticleUrl,
    publish_resolution_source: publishResolutionSource,
    evidence: {
      dir: evidenceDirFromArgs(args),
      snapshots: [evidence].filter(Boolean),
    },
  };
}

async function detectSurface(page) {
  const url = page.url();
  const title = await page.title().catch(() => "");
  const loginMatch = await firstVisibleLocator(page, [
    "input#loginform-username",
    "input#loginform-password",
    "text=密码登录",
    "text=短信登录",
    "text=微信登录",
  ]);
  const blockedMatch = await firstVisibleLocator(page, [
    "text=请求已被站点的安全策略拦截",
    "text=请求已被拦截",
    "text=EdgeOne",
  ]);
  const editorMatch = await firstVisibleLocator(page, [
    "text=发布文章",
    "#title",
    "input[placeholder*='标题']",
    "textarea[placeholder*='标题']",
    "textarea[placeholder*='请输入正文']",
    "[contenteditable='true']",
    "text=创作中心",
  ]);
  const sliderMatch = await firstVisibleLocator(page, [
    "text=请按住滑块，拖动到最右边",
    "#nc_1_n1z",
    "#nc_1_captcha_input",
  ]);
  const agreementMatch = await firstVisibleLocator(page, [
    "#agree-check",
    "#agree",
    "label:has-text('我已经认真阅读并同意')",
  ]);

  let surface = "unknown";
  if (blockedMatch || title.includes("请求已被拦截") || url.includes("edgeone")) {
    surface = "blocked";
  } else if (loginMatch || url.includes("home.51cto.com/index")) {
    surface = "login";
  } else if (editorMatch || url.includes("/blogger/publish")) {
    surface = "editor";
  } else if (url.includes("login-success")) {
    surface = "login-success";
  }

  return {
    surface,
    url,
    title,
    loginSelector: loginMatch?.selector || "",
    editorSelector: editorMatch?.selector || "",
    blockedSelector: blockedMatch?.selector || "",
    sliderSelector: sliderMatch?.selector || "",
    agreementSelector: agreementMatch?.selector || "",
    manualClearanceRequired: Boolean(sliderMatch),
  };
}

async function openPublishSurface(page, timeoutMs) {
  await page.goto("https://www.51cto.com/", { waitUntil: "domcontentloaded", timeout: timeoutMs }).catch(() => null);
  await page.waitForTimeout(2000);
  await page.goto(DEFAULT_PUBLISH_URL, { waitUntil: "domcontentloaded", timeout: timeoutMs }).catch(() => null);
  await page.waitForTimeout(3000);
  if ((await detectSurface(page)).surface === "blocked") {
    await page.goto(DEFAULT_PUBLISH_URL, { timeout: timeoutMs }).catch(() => null);
    await page.waitForTimeout(2000);
  }
  return detectSurface(page);
}

async function clickAgreementIfNeeded(page) {
  return clickFirstVisible(page, [
    "#agree-check",
    "#agree",
    "label:has-text('我已经认真阅读并同意')",
  ]).catch(() => null);
}

async function switchToPasswordLogin(page) {
  return clickFirstVisible(page, [
    ".login-type-switch:has-text('密码登录')",
    "span.login-type-switch:has-text('密码登录')",
    "text=密码登录",
  ]).catch(() => null);
}

async function attemptPasswordLogin(page) {
  if (!CTO51_USERNAME || !CTO51_PASSWORD) {
    return {
      attempted: false,
      submitted: false,
      reason: "credentials_missing",
    };
  }

  const passwordTabSelector = await switchToPasswordLogin(page);
  if (passwordTabSelector) {
    await page.waitForTimeout(600);
  }
  await clickAgreementIfNeeded(page);
  const usernameSelector = await fillFirstVisible(page, [
    "input#loginform-username",
    "input[name='LoginForm[username]']",
    "input[placeholder='用户名/邮箱/手机']",
  ], CTO51_USERNAME);
  const passwordSelector = await fillFirstVisible(page, [
    "input#loginform-password",
    "input[name='LoginForm[password]']",
    "input[placeholder='密码']",
  ], CTO51_PASSWORD);

  if (!usernameSelector || !passwordSelector) {
    return {
      attempted: true,
      submitted: false,
      reason: "login_fields_missing",
      passwordTabSelector,
      usernameSelector,
      passwordSelector,
    };
  }

  const submitSelector = await clickFirstVisible(page, [
    "input[name='login-button']",
    "input.loginbtn_P",
    "button:has-text('登录')",
    "text=登录",
  ]);
  await page.waitForTimeout(1800);
  return {
    attempted: true,
    submitted: Boolean(submitSelector),
    reason: submitSelector ? "" : "login_submit_missing",
    passwordTabSelector,
    usernameSelector,
    passwordSelector,
    submitSelector: submitSelector || "",
  };
}

async function waitForBootstrapSurface(page, timeoutMs) {
  const deadline = Date.now() + Math.max(timeoutMs, 45000);
  let lastSurface = await detectSurface(page);
  while (Date.now() < deadline) {
    lastSurface = await detectSurface(page);
    if (lastSurface.surface === "editor" || lastSurface.surface === "blocked") {
      return lastSurface;
    }
    await page.waitForTimeout(1000);
  }
  return lastSurface;
}

async function bootstrapSession(runtime, args, stateFile, timeoutMs) {
  const { context, page, profileDir } = runtime;
  const cookieResult = await injectSessionCookies(context);
  await checkpointProgress(args, "open_publish_surface", {
    profile_dir: profileDir,
    cookie_names: cookieResult.names,
  });

  let surface = await openPublishSurface(page, timeoutMs);
  const loginAttempt = {
    attempted: false,
    submitted: false,
    reason: "",
  };

  if (surface.surface === "login") {
    Object.assign(loginAttempt, await attemptPasswordLogin(page));
    await checkpointProgress(args, "await_manual_clearance", {
      surface: surface.surface,
      final_url: page.url(),
      credential_login_attempted: loginAttempt.attempted,
      credential_login_submitted: loginAttempt.submitted,
      manual_clearance_required: Boolean(loginAttempt.submitted),
      login_reason: loginAttempt.reason || "",
    });
    if (loginAttempt.submitted) {
      surface = await waitForBootstrapSurface(page, timeoutMs);
    }
  }

  let stateSaved = false;
  let stateSaveError = "";
  try {
    stateSaved = await writeStorageState(context, stateFile);
  } catch (error) {
    stateSaveError = String(error?.message || error);
  }

  const liveReady = surface.surface === "editor";
  const reason = liveReady ? "" : inferBlockedReason(surface, loginAttempt);

  return {
    status: liveReady ? "ok" : "blocked",
    mode: "bootstrap-session",
    live_ready: liveReady,
    final_url: surface.url || page.url(),
    page_title: surface.title || await page.title().catch(() => ""),
    state_file: stateFile,
    state_file_written: stateSaved,
    state_file_write_error: stateSaveError,
    browser_profile_dir: profileDir,
    surface: surface.surface,
    reason,
    session_cookie_applied: cookieResult.applied,
    session_cookie_names: cookieResult.names,
    credential_login_attempted: loginAttempt.attempted,
    credential_login_submitted: loginAttempt.submitted,
    manual_clearance_required: surface.manualClearanceRequired || Boolean(loginAttempt.submitted && !liveReady),
  };
}

async function checkSession(runtime, args, stateFile, timeoutMs) {
  const { context, page, profileDir } = runtime;
  const cookieResult = await injectSessionCookies(context);
  await checkpointProgress(args, "check_session_open_publish", {
    profile_dir: profileDir,
    cookie_names: cookieResult.names,
  });

  const surface = await openPublishSurface(page, timeoutMs);
  let stateSaved = false;
  let stateSaveError = "";
  try {
    stateSaved = await writeStorageState(context, stateFile);
  } catch (error) {
    stateSaveError = String(error?.message || error);
  }
  const liveReady = surface.surface === "editor";
  let reason = "";
  if (!liveReady) {
    if (surface.surface === "blocked") {
      reason = "edgeone_blocked";
    } else if (surface.manualClearanceRequired) {
      reason = "manual_clearance_required";
    } else {
      reason = "session_invalid_or_missing";
    }
  }
  return {
    status: liveReady ? "ok" : "blocked",
    mode: "check-session",
    live_ready: liveReady,
    final_url: surface.url || page.url(),
    page_title: surface.title || await page.title().catch(() => ""),
    state_file: stateFile,
    state_file_written: stateSaved,
    state_file_write_error: stateSaveError,
    browser_profile_dir: profileDir,
    surface: surface.surface,
    reason,
    session_cookie_applied: cookieResult.applied,
    session_cookie_names: cookieResult.names,
    manual_clearance_required: surface.manualClearanceRequired,
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const action = String(args.action || "bootstrap-session");
  const stateFile = path.resolve(String(args["state-file"] || path.resolve(__dirname, "credentials/51cto-session-state.json")));
  const timeoutMs = Number.parseInt(String(args["timeout-ms"] || "45000"), 10);
  const headless = parseBool(args.headless, action === "check-session");
  const payloadFile = args["payload-file"] ? path.resolve(String(args["payload-file"])) : "";
  const submit = parseBool(args.submit, false);
  let payload = null;
  if (payloadFile) {
    payload = await loadJsonFile(payloadFile);
  }

  let runtime;
  let result;
  try {
    runtime = await launch51ctoContext({
      headless,
      stateFile,
      preferPersistent: true,
    });
    if (action === "bootstrap-session") {
      result = await bootstrapSession(runtime, args, stateFile, timeoutMs);
    } else if (action === "check-session") {
      result = await checkSession(runtime, args, stateFile, timeoutMs);
    } else if (action === "check-activity") {
      result = await checkRewardActivities(runtime, args, stateFile, timeoutMs);
    } else if (action === "verify-reward") {
      result = await verifyRewardParticipation(runtime, args, stateFile, timeoutMs, payload);
    } else if (action === "prepare-article") {
      result = await prepareArticle(runtime, args, stateFile, timeoutMs, payload, submit);
    } else {
      result = {
        status: "error",
        reason: `unsupported action: ${action}`,
        mode: action,
        payload_present: Boolean(payload),
      };
    }
  } catch (error) {
    result = {
      status: "error",
      reason: String(error?.message || error),
      mode: action,
    };
  } finally {
    if (runtime) {
      await closeRuntime(runtime).catch(() => null);
    }
  }

  await checkpointResult(args, result);
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  if (result.status === "error") {
    process.exitCode = 1;
  } else if (result.status === "blocked") {
    process.exitCode = 1;
  }
}

await main();
