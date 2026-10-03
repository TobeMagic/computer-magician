import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { clearStaleChromiumSingletonLocks } from "./profile_lock.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DEFAULT_PROFILE_DIR = path.resolve(__dirname, "credentials/bilibili-column-browser-profile");
const DEFAULT_PHONE_NUMBER = normalizeText(process.env.AIMAGICIAN_PLATFORM_LOGIN_PHONE || "13431877826");
const DEFAULT_SMS_CODE_FILE = process.env.BILIBILI_COLUMN_SMS_CODE_FILE
  || path.resolve(__dirname, "credentials/bilibili-column-sms-code.txt");
const DEFAULT_LOGIN_URL = process.env.BILIBILI_COLUMN_LOGIN_URL || "https://passport.bilibili.com/login";
const DEFAULT_CREATOR_HOME_URL = process.env.BILIBILI_COLUMN_CREATOR_HOME_URL || "https://member.bilibili.com/platform/home";
const DEFAULT_EDITOR_URL = process.env.BILIBILI_COLUMN_EDITOR_URL || "https://member.bilibili.com/platform/upload/text/edit";
const DEFAULT_LOCALE = process.env.BILIBILI_COLUMN_BROWSER_LOCALE || "zh-CN";
const DEFAULT_TIMEZONE = process.env.BILIBILI_COLUMN_BROWSER_TIMEZONE || "Asia/Shanghai";
const DEFAULT_VIEWPORT = { width: 1440, height: 960 };
const DEFAULT_USER_AGENT = process.env.BILIBILI_COLUMN_BROWSER_USER_AGENT
  || "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36";
const DEFAULT_BROWSER_ATTACH_URL = String(
  process.env.BILIBILI_COLUMN_BROWSER_ATTACH_URL || process.env.BILIBILI_COLUMN_BROWSER_CDP_URL || "",
).trim();
const DEFAULT_BROWSER_CHANNEL = String(process.env.BILIBILI_COLUMN_BROWSER_CHANNEL || "").trim();
const DEFAULT_BROWSER_EXECUTABLE_PATH = String(process.env.BILIBILI_COLUMN_BROWSER_EXECUTABLE_PATH || "").trim();
const DEFAULT_BROWSER_SHIM_AUTOMATION = parseBool(
  process.env.BILIBILI_COLUMN_BROWSER_SHIM_AUTOMATION,
  false,
);
const SESSION_PROBE_URL = "https://api.bilibili.com/x/web-interface/nav";
const AUTHOR_PROBE_URL = "https://api.bilibili.com/x/article/is_author";
const ARTICLE_LIST_URL = "https://api.bilibili.com/x/article/creative/article/list?pn=1&ps=20";
const OPUS_CREATION_LIST_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/creationlist?ps=10&pn=1&classification_type=0&creation_type=0&web_location=333.1374";
const MANUAL_CLEARANCE_MARKERS = [
  "安全验证",
  "验证后继续",
  "滑块验证",
  "拼图验证",
  "人机验证",
  "异常访问",
  "账号异常",
  "需要验证",
  "请完成验证",
  "风控",
];
const SMS_CHALLENGE_MARKERS = [
  "请在下图依次点击",
  "关闭验证",
  "刷新验证",
  "点击验证",
  "拖动滑块",
  "验证并登录",
];
const LOGIN_HINT_MARKERS = [
  "登录",
  "注册",
  "扫码登录",
  "手机号",
  "密码",
  "短信登录",
  "手机验证码",
];
const PUBLISH_SUCCESS_MARKERS = [
  "发布成功",
  "投稿成功",
  "提交成功",
  "已发布",
  "审核中",
  "专栏已发布",
];
const DRAFT_SUCCESS_MARKERS = [
  "保存成功",
  "保存草稿成功",
  "已保存到草稿",
  "草稿已保存",
];
const DAILY_LIMIT_MARKERS = [
  "已达到当日投稿上限",
  "只能保存草稿",
  "投稿上限",
];
const VALIDATION_MARKERS = [
  "标题不能为空",
  "请输入标题",
  "请填写标题",
  "摘要不能为空",
  "请填写摘要",
  "请选择标签",
  "标签不能为空",
  "请选择分区",
  "请上传封面",
  "请完善封面",
  "内容不能为空",
  "发布失败",
];
const PUBLIC_URL_PATTERN = /^https:\/\/www\.bilibili\.com\/(?:read\/cv\d+|opus\/\d+)\/?$/i;

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

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function uniqueNormalizedList(values) {
  const seen = new Set();
  const result = [];
  for (const value of Array.isArray(values) ? values : []) {
    const normalized = normalizeText(value);
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    result.push(normalized);
  }
  return result;
}

function findMarker(bodyText, markers) {
  return markers.find((marker) => bodyText.includes(marker)) || "";
}

async function readOptionalTrimmedFile(filePath) {
  if (!filePath) {
    return "";
  }
  try {
    return String(await fs.readFile(filePath, "utf8")).trim();
  } catch {
    return "";
  }
}

function sanitizeFileStem(value) {
  return String(value || "")
    .trim()
    .replace(/[^a-z0-9._-]+/gi, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 80) || "bilibili-column";
}

function evidenceDirFromArgs(args) {
  const raw = String(args["evidence-dir"] || "").trim();
  return raw ? path.resolve(raw) : "";
}

async function writeJson(jsonPath, value) {
  await fs.mkdir(path.dirname(jsonPath), { recursive: true });
  await fs.writeFile(jsonPath, JSON.stringify(value, null, 2), "utf8");
}

async function checkpointResult(args, value) {
  const outputFile = String(args["output-file"] || "").trim();
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

async function capturePageEvidence(page, args, label, extra = {}) {
  const evidenceDir = evidenceDirFromArgs(args);
  const pageClosed = !page || (typeof page.isClosed === "function" ? page.isClosed() : false);
  if (!evidenceDir || pageClosed) {
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
  const frameTexts = [];
  const frames = typeof page.frames === "function" ? page.frames() : [page];
  for (const frame of frames) {
    const locator = typeof frame.locator === "function" ? frame.locator("body") : null;
    const text = locator ? await locator.innerText().catch(() => "") : "";
    if (text) {
      frameTexts.push(text);
    }
  }
  const bodyText = frameTexts.join("\n");
  const payload = {
    label,
    url: page.url(),
    page_title: await page.title().catch(() => ""),
    body_excerpt: bodyText.slice(0, 6000),
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

async function collectPageSignals(page) {
  const pageClosed = !page || (typeof page.isClosed === "function" ? page.isClosed() : false);
  if (pageClosed) {
    return {
      bodyExcerpt: "",
      manualClearanceRequired: false,
      manualClearanceMarker: "",
      smsChallengeRequired: false,
      smsChallengeMarker: "",
      dailySubmissionLimitReached: false,
      dailySubmissionLimitMarker: "",
      publishSuccessSeen: false,
      draftSaved: false,
      validationMessage: "",
      loginHintSeen: false,
      loginHintMarker: "",
    };
  }
  const frameTexts = [];
  const frames = typeof page.frames === "function" ? page.frames() : [page];
  for (const frame of frames) {
    const locator = typeof frame.locator === "function" ? frame.locator("body") : null;
    const text = locator ? await locator.innerText().catch(() => "") : "";
    if (text) {
      frameTexts.push(text);
    }
  }
  const bodyText = frameTexts.join("\n");
  const successDialogVisible = Boolean(await firstVisibleLocatorAcrossFrames(page, [
    "text=你的专栏已提交成功",
    "text=专栏已提交成功",
    "text=投稿成功",
    "button:has-text('点击去看')",
    "button:has-text('立即查看')",
  ], { timeout: 300 }).catch(() => null));
  const smsChallengeMarker = findMarker(bodyText, SMS_CHALLENGE_MARKERS);
  const dailySubmissionLimitMarker = findMarker(bodyText, DAILY_LIMIT_MARKERS);
  const manualClearanceMarker = smsChallengeMarker || findMarker(bodyText, MANUAL_CLEARANCE_MARKERS);
  const validationMessage = findMarker(bodyText, VALIDATION_MARKERS);
  const loginHintMarker = findMarker(bodyText, LOGIN_HINT_MARKERS);
  return {
    bodyExcerpt: bodyText.slice(0, 6000),
    manualClearanceRequired: Boolean(manualClearanceMarker) && !dailySubmissionLimitMarker,
    manualClearanceMarker,
    smsChallengeRequired: Boolean(smsChallengeMarker),
    smsChallengeMarker,
    dailySubmissionLimitReached: Boolean(dailySubmissionLimitMarker),
    dailySubmissionLimitMarker,
    publishSuccessSeen: successDialogVisible || PUBLISH_SUCCESS_MARKERS.some((marker) => bodyText.includes(marker)),
    draftSaved: DRAFT_SUCCESS_MARKERS.some((marker) => bodyText.includes(marker)),
    validationMessage,
    loginHintSeen: Boolean(loginHintMarker),
    loginHintMarker,
  };
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
  return process.env.BILIBILI_COLUMN_BROWSER_PROFILE_DIR || DEFAULT_PROFILE_DIR;
}

async function launchBilibiliContext(options) {
  const {
    headless,
    stateFile,
    preferPersistent = false,
    allowFreshPersistentProfile = false,
  } = options;
  const profileDir = browserProfileDir();
  const persistentRequested = preferPersistent && parseBool(process.env.BILIBILI_COLUMN_PERSISTENT_BROWSER, true);
  const profileReady = await directoryHasEntries(profileDir);
  const stateFileReady = stateFile ? await pathExists(stateFile) : false;
  const persistent = persistentRequested && (profileReady || allowFreshPersistentProfile);
  const launchOptions = {
    headless,
    locale: DEFAULT_LOCALE,
    timezoneId: DEFAULT_TIMEZONE,
    viewport: DEFAULT_VIEWPORT,
    args: [
      "--lang=zh-CN,zh",
    ],
  };
  if (DEFAULT_USER_AGENT) {
    launchOptions.userAgent = DEFAULT_USER_AGENT;
  }
  if (DEFAULT_BROWSER_CHANNEL) {
    launchOptions.channel = DEFAULT_BROWSER_CHANNEL;
  }
  if (DEFAULT_BROWSER_EXECUTABLE_PATH) {
    launchOptions.executablePath = DEFAULT_BROWSER_EXECUTABLE_PATH;
  }
  if (DEFAULT_BROWSER_SHIM_AUTOMATION) {
    launchOptions.ignoreDefaultArgs = ["--enable-automation"];
    launchOptions.args.push("--disable-blink-features=AutomationControlled");
  }

  if (DEFAULT_BROWSER_ATTACH_URL) {
    const browser = await chromium.connectOverCDP(DEFAULT_BROWSER_ATTACH_URL);
    const context = browser.contexts()[0];
    if (!context) {
      throw new Error("bilibili_attach_context_missing");
    }
    if (DEFAULT_BROWSER_SHIM_AUTOMATION) {
      await applyStealthInitScript(context);
    }
    const page = context.pages()[0] || await context.newPage();
    return {
      browser,
      context,
      page,
      persistent: true,
      profileDir,
      profileReady,
      stateFileReady,
      authMaterialSource: "attached_browser",
      attached: true,
      attachUrl: DEFAULT_BROWSER_ATTACH_URL,
    };
  }

  if (persistent) {
    await clearStaleChromiumSingletonLocks(profileDir);
    const context = await chromium.launchPersistentContext(profileDir, launchOptions);
    if (DEFAULT_BROWSER_SHIM_AUTOMATION) {
      await applyStealthInitScript(context);
    }
    const page = context.pages()[0] || await context.newPage();
    return {
      browser: null,
      context,
      page,
      persistent,
      profileDir,
      profileReady,
      stateFileReady,
      authMaterialSource: profileReady ? "browser_profile" : "fresh_browser_profile",
    };
  }

  const browser = await chromium.launch(launchOptions);
  const contextOptions = {
    locale: DEFAULT_LOCALE,
    timezoneId: DEFAULT_TIMEZONE,
    viewport: DEFAULT_VIEWPORT,
  };
  if (stateFileReady) {
    contextOptions.storageState = stateFile;
  }
  const context = await browser.newContext(contextOptions);
  if (DEFAULT_BROWSER_SHIM_AUTOMATION) {
    await applyStealthInitScript(context);
  }
  const page = await context.newPage();
  return {
    browser,
    context,
    page,
    persistent,
    profileDir,
    profileReady,
    stateFileReady,
    authMaterialSource: stateFileReady ? "storage_state" : "clean_context",
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
  if (!runtime) {
    return;
  }
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

async function firstVisibleLocator(page, selectors, options = {}) {
  for (const selector of selectors) {
    const locator = page.locator(selector).first();
    try {
      if (await locator.isVisible({ timeout: options.timeout || 1000 })) {
        return { selector, locator };
      }
    } catch {
      continue;
    }
  }
  return null;
}

async function firstVisibleLocatorAcrossFrames(page, selectors, options = {}) {
  const roots = [page, ...page.frames()];
  for (const root of roots) {
    const match = await firstVisibleLocator(root, selectors, options).catch(() => null);
    if (match) {
      return { ...match, root };
    }
  }
  return null;
}

async function clickLocatorRobust(page, locator, fallbackPage = null) {
  try {
    await locator.click({ timeout: 3000 });
    return true;
  } catch {}
  try {
    await locator.click({ timeout: 3000, force: true });
    return true;
  } catch {}
  try {
    const box = await locator.boundingBox().catch(() => null);
    const mouseOwner = page && typeof page.mouse?.click === "function"
      ? page
      : fallbackPage;
    if (box && mouseOwner && typeof mouseOwner.mouse?.click === "function") {
      await mouseOwner.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
      return true;
    }
  } catch {}
  try {
    await locator.evaluate((node) => node.click());
    return true;
  } catch {}
  return false;
}

async function activateLocatorAggressively(page, locator, fallbackPage = null) {
  let activated = false;
  try {
    await locator.scrollIntoViewIfNeeded({ timeout: 2000 });
  } catch {}
  try {
    await locator.click({ timeout: 3000 });
    activated = true;
  } catch {}
  try {
    await locator.evaluate((node) => {
      const options = { bubbles: true, cancelable: true, view: window };
      node.dispatchEvent(new PointerEvent("pointerdown", options));
      node.dispatchEvent(new MouseEvent("mousedown", options));
      node.dispatchEvent(new PointerEvent("pointerup", options));
      node.dispatchEvent(new MouseEvent("mouseup", options));
      node.dispatchEvent(new MouseEvent("click", options));
      if (typeof node.click === "function") {
        node.click();
      }
    });
    activated = true;
  } catch {}
  try {
    const box = await locator.boundingBox().catch(() => null);
    const mouseOwner = page && typeof page.mouse?.click === "function"
      ? page
      : fallbackPage;
    if (box && mouseOwner && typeof mouseOwner.mouse?.click === "function") {
      await mouseOwner.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
      activated = true;
    }
  } catch {}
  return activated;
}

async function fillFirstVisibleInput(page, selectors, value) {
  const normalized = normalizeText(value);
  if (!normalized) {
    return "";
  }
  for (const selector of selectors) {
    const locator = page.locator(selector).first();
    try {
      if (!await locator.isVisible({ timeout: 1000 })) {
        continue;
      }
      await locator.click({ timeout: 3000 });
      await locator.fill("");
      await locator.fill(normalized);
      return selector;
    } catch {
      continue;
    }
  }
  return "";
}

async function clickFirstVisible(page, selectors, options = {}) {
  const match = await firstVisibleLocator(page, selectors, { timeout: options.timeoutMs || options.timeout || 1000 });
  if (!match) {
    return "";
  }
  const clicked = await clickLocatorRobust(page, match.locator);
  if (clicked) {
    await page.waitForTimeout(options.waitAfterMs || 300);
    return match.selector;
  }
  return "";
}

async function maybeAcceptAgreement(page) {
  const selectors = [
    "label:has-text('我已阅读并同意')",
    "label:has-text('同意用户协议')",
    "label:has-text('同意')",
    "[role='checkbox']:has-text('同意')",
    "input[type='checkbox']",
  ];
  for (const selector of selectors) {
    const locator = page.locator(selector).first();
    try {
      if (!await locator.isVisible({ timeout: 1000 })) {
        continue;
      }
      const isChecked = await locator.evaluate((node) => {
        if (node instanceof HTMLInputElement && node.type === "checkbox") {
          return node.checked;
        }
        return node.getAttribute("aria-checked") === "true";
      }).catch(() => false);
      if (!isChecked) {
        await clickLocatorRobust(page, locator);
        await page.waitForTimeout(300);
      }
      return selector;
    } catch {
      continue;
    }
  }
  return "";
}

async function submitCredentialForm(page, preferredSelector = "") {
  const selectors = [];
  if (preferredSelector) {
    selectors.push(preferredSelector);
  }
  selectors.push(
    "div.btn_primary",
    ".btn_primary",
    "button:has-text('登录')",
    "[role='button']:has-text('登录')",
    "button[type='submit']",
    "div[class*='btn']:has-text('登录')",
    "span:has-text('登录')",
    "text=登录",
  );
  return clickFirstVisible(page, selectors, { timeoutMs: 1500, waitAfterMs: 1500 });
}

async function attemptSmsLogin(page) {
  const phone = normalizeText(
    process.env.BILIBILI_COLUMN_PHONE
    || process.env.AIMAGICIAN_PLATFORM_LOGIN_PHONE
    || process.env.BILIBILI_COLUMN_USERNAME
    || DEFAULT_PHONE_NUMBER
  );
  const result = {
    sms_login_configured: Boolean(phone),
    sms_mode_selector: "",
    phone_selector: "",
    code_selector: "",
    get_code_selector: "",
    sms_get_code_clicked: false,
    sms_challenge_required: false,
    sms_challenge_marker: "",
    agreement_selector: "",
  };
  if (!phone) {
    return result;
  }
  result.sms_mode_selector = await clickFirstVisible(page, [
    "text=短信登录",
    "text=验证码登录",
    "text=手机验证码",
    "button:has-text('短信登录')",
    "button:has-text('验证码登录')",
    "[role='button']:has-text('短信登录')",
    "[role='button']:has-text('验证码登录')",
    "[role='tab']:has-text('短信登录')",
    "[role='tab']:has-text('验证码登录')",
    "span:has-text('短信登录')",
    "span:has-text('验证码登录')",
  ], { timeoutMs: 1500, waitAfterMs: 800 });
  result.phone_selector = await fillFirstVisibleInput(page, [
    "input[type='tel']",
    "input[name='tel']",
    "input[name='phone']",
    "input[name='username']",
    "input[autocomplete='tel']",
    "input[inputmode='numeric']",
    "input[placeholder*='手机号']",
    "input[placeholder*='手机号码']",
    "input[placeholder*='账号']",
  ], phone);
  result.code_selector = await fillFirstVisibleInput(page, [
    "input[placeholder*='验证码']",
    "input[name*='code']",
    "input[inputmode='numeric']",
  ], "");
  result.agreement_selector = await maybeAcceptAgreement(page);
  result.get_code_selector = await clickFirstVisible(page, [
    ":text-is('获取验证码')",
    ":text-is('发送验证码')",
    "text=获取验证码",
    "text=发送验证码",
    "div.clickable:has-text('获取验证码')",
    "div.clickable:has-text('发送验证码')",
    "[class*='clickable']:has-text('获取验证码')",
    "[class*='clickable']:has-text('发送验证码')",
    "button:has-text('获取验证码')",
    "button:has-text('发送验证码')",
    "button:has-text('获取短信验证码')",
    "[role='button']:has-text('获取验证码')",
    "[role='button']:has-text('发送验证码')",
    "span:has-text('获取验证码')",
    "span:has-text('发送验证码')",
  ], { timeoutMs: 1500, waitAfterMs: 1500 });
  result.sms_get_code_clicked = Boolean(result.get_code_selector);
  if (result.sms_get_code_clicked) {
    const signals = await collectPageSignals(page);
    result.sms_challenge_required = signals.smsChallengeRequired;
    result.sms_challenge_marker = signals.smsChallengeMarker || signals.manualClearanceMarker;
  }
  return result;
}

async function fillSmsCodeIfAvailable(page, smsCodeFile, state = {}) {
  if (!smsCodeFile || state.sms_code_applied) {
    return state;
  }
  const smsCode = await readOptionalTrimmedFile(smsCodeFile);
  if (!/^\d{4,8}$/.test(smsCode)) {
    return state;
  }
  const codeSelector = await fillFirstVisibleInput(page, [
    "input[placeholder*='验证码']",
    "input[name*='code']",
    "input[inputmode='numeric']",
    "input[type='number']",
    "input[type='text']",
  ], smsCode);
  const submitSelector = await submitCredentialForm(page, "div.btn_primary");
  return {
    ...state,
    sms_code_applied: Boolean(codeSelector),
    sms_code_selector: codeSelector,
    sms_submit_selector: submitSelector,
  };
}

async function attemptCredentialLogin(page) {
  const username = normalizeText(
    process.env.BILIBILI_COLUMN_USERNAME
    || process.env.BILIBILI_COLUMN_PHONE
    || process.env.AIMAGICIAN_PLATFORM_LOGIN_PHONE
    || ""
  );
  const password = normalizeText(process.env.BILIBILI_COLUMN_PASSWORD || "");
  const passwordModeMatch = await firstVisibleLocator(page, [
    "text=密码登录",
    "button:has-text('密码登录')",
    "[role='button']:has-text('密码登录')",
    "[role='tab']:has-text('密码登录')",
    "span:has-text('密码登录')",
  ], { timeout: 1000 });
  const passwordModeSelector = passwordModeMatch?.selector || "";
  if (passwordModeMatch) {
    await clickLocatorRobust(page, passwordModeMatch.locator);
    await page.waitForTimeout(800);
  }
  const usernameSelector = await fillFirstVisibleInput(page, [
    "input[autocomplete='username']",
    "input[name='username']",
    "input[name='tel']",
    "input[name='phone']",
    "input[type='tel']",
    "input[placeholder*='手机号']",
    "input[placeholder*='账号']",
    "input[placeholder*='用户名']",
  ], username);
  const passwordSelector = await fillFirstVisibleInput(page, [
    "input[type='password']",
    "input[autocomplete='current-password']",
    "input[name='password']",
    "input[placeholder*='密码']",
  ], password);
  const agreementSelector = await maybeAcceptAgreement(page);
  const submitSelector = await submitCredentialForm(page, "div.btn_primary");
  return {
    credential_login_configured: Boolean(username && password),
    password_mode_selector: passwordModeSelector,
    username_selector: usernameSelector,
    password_selector: passwordSelector,
    agreement_selector: agreementSelector,
    submit_selector: submitSelector,
  };
}

async function dismissTransientPrompts(page) {
  const clicked = [];
  for (const _ of [0, 1, 2]) {
    const match = await firstVisibleLocator(page, [
      "button:has-text('我知道了')",
      "button:has-text('知道了')",
      "button:has-text('关闭')",
      "button:has-text('稍后')",
      "[role='dialog'] button:has-text('确定')",
      "[role='dialog'] button:has-text('知道了')",
      ".close",
    ], { timeout: 700 });
    if (!match) {
      break;
    }
    const clickedNow = await clickLocatorRobust(page, match.locator);
    if (!clickedNow) {
      break;
    }
    clicked.push(match.selector);
    await page.waitForTimeout(500);
  }
  return clicked;
}

function isPublicArticleUrl(url) {
  return PUBLIC_URL_PATTERN.test(String(url || "").trim());
}

async function collectSelectorTexts(page, selectors) {
  const texts = [];
  for (const selector of selectors) {
    try {
      const values = await page.locator(selector).evaluateAll((nodes) => nodes
        .map((node) => String(
          node.innerText
          || node.textContent
          || node.getAttribute("placeholder")
          || node.getAttribute("aria-label")
          || ""
        ).replace(/\s+/g, " ").trim())
        .filter(Boolean)
        .slice(0, 12));
      texts.push(...values);
    } catch {}
  }
  return [...new Set(texts)];
}

function resolveEditorFrame(page) {
  return page.frames().find((frame) => String(frame.url() || "").includes("/york/read-editor")) || null;
}

async function detectSurface(page) {
  const url = page.url();
  const title = await page.title().catch(() => "");
  const signals = await collectPageSignals(page);
  const editorFrame = resolveEditorFrame(page);
  if (isPublicArticleUrl(url)) {
    return {
      surface: "published",
      url,
      title,
      matched_selector: "current_page_url",
      manual_clearance_required: signals.manualClearanceRequired,
    };
  }
  const loginMatch = await firstVisibleLocator(page, [
    "input[type='password']",
    "input[autocomplete='current-password']",
    "button:has-text('登录')",
    "button:has-text('扫码登录')",
    "a:has-text('登录')",
  ]);
  if (url.includes("passport.bilibili.com") || (loginMatch && signals.loginHintSeen)) {
    return {
      surface: "login",
      url,
      title,
      matched_selector: loginMatch?.selector || signals.loginHintMarker || "",
      manual_clearance_required: signals.manualClearanceRequired,
    };
  }
  if (signals.manualClearanceRequired) {
    return {
      surface: "blocked",
      url,
      title,
      matched_selector: signals.manualClearanceMarker,
      manual_clearance_required: true,
    };
  }
  if (signals.dailySubmissionLimitReached) {
    return {
      surface: "daily-limit",
      url,
      title,
      matched_selector: signals.dailySubmissionLimitMarker,
      manual_clearance_required: false,
    };
  }
  const editorMatch = await firstVisibleLocator(page, [
    "input[placeholder*='标题']",
    "textarea[placeholder*='标题']",
    "[contenteditable='true']",
    ".ProseMirror",
    ".ql-editor",
    ".editor",
    "button:has-text('发布')",
    "button:has-text('保存草稿')",
  ]);
  if (url.includes("/platform/upload/text") || editorMatch || editorFrame) {
    return {
      surface: "editor",
      url,
      title,
      matched_selector: editorMatch?.selector || (editorFrame ? "iframe[york-read-editor]" : ""),
      manual_clearance_required: signals.manualClearanceRequired,
    };
  }
  const creatorMatch = await firstVisibleLocator(page, [
    "text=创作中心",
    "text=专栏投稿",
    "a[href*='/platform/upload/text']",
  ]);
  if (url.includes("/platform/home") || creatorMatch) {
    return {
      surface: "creator-home",
      url,
      title,
      matched_selector: creatorMatch?.selector || "",
      manual_clearance_required: signals.manualClearanceRequired,
    };
  }
  return {
    surface: "unknown",
    url,
    title,
    matched_selector: "",
    manual_clearance_required: signals.manualClearanceRequired,
  };
}

async function saveSessionStateSafely(context, stateFile) {
  if (!stateFile) {
    return { stateSaved: false, stateSaveError: "missing_state_file" };
  }
  try {
    await fs.mkdir(path.dirname(stateFile), { recursive: true });
    await context.storageState({ path: stateFile });
    return { stateSaved: true, stateSaveError: "" };
  } catch (error) {
    return {
      stateSaved: false,
      stateSaveError: error instanceof Error ? error.message : String(error),
    };
  }
}

function buildCookieHeader(cookies) {
  return cookies
    .filter((item) => item && item.name && item.value)
    .map((item) => `${item.name}=${item.value}`)
    .join("; ");
}

async function fetchProbe(url, cookieHeader, referer = DEFAULT_CREATOR_HOME_URL) {
  try {
    const response = await fetch(url, {
      headers: {
        accept: "application/json, text/plain, */*",
        "user-agent": DEFAULT_USER_AGENT,
        referer,
        cookie: cookieHeader,
      },
      redirect: "follow",
    });
    const body = await response.text();
    const payload = JSON.parse(body);
    return {
      probe_url: url,
      http_status: response.status,
      api_code: payload.code,
      api_message: String(payload.message || payload.msg || ""),
      data: payload.data,
    };
  } catch (error) {
    return {
      probe_url: url,
      http_status: null,
      api_code: null,
      api_message: error instanceof Error ? error.message : String(error),
      error: "fetch_probe_failed",
    };
  }
}

async function openEditor(page, timeoutMs) {
  await page.goto(DEFAULT_CREATOR_HOME_URL, { waitUntil: "domcontentloaded", timeout: timeoutMs }).catch(() => null);
  await page.waitForTimeout(1200);
  await dismissTransientPrompts(page);
  await page.goto(DEFAULT_EDITOR_URL, { waitUntil: "domcontentloaded", timeout: timeoutMs }).catch(() => null);
  await page.waitForTimeout(1800);
  await dismissTransientPrompts(page);
  return detectSurface(page);
}

async function checkSession(runtime, args, stateFile, timeoutMs) {
  const { context, page, profileDir, authMaterialSource } = runtime;
  await checkpointProgress(args, "check_session_navigate", {
    editor_url: DEFAULT_EDITOR_URL,
    profile_dir: profileDir,
  });
  const detected = await openEditor(page, timeoutMs);
  const signals = await collectPageSignals(page);
  const cookies = await context.cookies().catch(() => []);
  const cookieHeader = buildCookieHeader(cookies);
  const sessionProbe = await fetchProbe(SESSION_PROBE_URL, cookieHeader);
  const authorProbe = await fetchProbe(AUTHOR_PROBE_URL, cookieHeader);
  const { stateSaved, stateSaveError } = detected.surface === "editor"
    ? await saveSessionStateSafely(context, stateFile)
    : { stateSaved: false, stateSaveError: "" };
  const liveReady = detected.surface === "editor";
  const reason = liveReady
    ? ""
    : (detected.surface === "login"
      ? "session_invalid_or_missing"
      : detected.surface === "daily-limit"
        ? "daily_submission_limit_reached"
      : detected.surface === "blocked"
        ? "manual_clearance_required"
        : "editor_surface_not_reached");
  const evidence = await capturePageEvidence(page, args, "check-session", {
    surface: detected.surface,
    reason,
  });
  return {
    status: liveReady ? "ok" : "blocked",
    mode: "check-session",
    live_ready: liveReady,
    final_url: detected.url,
    page_title: detected.title,
    surface: detected.surface,
    matched_selector: detected.matched_selector,
    state_file: stateFile,
    state_file_written: stateSaved,
    state_file_write_error: stateSaveError,
    browser_profile_dir: profileDir,
    auth_material_source: authMaterialSource,
    manual_clearance_required: detected.manual_clearance_required || signals.manualClearanceRequired,
    session_probe: sessionProbe,
    author_probe: authorProbe,
    reason,
    final_blocker: reason,
    evidence,
  };
}

async function bootstrapSession(runtime, args, stateFile, timeoutMs) {
  const { context, page, profileDir, authMaterialSource } = runtime;
  const loginMode = normalizeText(process.env.BILIBILI_COLUMN_LOGIN_MODE || args["login-mode"] || "sms").toLowerCase();
  const smsCodeFile = String(process.env.BILIBILI_COLUMN_SMS_CODE_FILE || DEFAULT_SMS_CODE_FILE).trim();
  const allowManualClearanceWait = !parseBool(args.headless, false);
  await checkpointProgress(args, "bootstrap_navigate", {
    login_url: DEFAULT_LOGIN_URL,
    editor_url: DEFAULT_EDITOR_URL,
    profile_dir: profileDir,
    login_mode: loginMode,
    sms_code_file: smsCodeFile,
  });
  await page.goto(DEFAULT_LOGIN_URL, { waitUntil: "domcontentloaded", timeout: timeoutMs }).catch(() => null);
  await page.waitForTimeout(1800);
  await dismissTransientPrompts(page);

  let detected = await detectSurface(page);
  let loginAttempt = {};
  if (detected.surface === "editor") {
    const { stateSaved, stateSaveError } = await saveSessionStateSafely(context, stateFile);
    const evidence = await capturePageEvidence(page, args, "bootstrap-session-ready", {
      reused_existing_session: true,
    });
    return {
      status: "ok",
      mode: "bootstrap-session",
      live_ready: true,
      reused_existing_session: true,
      final_url: detected.url,
      page_title: detected.title,
      matched_selector: detected.matched_selector,
      state_file: stateFile,
      state_file_written: stateSaved,
      state_file_write_error: stateSaveError,
      browser_profile_dir: profileDir,
      auth_material_source: authMaterialSource,
      evidence,
    };
  }

  const deadline = Date.now() + Math.max(timeoutMs, 120000);
  let lastSignals = await collectPageSignals(page);
  while (Date.now() < deadline) {
    const smsClearanceActive = loginMode === "sms"
      && (loginAttempt.sms_challenge_required || lastSignals.smsChallengeRequired);
    const manualClearanceActive = detected.surface === "blocked" || lastSignals.manualClearanceRequired;
    const clearanceActive = smsClearanceActive || manualClearanceActive;

    if (detected.surface === "login" && !clearanceActive) {
      loginAttempt = loginMode === "sms"
        ? await attemptSmsLogin(page)
        : await attemptCredentialLogin(page);
      await checkpointProgress(args, "bootstrap_wait_manual_login", {
        current_url: page.url(),
        current_surface: detected.surface,
        login_mode: loginMode,
        sms_code_file: smsCodeFile,
        ...loginAttempt,
      });
    } else if (clearanceActive && allowManualClearanceWait) {
      await checkpointProgress(args, "bootstrap_wait_manual_clearance", {
        current_url: page.url(),
        current_surface: detected.surface,
        login_mode: loginMode,
        sms_code_file: smsCodeFile,
        sms_challenge_required: smsClearanceActive,
        sms_challenge_marker: loginAttempt.sms_challenge_marker || lastSignals.smsChallengeMarker || "",
        manual_clearance_required: manualClearanceActive,
        manual_clearance_marker: lastSignals.manualClearanceMarker || detected.matched_selector || "",
      });
    }
    if (loginMode === "sms") {
      loginAttempt = await fillSmsCodeIfAvailable(page, smsCodeFile, loginAttempt);
    }
    await page.waitForTimeout(1500);
    await dismissTransientPrompts(page);
    detected = await detectSurface(page);
    lastSignals = await collectPageSignals(page);
    if (loginMode === "sms" && (loginAttempt.sms_challenge_required || lastSignals.smsChallengeRequired)) {
      if (allowManualClearanceWait) {
        continue;
      }
      const evidence = await capturePageEvidence(page, args, "bootstrap-session-sms-challenge", {
        surface: detected.surface,
        final_blocker: "sms_send_requires_manual_clearance",
        ...loginAttempt,
      });
      return {
        status: "blocked",
        mode: "bootstrap-session",
        live_ready: false,
        login_mode: loginMode,
        sms_code_file: smsCodeFile,
        sms_code_applied: Boolean(loginAttempt.sms_code_applied),
        sms_get_code_clicked: Boolean(loginAttempt.sms_get_code_clicked),
        sms_challenge_required: true,
        sms_challenge_marker: loginAttempt.sms_challenge_marker || lastSignals.smsChallengeMarker,
        final_url: detected.url,
        page_title: detected.title,
        matched_selector: (
          loginAttempt.sms_challenge_marker
          || lastSignals.smsChallengeMarker
          || detected.matched_selector
        ),
        state_file: stateFile,
        state_file_written: false,
        browser_profile_dir: profileDir,
        auth_material_source: authMaterialSource,
        manual_clearance_required: true,
        reason: "sms_send_requires_manual_clearance",
        final_blocker: "sms_send_requires_manual_clearance",
        evidence,
      };
    }
    if (detected.surface === "creator-home") {
      detected = await openEditor(page, timeoutMs);
    }
    if (detected.surface === "editor") {
      const { stateSaved, stateSaveError } = await saveSessionStateSafely(context, stateFile);
      const evidence = await capturePageEvidence(page, args, "bootstrap-session-ready", {
        reused_existing_session: false,
        ...loginAttempt,
      });
      return {
        status: "ok",
        mode: "bootstrap-session",
        live_ready: true,
        reused_existing_session: false,
        login_mode: loginMode,
        sms_code_file: smsCodeFile,
        sms_code_applied: Boolean(loginAttempt.sms_code_applied),
        sms_get_code_clicked: Boolean(loginAttempt.sms_get_code_clicked),
        sms_challenge_required: Boolean(loginAttempt.sms_challenge_required),
        sms_challenge_marker: loginAttempt.sms_challenge_marker || "",
        final_url: detected.url,
        page_title: detected.title,
        matched_selector: detected.matched_selector,
        state_file: stateFile,
        state_file_written: stateSaved,
        state_file_write_error: stateSaveError,
        browser_profile_dir: profileDir,
        auth_material_source: authMaterialSource,
        evidence,
      };
    }
    if (detected.surface === "blocked" || lastSignals.manualClearanceRequired) {
      if (allowManualClearanceWait) {
        continue;
      }
      const evidence = await capturePageEvidence(page, args, "bootstrap-session-blocked", {
        surface: detected.surface,
        final_blocker: "manual_clearance_required",
        ...loginAttempt,
      });
      return {
        status: "blocked",
        mode: "bootstrap-session",
        live_ready: false,
        login_mode: loginMode,
        sms_code_file: smsCodeFile,
        sms_code_applied: Boolean(loginAttempt.sms_code_applied),
        sms_get_code_clicked: Boolean(loginAttempt.sms_get_code_clicked),
        sms_challenge_required: Boolean(lastSignals.smsChallengeRequired),
        sms_challenge_marker: lastSignals.smsChallengeMarker || "",
        final_url: detected.url,
        page_title: detected.title,
        matched_selector: detected.matched_selector || lastSignals.manualClearanceMarker,
        state_file: stateFile,
        state_file_written: false,
        browser_profile_dir: profileDir,
        auth_material_source: authMaterialSource,
        manual_clearance_required: true,
        reason: "manual_clearance_required",
        final_blocker: "manual_clearance_required",
        evidence,
      };
    }
  }

  const evidence = await capturePageEvidence(page, args, "bootstrap-session-timeout", {
    surface: detected.surface,
    final_blocker: "manual_login_not_completed",
    ...loginAttempt,
  });
  return {
    status: "blocked",
    mode: "bootstrap-session",
    live_ready: false,
    login_mode: loginMode,
    sms_code_file: smsCodeFile,
    sms_code_applied: Boolean(loginAttempt.sms_code_applied),
    sms_get_code_clicked: Boolean(loginAttempt.sms_get_code_clicked),
    sms_challenge_required: Boolean(lastSignals.smsChallengeRequired),
    sms_challenge_marker: lastSignals.smsChallengeMarker || "",
    final_url: detected.url,
    page_title: detected.title,
    matched_selector: detected.matched_selector,
    state_file: stateFile,
    state_file_written: false,
    browser_profile_dir: profileDir,
    auth_material_source: authMaterialSource,
    manual_clearance_required: lastSignals.manualClearanceRequired,
    reason: "manual_login_not_completed",
    final_blocker: "manual_login_not_completed",
    evidence,
  };
}

async function resolveInputCandidates(page) {
  return page.locator("input[type='file']").evaluateAll((nodes) => nodes.map((node, index) => {
    const textFrom = (target) => String(
      target?.innerText
      || target?.textContent
      || target?.getAttribute?.("aria-label")
      || target?.getAttribute?.("title")
      || ""
    ).replace(/\s+/g, " ").trim();
    const parent = node.parentElement;
    const grand = parent?.parentElement;
    const label = node.labels && node.labels.length ? Array.from(node.labels).map((item) => textFrom(item)).join(" ") : "";
    const nearby = [
      textFrom(node),
      textFrom(parent),
      textFrom(grand),
      label,
    ].join(" ").slice(0, 400);
    return {
      index,
      multiple: node.multiple,
      accept: String(node.getAttribute("accept") || ""),
      nearbyText: nearby,
    };
  }));
}

async function resolveCoverUploadFile(draft) {
  const cover = draft?.cover && typeof draft.cover === "object" ? draft.cover : {};
  const sourcePath = String(cover.source_path || cover.runtime_path || "").trim();
  if (sourcePath) {
    await fs.access(sourcePath);
    return { filePath: sourcePath, temporary: false };
  }
  const directUrl = String(cover.direct_url || "").trim();
  if (!directUrl) {
    return { filePath: "", temporary: false };
  }
  const response = await fetch(directUrl);
  if (!response.ok) {
    throw new Error(`cover_download_failed:${response.status}`);
  }
  const bytes = Buffer.from(await response.arrayBuffer());
  const extension = path.extname(new URL(directUrl).pathname) || ".png";
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "oc-bilibili-cover-"));
  const filePath = path.join(tempDir, `cover${extension}`);
  await fs.writeFile(filePath, bytes);
  return { filePath, temporary: true };
}

async function openPublishSettings(root, page) {
  const dialogVisible = await root.locator(".publish-settings").first().isVisible({ timeout: 500 }).catch(() => false);
  if (dialogVisible) {
    return {
      opened: true,
      selector: ".publish-settings",
      reason: "",
    };
  }
  const match = await firstVisibleLocator(root, [
    "button:has-text('发布设置')",
    ".settings-button",
    "text=发布设置",
  ], { timeout: 1200 });
  if (!match) {
    return {
      opened: false,
      selector: "",
      reason: "publish_settings_button_missing",
    };
  }
  const clicked = await clickLocatorRobust(root, match.locator, page);
  if (!clicked) {
    return {
      opened: false,
      selector: match.selector,
      reason: "publish_settings_open_failed",
    };
  }
  await root.waitForTimeout(600);
  const opened = await root.locator(".publish-settings").first().isVisible({ timeout: 1200 }).catch(() => false);
  return {
    opened,
    selector: match.selector,
    reason: opened ? "" : "publish_settings_not_opened",
  };
}

async function ensureOriginalDeclaration(root, page, draft) {
  if (draft?.declare_original === false) {
    return {
      checked: true,
      selector: "",
      reason: "",
      mode: "skipped_disabled_by_payload",
    };
  }
  const settings = await openPublishSettings(root, page);
  if (!settings.opened) {
    return {
      checked: false,
      selector: settings.selector,
      reason: settings.reason || "publish_settings_not_opened",
      mode: "",
    };
  }
  const state = await root.evaluate(() => {
    const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
    const label = Array.from(document.querySelectorAll("label.vui_checkbox")).find((node) => {
      const text = normalize(node.innerText || node.textContent || "");
      return text.includes("声明此文章为原创");
    });
    const input = label?.querySelector("input[type='checkbox']");
    if (!label || !input) {
      return {
        exists: false,
        checked: false,
      };
    }
    if (!input.checked) {
      label.click();
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
    return {
      exists: true,
      checked: Boolean(input.checked),
    };
  }).catch(() => ({
    exists: false,
    checked: false,
  }));
  if (!state.exists) {
    return {
      checked: false,
      selector: "label.vui_checkbox:has-text('声明此文章为原创') input[type='checkbox']",
      reason: "original_declaration_checkbox_not_found",
      mode: "",
    };
  }
  await root.waitForTimeout(300);
  const checked = await root.evaluate(() => {
    const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
    const label = Array.from(document.querySelectorAll("label.vui_checkbox")).find((node) => {
      const text = normalize(node.innerText || node.textContent || "");
      return text.includes("声明此文章为原创");
    });
    const input = label?.querySelector("input[type='checkbox']");
    return Boolean(input?.checked);
  }).catch(() => false);
  return {
    checked,
    selector: "label.vui_checkbox:has-text('声明此文章为原创') input[type='checkbox']",
    reason: checked ? "" : "original_declaration_not_confirmed",
    mode: checked ? "checkbox_checked" : "",
  };
}

async function ensureAiAssistedDeclaration(root, page, draft) {
  const cover = draft?.cover && typeof draft.cover === "object" ? draft.cover : {};
  const hasGeneratedCover = Boolean(cover.source_path || cover.direct_url);
  if (!hasGeneratedCover) {
    return {
      checked: true,
      selector: "",
      reason: "",
      mode: "skipped_no_generated_cover",
    };
  }
  const settings = await openPublishSettings(root, page);
  if (!settings.opened) {
    return {
      checked: false,
      selector: settings.selector,
      reason: settings.reason || "publish_settings_not_opened",
      mode: "",
    };
  }
  const state = await root.evaluate(() => {
    const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
    const label = Array.from(document.querySelectorAll("label.vui_checkbox")).find((node) => {
      const text = normalize(node.innerText || node.textContent || "");
      return text.includes("AI辅助创作声明");
    });
    const input = label?.querySelector("input[type='checkbox']");
    if (!label || !input) {
      return {
        exists: false,
        checked: false,
      };
    }
    if (!input.checked) {
      label.click();
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
    return {
      exists: true,
      checked: Boolean(input.checked),
    };
  }).catch(() => ({
    exists: false,
    checked: false,
  }));
  if (!state.exists) {
    return {
      checked: false,
      selector: "label.vui_checkbox:has-text('AI辅助创作声明') input[type='checkbox']",
      reason: "ai_declaration_checkbox_not_found",
      mode: "",
    };
  }
  await root.waitForTimeout(300);
  const checked = await root.evaluate(() => {
    const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
    const label = Array.from(document.querySelectorAll("label.vui_checkbox")).find((node) => {
      const text = normalize(node.innerText || node.textContent || "");
      return text.includes("AI辅助创作声明");
    });
    const input = label?.querySelector("input[type='checkbox']");
    return Boolean(input?.checked);
  }).catch(() => false);
  return {
    checked,
    selector: "label.vui_checkbox:has-text('AI辅助创作声明') input[type='checkbox']",
    reason: checked ? "" : "ai_declaration_not_confirmed",
    mode: checked ? "checkbox_checked" : "",
  };
}

async function ensureCustomCoverEnabled(root, page) {
  const settings = await openPublishSettings(root, page);
  if (!settings.opened) {
    return {
      enabled: false,
      selector: settings.selector,
      reason: settings.reason || "publish_settings_not_opened",
    };
  }
  const toggle = root.locator(".form-item:has-text('自定义封面') .vui_switch--switch").first();
  const exists = await toggle.count().catch(() => 0);
  if (!exists) {
    return {
      enabled: false,
      selector: ".form-item:has-text('自定义封面') .vui_switch--switch",
      reason: "cover_toggle_not_found",
    };
  }
  let enabled = (await toggle.getAttribute("aria-checked").catch(() => "")) === "true";
  if (!enabled) {
    const clicked = await clickLocatorRobust(root, toggle, page);
    if (!clicked) {
      return {
        enabled: false,
        selector: ".form-item:has-text('自定义封面') .vui_switch--switch",
        reason: "cover_toggle_click_failed",
      };
    }
    await root.waitForTimeout(500);
    enabled = (await toggle.getAttribute("aria-checked").catch(() => "")) === "true";
  }
  return {
    enabled,
    selector: ".form-item:has-text('自定义封面') .vui_switch--switch",
    reason: enabled ? "" : "cover_toggle_not_enabled",
  };
}

async function uploadCoverImage(root, page, draft) {
  const upload = await resolveCoverUploadFile(draft);
  if (!upload.filePath) {
    return {
      uploaded: false,
      blocking: true,
      reason: "cover_image_missing",
      filePath: "",
      selected_input: null,
    };
  }
  const coverToggle = await ensureCustomCoverEnabled(root, page);
  if (!coverToggle.enabled) {
    if (upload.temporary) {
      await fs.unlink(upload.filePath).catch(() => null);
      await fs.rmdir(path.dirname(upload.filePath)).catch(() => null);
    }
    return {
      uploaded: false,
      blocking: true,
      reason: coverToggle.reason || "cover_toggle_not_enabled",
      filePath: upload.filePath,
      selected_input: null,
    };
  }

  try {
    const uploadArea = await firstVisibleLocator(root, [
      ".select-cover-content",
      ".select-cover .upload-button",
      ".select-cover .upload-text",
      ".select-cover",
    ], { timeout: 1500 });
    if (!uploadArea) {
      throw new Error("cover_upload_control_not_detected");
    }
    await clickLocatorRobust(root, uploadArea.locator, page);
    await root.waitForTimeout(600);
    const imageInput = root.locator(
      "input[type='file'][accept*='.jpg'], input[type='file'][accept*='.jpeg'], input[type='file'][accept*='.png']",
    ).last();
    const inputCount = await imageInput.count().catch(() => 0);
    if (!inputCount) {
      throw new Error("cover_upload_control_not_detected");
    }
    await imageInput.setInputFiles(upload.filePath);
    await root.waitForTimeout(1800);
    const confirm = await firstVisibleLocator(root, [
      ".vui_dialog--content button:has-text('确定')",
      ".vui_dialog--content button:has-text('完成')",
      ".vui_dialog--content button:has-text('保存')",
      "button:has-text('完成裁剪')",
    ], { timeout: 1200 });
    if (confirm) {
      await clickLocatorRobust(root, confirm.locator, page);
      await root.waitForTimeout(2200);
    }
  } catch (error) {
    if (upload.temporary) {
      await fs.unlink(upload.filePath).catch(() => null);
      await fs.rmdir(path.dirname(upload.filePath)).catch(() => null);
    }
    return {
      uploaded: false,
      blocking: true,
      reason: error instanceof Error ? `cover_upload_failed:${error.message}` : "cover_upload_failed",
      filePath: upload.filePath,
      selected_input: null,
    };
  }

  const bodyText = await root.locator("body").innerText().catch(() => "");
  const uploaded = /更换封面|重新上传|删除/.test(bodyText);
  if (upload.temporary) {
    await fs.unlink(upload.filePath).catch(() => null);
    await fs.rmdir(path.dirname(upload.filePath)).catch(() => null);
  }
  return {
    uploaded,
    blocking: true,
    reason: uploaded ? "" : "cover_upload_not_confirmed",
    filePath: upload.filePath,
    selected_input: {
      index: 0,
      accept: ".jpg,.jpeg,.png",
      nearbyText: "select-cover-content",
      multiple: false,
    },
  };
}

async function selectTopic(root, page, draft) {
  const candidates = uniqueNormalizedList([
    ...(Array.isArray(draft?.topic_candidates) ? draft.topic_candidates : []),
    ...(Array.isArray(draft?.tags) ? draft.tags : []),
    "人工智能",
    "AI",
    "科技",
    "程序员",
    "学习",
  ]);
  if (!candidates.length) {
    return {
      selected: false,
      selector: "",
      reason: "topic_candidates_missing",
      chosenTopic: "",
      query: "",
    };
  }
  const settings = await openPublishSettings(root, page);
  if (!settings.opened) {
    return {
      selected: false,
      selector: settings.selector,
      reason: settings.reason || "publish_settings_not_opened",
      chosenTopic: "",
      query: "",
    };
  }
  const addTopic = await firstVisibleLocator(root, [
    "button:has-text('添加话题')",
    ".topic-button",
  ], { timeout: 1200 });
  if (!addTopic) {
    return {
      selected: false,
      selector: "",
      reason: "topic_button_missing",
      chosenTopic: "",
      query: "",
    };
  }
  let chosenTopic = "";
  let queryUsed = "";
  for (const candidate of candidates) {
    const dialogAlreadyVisible = await root.locator(".topic-dialog").first().isVisible({ timeout: 300 }).catch(() => false);
    if (!dialogAlreadyVisible) {
      await clickLocatorRobust(root, addTopic.locator, page);
      await root.waitForTimeout(500);
    }
    const searchInput = root.locator("input[placeholder='搜索话题']").first();
    const inputCount = await searchInput.count().catch(() => 0);
    if (!inputCount) {
      continue;
    }
    await searchInput.fill("").catch(() => null);
    await searchInput.fill(candidate).catch(() => null);
    await root.waitForTimeout(1200);
    queryUsed = candidate;
    chosenTopic = await root.evaluate((query) => {
      const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
      const comparable = (value) => normalize(value).replace(/#/g, "");
      const items = Array.from(document.querySelectorAll(".topic-dialog .topic-item"));
      const ranked = items.map((item) => {
        const title = normalize(item.querySelector(".topic-item-name")?.getAttribute("title")
          || item.querySelector(".topic-item-name")?.textContent
          || "");
        const score = !title
          ? -1
          : title === query
            ? 100
            : comparable(title) === comparable(query)
              ? 95
              : title.startsWith(query)
                ? 80 - title.length
                : comparable(title).includes(comparable(query))
                  ? 60 - title.length
                  : query.includes(title)
                    ? 40 - title.length
                    : -1;
        return { item, title, score };
      }).filter((entry) => entry.score >= 0);
      const firstAvailable = items.map((item) => {
        const title = normalize(item.querySelector(".topic-item-name")?.getAttribute("title")
          || item.querySelector(".topic-item-name")?.textContent
          || item.textContent
          || "");
        return { item, title, score: title ? 1 : -1 };
      }).filter((entry) => entry.score >= 0)[0];
      const best = ranked.sort((left, right) => right.score - left.score)[0] || firstAvailable;
      const chosen = best?.item || null;
      if (!chosen) {
        return "";
      }
      const label = chosen.querySelector("label") || chosen;
      label.click();
      return normalize(chosen.querySelector(".topic-item-name")?.getAttribute("title")
        || chosen.querySelector(".topic-item-name")?.textContent
        || chosen.textContent
        || "");
    }, candidate).catch(() => "");
    if (chosenTopic) {
      break;
    }
    const cancelButton = root.locator(".topic-action button:has-text('取消'), .vui_dialog--footer button:has-text('取消')").last();
    if (await cancelButton.count().catch(() => 0)) {
      await clickLocatorRobust(root, cancelButton, page);
      await root.waitForTimeout(300);
    }
  }
  if (!chosenTopic) {
    return {
      selected: false,
      selector: ".topic-dialog .topic-item",
      reason: "topic_option_not_found",
      chosenTopic: "",
      query: queryUsed,
    };
  }
  const confirm = root.locator(".topic-action button:has-text('确认'), .vui_dialog--footer button:has-text('确认')").last();
  const confirmCount = await confirm.count().catch(() => 0);
  if (!confirmCount) {
    return {
      selected: false,
      selector: ".topic-action button:has-text('确认')",
      reason: "topic_confirm_button_missing",
      chosenTopic,
      query: queryUsed,
    };
  }
  await clickLocatorRobust(root, confirm, page);
  await root.waitForTimeout(800);
  const bodyText = await root.locator("body").innerText().catch(() => "");
  const selected = bodyText.includes(chosenTopic);
  return {
    selected,
    selector: ".topic-dialog .topic-item",
    reason: selected ? "" : "topic_selection_not_confirmed",
    chosenTopic,
    query: queryUsed,
  };
}

async function selectCollection(root, page, draft) {
  const preferredName = normalizeText(draft?.collection_name || "");
  const settings = await openPublishSettings(root, page);
  if (!settings.opened) {
    return {
      selected: false,
      selector: settings.selector,
      reason: settings.reason || "publish_settings_not_opened",
      chosenCollection: "",
    };
  }
  const openCollection = await firstVisibleLocator(root, [
    "button:has-text('选择文集')",
    ".collection-button",
  ], { timeout: 1200 });
  if (!openCollection) {
    return {
      selected: false,
      selector: "",
      reason: "collection_button_missing",
      chosenCollection: "",
    };
  }
  await clickLocatorRobust(root, openCollection.locator, page);
  await root.waitForTimeout(500);
  const chosenCollection = await root.evaluate((preferred) => {
    const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
    const items = Array.from(document.querySelectorAll(".collection-dialog .collection-radio"));
    const exact = preferred
      ? items.find((item) => {
        const name = normalize(item.querySelector(".collection-name")?.getAttribute("title")
          || item.querySelector(".collection-name")?.textContent
          || "");
        return name === preferred;
      })
      : null;
    const partial = exact || (preferred
      ? items.find((item) => {
        const name = normalize(item.querySelector(".collection-name")?.getAttribute("title")
          || item.querySelector(".collection-name")?.textContent
          || "");
        return name && (name.includes(preferred) || preferred.includes(name));
      })
      : null);
    const chosen = partial || items[0];
    if (!chosen) {
      return "";
    }
    chosen.click();
    return normalize(chosen.querySelector(".collection-name")?.getAttribute("title")
      || chosen.querySelector(".collection-name")?.textContent
      || chosen.textContent
      || "");
  }, preferredName).catch(() => "");
  if (!chosenCollection) {
    return {
      selected: false,
      selector: ".collection-dialog .collection-radio",
      reason: "collection_option_not_found",
      chosenCollection: "",
    };
  }
  const confirm = root.locator(".collection-action button:has-text('确定'), .vui_dialog--footer button:has-text('确定')").last();
  const confirmCount = await confirm.count().catch(() => 0);
  if (!confirmCount) {
    return {
      selected: false,
      selector: ".collection-action button:has-text('确定')",
      reason: "collection_confirm_button_missing",
      chosenCollection,
    };
  }
  await clickLocatorRobust(root, confirm, page);
  await root.waitForTimeout(800);
  const bodyText = await root.locator("body").innerText().catch(() => "");
  const selected = bodyText.includes(chosenCollection);
  return {
    selected,
    selector: ".collection-dialog .collection-radio",
    reason: selected ? "" : "collection_selection_not_confirmed",
    chosenCollection,
  };
}

async function resolveTitleSelector(root) {
  return root.evaluate(() => {
    const ensureSelector = (node) => {
      if (!node.dataset.openclawId) {
        node.dataset.openclawId = `oc-${Math.random().toString(36).slice(2, 10)}`;
      }
      node.dataset.aimagicianId = node.dataset.openclawId;
      return `[data-aimagician-id="${node.dataset.openclawId}"]`;
    };
    
    // 首先尝试常见的 B站专栏标题选择器
    const commonSelectors = [
      "input.title-input",
      "input[placeholder*='标题']",
      "textarea[placeholder*='标题']",
      "input[placeholder*='请输入标题']",
      "h1[contenteditable]",
      "[contenteditable][data-placeholder*='标题']",
      "[contenteditable][aria-placeholder*='标题']",
      "[data-placeholder*='请输入标题']",
      "[data-placeholder*='标题']",
      "[aria-placeholder*='标题']",
      "[class*='title'] input",
      "[class*='Title'] input",
      "[class*='title'] [contenteditable]",
      "[class*='Title'] [contenteditable]",
      ".article-title input",
      ".article-title [contenteditable]",
      ".title-input",
    ];
    
    for (const selector of commonSelectors) {
      try {
        const node = document.querySelector(selector);
        if (node && node.offsetParent !== null) {
          const rect = node.getBoundingClientRect();
          if (rect.width > 100 && rect.height > 20) {
            return {
              score: 200,
              selector: ensureSelector(node),
              placeholder: node.getAttribute("placeholder") || node.getAttribute("aria-label") || "",
              tagName: (node.tagName || "").toLowerCase(),
            };
          }
        }
      } catch {}
    }
    
    // 通用候选选择
    const candidates = Array.from(document.querySelectorAll("input, textarea, [contenteditable], [role='textbox'], [data-placeholder], [aria-placeholder]"));
    let best = null;
    for (const node of candidates) {
      const rect = node.getBoundingClientRect();
      // 降低最小尺寸要求
      if (rect.width < 150 || rect.height < 20) {
        continue;
      }
      const style = window.getComputedStyle(node);
      if (style.visibility === "hidden" || style.display === "none") {
        continue;
      }
      const tagName = (node.tagName || "").toLowerCase();
      const placeholder = String(
        node.getAttribute("placeholder")
        || node.getAttribute("data-placeholder")
        || node.getAttribute("aria-placeholder")
        || node.getAttribute("aria-label")
        || ""
      ).trim();
      const className = String(node.getAttribute("class") || "").toLowerCase();
      const nearby = String(node.parentElement?.innerText || "").slice(0, 200);
      const score = (
        (/标题|title/.test(placeholder) ? 220 : 0)
        + (/标题|title/.test(className) ? 100 : 0)
        + (/标题/.test(nearby) ? 40 : 0)
        + (tagName === "input" ? 50 : 0)
        + (tagName === "h1" ? 80 : 0)
        + (node.isContentEditable ? 45 : 0)
        + Math.min(rect.width / 4, 150)
      );
      if (!best || score > best.score) {
        best = {
          score,
          selector: ensureSelector(node),
          placeholder,
          tagName,
        };
      }
    }
    return best;
  }).catch(() => null);
}

async function resolveBodySelector(root) {
  return root.evaluate(() => {
    const ensureSelector = (node) => {
      if (!node.dataset.openclawId) {
        node.dataset.openclawId = `oc-${Math.random().toString(36).slice(2, 10)}`;
      }
      node.dataset.aimagicianId = node.dataset.openclawId;
      return `[data-aimagician-id="${node.dataset.openclawId}"]`;
    };
    const candidates = Array.from(document.querySelectorAll("textarea, [contenteditable], [role='textbox'], [data-placeholder], [aria-placeholder], .ProseMirror, .ql-editor"));
    let best = null;
    for (const node of candidates) {
      const rect = node.getBoundingClientRect();
      if (rect.width < 350 || rect.height < 120) {
        continue;
      }
      const style = window.getComputedStyle(node);
      if (style.visibility === "hidden" || style.display === "none") {
        continue;
      }
      const text = String(node.innerText || node.textContent || "").trim();
      const placeholder = String(
        node.getAttribute("placeholder")
        || node.getAttribute("data-placeholder")
        || node.getAttribute("aria-placeholder")
        || node.getAttribute("aria-label")
        || ""
      ).trim();
      const nearby = String(node.parentElement?.innerText || "").slice(0, 200);
      if (/标题/.test(placeholder) || /标题/.test(nearby)) {
        continue;
      }
      const score = (
        rect.width * rect.height
        + Math.min(text.length, 200)
        + (/正文|内容|写点什么/.test(placeholder) ? 80 : 0)
        + ((node.isContentEditable || /ProseMirror|ql-editor/.test(node.className || "")) ? 100 : 0)
      );
      if (!best || score > best.score) {
        best = {
          score,
          selector: ensureSelector(node),
          placeholder,
        };
      }
    }
    return best;
  }).catch(() => null);
}

async function resolveTagSelector(root) {
  return root.evaluate(() => {
    const ensureSelector = (node) => {
      if (!node.dataset.openclawId) {
        node.dataset.openclawId = `oc-${Math.random().toString(36).slice(2, 10)}`;
      }
      node.dataset.aimagicianId = node.dataset.openclawId;
      return `[data-aimagician-id="${node.dataset.openclawId}"]`;
    };
    const candidates = Array.from(document.querySelectorAll("input, textarea, [contenteditable='true'], [role='textbox']"));
    for (const node of candidates) {
      const placeholder = String(node.getAttribute("placeholder") || node.getAttribute("aria-label") || "").trim();
      const nearby = String(node.parentElement?.innerText || "").slice(0, 120);
      if (/标签|tag/i.test(`${placeholder} ${nearby}`)) {
        return {
          selector: ensureSelector(node),
          placeholder,
        };
      }
    }
    return null;
  }).catch(() => null);
}

async function resolveAbstractSelector(root) {
  return root.evaluate(() => {
    const ensureSelector = (node) => {
      if (!node.dataset.openclawId) {
        node.dataset.openclawId = `oc-${Math.random().toString(36).slice(2, 10)}`;
      }
      node.dataset.aimagicianId = node.dataset.openclawId;
      return `[data-aimagician-id="${node.dataset.openclawId}"]`;
    };
    const candidates = Array.from(document.querySelectorAll("input, textarea"));
    for (const node of candidates) {
      const placeholder = String(node.getAttribute("placeholder") || node.getAttribute("aria-label") || "").trim();
      const rect = node.getBoundingClientRect();
      if (rect.width > 900 || rect.height > 180) {
        continue;
      }
      if (/摘要|简介|导语|前言/i.test(placeholder)) {
        return {
          selector: ensureSelector(node),
          placeholder,
        };
      }
    }
    return null;
  }).catch(() => null);
}

async function setPlainValue(root, browserPage, selector, value) {
  const locator = root.locator(selector).first();
  await locator.waitFor({ state: "visible", timeout: 2000 }).catch(() => null);
  const tagName = await locator.evaluate((node) => (node.tagName || "").toLowerCase()).catch(() => "");
  if (tagName === "input" || tagName === "textarea") {
    await locator.fill("");
    await locator.fill(value);
    return true;
  }
  await locator.click({ timeout: 2000 }).catch(() => null);
  await browserPage.keyboard.press("Control+A").catch(() => null);
  await browserPage.keyboard.press("Backspace").catch(() => null);
  const inserted = await locator.evaluate((node, text) => {
    const target = node;
    target.focus();
    if (document.execCommand) {
      try {
        document.execCommand("insertText", false, text);
      } catch {}
    }
    if (!String(target.innerText || target.textContent || "").trim()) {
      target.textContent = text;
    }
    target.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
    target.dispatchEvent(new Event("change", { bubbles: true }));
    return String(target.innerText || target.textContent || target.value || "").includes(text.slice(0, 10));
  }, value).catch(() => false);
  return inserted;
}

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function charSlice(text, limit) {
  return Array.from(String(text || "")).slice(0, Math.max(0, limit)).join("");
}

function buildBilibiliSafeTitle(title, limit = 48) {
  const normalized = normalizeText(title);
  if (Array.from(normalized).length <= limit) {
    return normalized;
  }
  const bracketMatch = normalized.match(/^【([^】]+)】(.+)$/);
  if (bracketMatch) {
    const rawPrefix = bracketMatch[1];
    const compactPrefix = rawPrefix.includes("|")
      ? rawPrefix.split("|")[0].trim()
      : rawPrefix.trim();
    const prefix = `【${compactPrefix}】`;
    const rest = normalizeText(bracketMatch[2]);
    const remaining = limit - Array.from(prefix).length;
    if (remaining > 8) {
      return `${prefix}${charSlice(rest, remaining)}`;
    }
  }
  return charSlice(normalized, limit);
}

function blockToEditorHtml(block) {
  const type = String(block?.type || "");
  if (type === "heading") {
    const level = Math.min(Math.max(Number(block?.level || 2), 1), 3);
    const tag = level === 1 ? "h1" : level === 2 ? "h2" : "h3";
    return `<${tag}>${String(block?.text || "")}</${tag}>`;
  }
  if (type === "paragraph") {
    return `<p>${String(block?.text || "")}</p>`;
  }
  if (type === "quote") {
    return `<p><em>${String(block?.text || "")}</em></p>`;
  }
  if (type === "list") {
    const tag = block?.ordered ? "ol" : "ul";
    const items = Array.isArray(block?.items) ? block.items : [];
    return `<${tag}>${items.map((item) => `<li>${String(item || "")}</li>`).join("")}</${tag}>`;
  }
  if (type === "code") {
    const language = normalizeText(block?.language || "");
    const cls = language ? ` class="language-${escapeHtml(language)}"` : "";
    return `<pre><code${cls}>${escapeHtml(String(block?.text || ""))}</code></pre>`;
  }
  if (type === "table") {
    const header = Array.isArray(block?.header) ? block.header : [];
    const rows = Array.isArray(block?.rows) ? block.rows : [];
    const thead = header.length
      ? `<thead><tr>${header.map((cell) => `<th>${String(cell || "")}</th>`).join("")}</tr></thead>`
      : "";
    const tbody = rows.length
      ? `<tbody>${rows.map((row) => `<tr>${(Array.isArray(row) ? row : []).map((cell) => `<td>${String(cell || "")}</td>`).join("")}</tr>`).join("")}</tbody>`
      : "";
    return `<table>${thead}${tbody}</table>`;
  }
  if (type === "image") {
    const caption = normalizeText(block?.caption || block?.alt || block?.purpose || "");
    return caption ? `<p><em>${caption}</em></p>` : "";
  }
  if (type === "divider") {
    return "<hr />";
  }
  return "";
}

async function clearEditorContent(locator) {
  return locator.evaluate((node) => {
    node.focus();
    if ("value" in node && typeof node.value === "string") {
      node.value = "";
    }
    if ("innerHTML" in node) {
      node.innerHTML = "";
    } else {
      node.textContent = "";
    }
    node.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "deleteContentBackward" }));
    node.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }).catch(() => false);
}

async function appendHtmlToEditor(locator, browserPage, html, plainText = "") {
  await locator.click({ timeout: 3000 }).catch(() => null);
  return locator.evaluate((node, payload) => {
    node.focus();
    const ensureSelectionAtEnd = () => {
      const selection = window.getSelection();
      if (!selection) {
        return;
      }
      const range = document.createRange();
      range.selectNodeContents(node);
      range.collapse(false);
      selection.removeAllRanges();
      selection.addRange(range);
    };
    ensureSelectionAtEnd();
    let inserted = false;
    if (document.execCommand) {
      try {
        inserted = document.execCommand("insertHTML", false, payload.html);
      } catch {
        inserted = false;
      }
    }
    if (!inserted) {
      if ("insertAdjacentHTML" in node) {
        node.insertAdjacentHTML("beforeend", payload.html);
      } else if ("innerHTML" in node) {
        node.innerHTML = `${String(node.innerHTML || "")}${payload.html}`;
      } else {
        node.textContent = `${String(node.textContent || "")}\n${payload.text}`;
      }
    }
    node.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertFromPaste", data: payload.text }));
    node.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }, { html, text: plainText }).catch(() => false);
}

async function downloadRemoteImageToTemp(sourceUrl) {
  const response = await fetch(sourceUrl);
  if (!response.ok) {
    throw new Error(`image_download_failed:${response.status}`);
  }
  const bytes = Buffer.from(await response.arrayBuffer());
  const url = new URL(sourceUrl);
  const ext = path.extname(url.pathname || "").trim() || ".png";
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "aimagician-bilibili-img-"));
  const filePath = path.join(tempDir, `image${ext}`);
  await fs.writeFile(filePath, bytes);
  return { filePath, temporary: true, tempDir };
}

async function resolveBodyImageUpload(block) {
  const sourcePath = normalizeText(block?.source_path || "");
  if (sourcePath && await pathExists(sourcePath)) {
    return { filePath: sourcePath, temporary: false, tempDir: "" };
  }
  const sourceUrl = normalizeText(block?.url || "");
  if (sourceUrl.startsWith("http://") || sourceUrl.startsWith("https://")) {
    return downloadRemoteImageToTemp(sourceUrl);
  }
  return { filePath: "", temporary: false, tempDir: "" };
}

async function uploadBodyImage(root, page, block) {
  let upload = { filePath: "", temporary: false, tempDir: "" };
  try {
    upload = await resolveBodyImageUpload(block);
    if (!upload.filePath) {
      return { uploaded: false, reason: "body_image_missing", selector: "" };
    }
    const trigger = await firstVisibleLocator(root, [
      "eva3-toolbar-image",
      "[class*='toolbar-image']",
      "button[aria-label*='图片']",
      "button:has-text('图片')",
    ], { timeout: 2000 });
    if (!trigger) {
      throw new Error("body_image_toolbar_missing");
    }
    const chooserPromise = page.waitForEvent("filechooser", { timeout: 4000 }).catch(() => null);
    await clickLocatorRobust(root, trigger.locator, page);
    const chooser = await chooserPromise;
    if (chooser) {
      await chooser.setFiles(upload.filePath);
    } else {
      const input = root.locator("input[type='file']").last();
      const count = await input.count().catch(() => 0);
      if (!count) {
        throw new Error("body_image_filechooser_missing");
      }
      await input.setInputFiles(upload.filePath);
    }
    await root.waitForTimeout(3000);
    return { uploaded: true, reason: "", selector: trigger.selector };
  } catch (error) {
    return {
      uploaded: false,
      reason: error instanceof Error ? error.message : "body_image_upload_failed",
      selector: "",
    };
  } finally {
    if (upload.temporary) {
      await fs.unlink(upload.filePath).catch(() => null);
      await fs.rmdir(upload.tempDir).catch(() => null);
    }
  }
}

async function readLocatorComparableText(locator) {
  return locator.evaluate((node) => {
    if ("value" in node && typeof node.value === "string") {
      return node.value;
    }
    return String(node.innerText || node.textContent || "");
  }).catch(() => "");
}

async function importMarkdownDocument(root, page, draft, expectedText, bodyLocator = null) {
  const markdownFile = normalizeText(draft?.markdown_file || "");
  if (!markdownFile || !await pathExists(markdownFile)) {
    return { imported: false, reason: "markdown_file_missing", selector: "" };
  }
  const trigger = await firstVisibleLocator(root, [
    "xpath=/html/body/div/div[1]/div/eva3-toolbar-import//eva3-tooltip/eva3-button",
    "eva3-toolbar-import eva3-button",
    "eva3-toolbar-import",
    "button:has-text('导入')",
    "[aria-label*='导入']",
    "[data-tooltip*='导入']",
  ], { timeout: 3000 });
  if (!trigger) {
    return { imported: false, reason: "markdown_import_button_missing", selector: "" };
  }
  const chooserPromise = page.waitForEvent("filechooser", { timeout: 5000 }).catch(() => null);
  await clickLocatorRobust(root, trigger.locator, page);
  const chooser = await chooserPromise;
  if (chooser) {
    await chooser.setFiles(markdownFile);
  } else {
    const input = root.locator("eva3-toolbar-import input[type='file'], input[type='file']").last();
    const count = await input.count().catch(() => 0);
    if (!count) {
      return { imported: false, reason: "markdown_import_failed", selector: trigger.selector };
    }
    await input.setInputFiles(markdownFile);
  }
  const normalizedExpected = normalizeText(expectedText);
  const probe = normalizedExpected.slice(0, 80);
  const tailProbe = normalizedExpected.length > 1000
    ? normalizedExpected.slice(Math.floor(normalizedExpected.length * 0.65), Math.floor(normalizedExpected.length * 0.65) + 80)
    : "";
  const expectedLength = normalizedExpected.length;
  let editorText = "";
  let rootText = "";
  let imported = false;
  let lastSignals = {
    hasTailProbe: false,
    hasEnoughBody: false,
    hasReference: false,
  };
  for (let attempt = 0; attempt < 45; attempt += 1) {
    await root.waitForTimeout(1000);
    editorText = bodyLocator
      ? await readLocatorComparableText(bodyLocator)
      : await root.locator("body").innerText().catch(() => "");
    rootText = await root.locator("body").innerText().catch(() => "");
    const normalizedEditor = normalizeText(editorText);
    const hasProbe = probe ? normalizedEditor.includes(probe.slice(0, 30)) : false;
    const hasTailProbe = tailProbe ? normalizedEditor.includes(tailProbe.slice(0, 30)) : false;
    const hasEnoughBody = expectedLength > 800
      ? normalizedEditor.length >= Math.min(Math.floor(expectedLength * 0.45), 5000)
      : normalizedEditor.length > 120;
    const hasReference = normalizedEditor.includes("参考文献");
    lastSignals = { hasTailProbe, hasEnoughBody, hasReference };
    if (expectedLength > 800 ? (hasEnoughBody || hasTailProbe || hasReference) : (hasProbe || hasEnoughBody)) {
      imported = true;
      break;
    }
  }
  return {
    imported,
    reason: imported ? "" : "markdown_import_failed",
    selector: trigger.selector,
    observed_text_length: normalizeText(editorText).length,
    observed_root_text_length: normalizeText(rootText).length,
    expected_text_length: expectedLength,
    ...lastSignals,
  };
}

async function fillTitle(root, browserPage, title) {
  if (!normalizeText(title)) {
    return { filled: false, selector: "", reason: "title_missing" };
  }
  const resolved = await resolveTitleSelector(root);
  if (!resolved?.selector) {
    return { filled: false, selector: "", reason: "title_input_not_found" };
  }
  const titleLocator = root.locator(resolved.selector).first();
  const maxLength = await titleLocator.evaluate((node) => Number(node.getAttribute("maxlength") || node.maxLength || 0)).catch(() => 0);
  const titleToWrite = maxLength > 0 && Array.from(normalizeText(title)).length >= maxLength
    ? buildBilibiliSafeTitle(title, Math.max(10, maxLength - 2))
    : title;
  const filled = await setPlainValue(root, browserPage, resolved.selector, titleToWrite);
  return {
    filled,
    selector: resolved.selector,
    written_title: titleToWrite,
    truncated: normalizeText(titleToWrite) !== normalizeText(title),
    reason: filled ? "" : "title_fill_failed",
  };
}

async function fillBody(root, browserPage, draft) {
  const bodyHtml = String(draft?.body_html || "").trim();
  const bodyText = String(draft?.body_text || draft?.body_markdown || "").trim();
  if (!bodyHtml && !bodyText) {
    return { filled: false, selector: "", reason: "article_markdown_missing" };
  }
  const resolved = await resolveBodySelector(root);
  if (!resolved?.selector) {
    return { filled: false, selector: "", reason: "editor_body_not_found" };
  }
  const locator = root.locator(resolved.selector).first();
  await locator.waitFor({ state: "visible", timeout: 3000 }).catch(() => null);
  await locator.click({ timeout: 3000 }).catch(() => null);
  const tagName = await locator.evaluate((node) => (node.tagName || "").toLowerCase()).catch(() => "");

  let filled = false;
  let importAttempt = null;
  const blocks = Array.isArray(draft?.body_blocks) ? draft.body_blocks : [];
  const useStructuredBlocks = tagName !== "textarea" && blocks.length > 0;
  if (tagName === "textarea") {
    await locator.fill(bodyText);
    filled = true;
  } else {
    if (normalizeText(draft?.markdown_file || "")) {
      await clearEditorContent(locator);
      const imported = await importMarkdownDocument(root, browserPage, draft, bodyText, locator);
      importAttempt = imported;
      if (imported.imported) {
        return {
          filled: true,
          selector: imported.selector,
          reason: "",
          mode: "markdown_import",
          import_observed_text_length: imported.observed_text_length,
          import_observed_root_text_length: imported.observed_root_text_length,
          import_expected_text_length: imported.expected_text_length,
          import_has_tail_probe: imported.hasTailProbe,
          import_has_enough_body: imported.hasEnoughBody,
          import_has_reference: imported.hasReference,
        };
      }
    }
    if (useStructuredBlocks) {
    await clearEditorContent(locator);
    let insertedCount = 0;
    for (const block of blocks) {
      const type = String(block?.type || "");
      if (type === "image") {
        const upload = await uploadBodyImage(root, browserPage, block);
        if (upload.uploaded) {
          const captionHtml = blockToEditorHtml(block);
          if (captionHtml) {
            await root.waitForTimeout(1200);
            const captionText = normalizeText(block?.caption || block?.alt || block?.purpose || "");
            await appendHtmlToEditor(locator, browserPage, captionHtml, captionText);
          }
          insertedCount += 1;
          continue;
        }
        const fallbackLabel = normalizeText(block?.alt || "") || normalizeText(block?.purpose || "") || "配图";
        const fallbackHtml = `<p>[图片] ${fallbackLabel}</p>`;
        const fallbackApplied = await appendHtmlToEditor(locator, browserPage, fallbackHtml, fallbackLabel);
        if (fallbackApplied) {
          insertedCount += 1;
        }
        continue;
      }
      const blockHtml = blockToEditorHtml(block);
      if (!blockHtml) {
        continue;
      }
      const plainText = normalizeText(block?.text || "")
        || (Array.isArray(block?.items) ? block.items.join(" ") : "")
        || (Array.isArray(block?.header) ? block.header.join(" ") : "");
      const appended = await appendHtmlToEditor(locator, browserPage, blockHtml, plainText);
      if (appended) {
        insertedCount += 1;
      }
    }
    filled = insertedCount >= Math.max(3, Math.floor(blocks.length * 0.6));
    } else {
    filled = await locator.evaluate((node, payload) => {
      const target = node;
      target.focus();
      const html = String(payload.html || "");
      const text = String(payload.text || "");
      if (document.execCommand) {
        try {
          document.execCommand("selectAll", false);
          document.execCommand("delete", false);
        } catch {}
        try {
          if (html) {
            document.execCommand("insertHTML", false, html);
          } else {
            document.execCommand("insertText", false, text);
          }
        } catch {}
      }
      const nextValue = String(target.innerText || target.textContent || "").trim();
      if (!nextValue) {
        if (html && "innerHTML" in target) {
          target.innerHTML = html;
        } else {
          target.textContent = text;
        }
      }
      target.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertFromPaste", data: text }));
      target.dispatchEvent(new Event("change", { bubbles: true }));
      const finalText = String(target.innerText || target.textContent || "").trim();
      return finalText.length >= Math.min(Math.max(text.length / 5, 30), 160);
    }, { html: bodyHtml, text: bodyText }).catch(() => false);
    }
  }
  await root.waitForTimeout(800);
  return {
    filled,
    selector: resolved.selector,
    reason: filled ? "" : (useStructuredBlocks ? "structured_body_insert_failed" : "editor_html_insert_failed"),
    mode: tagName === "textarea" ? "textarea" : (useStructuredBlocks ? "structured_blocks" : "html_insert"),
    import_observed_text_length: importAttempt?.observed_text_length ?? null,
    import_observed_root_text_length: importAttempt?.observed_root_text_length ?? null,
    import_expected_text_length: importAttempt?.expected_text_length ?? null,
    import_has_tail_probe: importAttempt?.hasTailProbe ?? null,
    import_has_enough_body: importAttempt?.hasEnoughBody ?? null,
    import_has_reference: importAttempt?.hasReference ?? null,
  };
}

async function fillAbstract(root, browserPage, abstract) {
  const value = normalizeText(abstract);
  if (!value) {
    return { filled: false, selector: "", reason: "" };
  }
  const resolved = await resolveAbstractSelector(root);
  if (!resolved?.selector) {
    return { filled: false, selector: "", reason: "abstract_input_not_found" };
  }
  const filled = await setPlainValue(root, browserPage, resolved.selector, value);
  return {
    filled,
    selector: resolved.selector,
    reason: filled ? "" : "abstract_fill_failed",
  };
}

async function applyTags(root, browserPage, tags) {
  const normalized = Array.isArray(tags) ? tags.map((item) => normalizeText(item)).filter(Boolean).slice(0, 5) : [];
  if (!normalized.length) {
    return { applied: false, selector: "", appliedTags: [], reason: "" };
  }
  const resolved = await resolveTagSelector(root);
  if (!resolved?.selector) {
    return { applied: false, selector: "", appliedTags: [], reason: "tag_input_not_found" };
  }
  const locator = root.locator(resolved.selector).first();
  const applied = [];
  for (const tag of normalized) {
    await locator.click({ timeout: 2000 }).catch(() => null);
    const success = await setPlainValue(root, browserPage, resolved.selector, tag);
    if (!success) {
      continue;
    }
    await browserPage.keyboard.press("Enter").catch(() => null);
    await root.waitForTimeout(400);
    applied.push(tag);
  }
  return {
    applied: applied.length > 0,
    selector: resolved.selector,
    appliedTags: applied,
    reason: applied.length > 0 ? "" : "tag_apply_failed",
  };
}

async function clickDraftButton(root, page) {
  const match = await firstVisibleLocator(root, [
    "button:has-text('保存草稿')",
    "button:has-text('存为草稿')",
    "button:has-text('草稿')",
    "text=保存草稿",
  ], { timeout: 1500 });
  if (!match) {
    return {
      clicked: false,
      selector: "",
      reason: "draft_button_missing",
    };
  }
  const clicked = await clickLocatorRobust(root, match.locator, page);
  return {
    clicked,
    selector: match.selector,
    reason: clicked ? "" : "draft_button_click_failed",
  };
}

async function confirmDraftSaved(root, timeoutMs) {
  const deadline = Date.now() + Math.max(timeoutMs, 8000);
  while (Date.now() < deadline) {
    const signals = await collectPageSignals(root);
    if (signals.draftSaved) {
      return {
        confirmed: true,
        reason: "",
      };
    }
    if (signals.validationMessage) {
      return {
        confirmed: false,
        reason: `draft_validation_failed:${signals.validationMessage}`,
      };
    }
    await root.waitForTimeout(700);
  }
  return {
    confirmed: false,
    reason: "draft_save_not_confirmed",
  };
}

async function clickPrimaryPublish(root, page) {
  const exactPublish = root.getByRole("button", { name: /^发布$/ }).last();
  const exactCount = await exactPublish.count().catch(() => 0);
  if (exactCount && await exactPublish.isVisible({ timeout: 1500 }).catch(() => false)) {
    const clicked = await clickLocatorRobust(root, exactPublish, page);
    if (clicked) {
      await root.waitForTimeout(1500);
    }
    return {
      clicked,
      selector: "role=button[name=/^发布$/]",
      reason: clicked ? "" : "publish_button_click_failed",
    };
  }
  const match = await firstVisibleLocator(root, [
    "button:has-text('发布文章')",
    "button:has-text('发布专栏')",
    "button:has-text('投稿')",
    "button:has-text('发布')",
  ], { timeout: 2000 });
  if (!match) {
    return {
      clicked: false,
      selector: "",
      reason: "publish_button_missing",
    };
  }
  const clicked = await clickLocatorRobust(root, match.locator, page);
  if (clicked) {
    // 点击后等待对话框出现
    await root.waitForTimeout(1500);
  }
  return {
    clicked,
    selector: match.selector,
    reason: clicked ? "" : "publish_button_click_failed",
  };
}

async function clickLastVisibleRoleButton(roots, name, fallbackPage, selectorLabel, timeoutMs = 5000) {
  const deadline = Date.now() + Math.max(timeoutMs, 1000);
  while (Date.now() < deadline) {
    for (const root of roots) {
      if (!root || typeof root.getByRole !== "function") {
        continue;
      }
      const locator = root.getByRole("button", { name });
      const count = await locator.count().catch(() => 0);
      for (let index = count - 1; index >= 0; index -= 1) {
        const candidate = locator.nth(index);
        if (!await candidate.isVisible({ timeout: 300 }).catch(() => false)) {
          continue;
        }
        const clicked = await clickLocatorRobust(root, candidate, fallbackPage);
        return {
          clicked,
          selector: `${selectorLabel}[${index}]`,
          reason: clicked ? "" : "role_button_click_failed",
        };
      }
    }
    await fallbackPage.waitForTimeout(400).catch(() => null);
  }
  return {
    clicked: false,
    selector: "",
    reason: "role_button_missing",
  };
}

async function collectPublishButtonCandidates(page, preferredRoot = null) {
  const selectors = [
    ".publish-footer .footer-right button.vui_button--blue:has-text('发布')",
    ".publish-footer button.vui_button--blue:has-text('发布')",
    "[class*='publish-footer'] [class*='footer-right'] button:has-text('发布')",
    "[class*='publish-footer'] button:has-text('发布')",
    "[class*='footer-right'] button:has-text('发布')",
    ".publish-settings button.vui_button--blue:has-text('发布')",
    ".publish-settings button:has-text('发布')",
    "button.vui_button--blue:has-text('发布')",
    "button:has-text('发布')",
    "[role='button']:has-text('发布')",
    "eva3-button:has-text('发布')",
  ];
  const roots = [];
  if (preferredRoot) {
    roots.push({ label: "preferredRoot", root: preferredRoot });
  }
  roots.push({ label: "page", root: page });
  for (const frame of page.frames()) {
    if (frame && frame !== preferredRoot) {
      roots.push({ label: `frame:${String(frame.url() || "").slice(0, 80)}`, root: frame });
    }
  }

  const viewport = page.viewportSize?.() || DEFAULT_VIEWPORT;
  const candidates = [];
  for (const { label, root } of roots) {
    if (!root || typeof root.locator !== "function") {
      continue;
    }
    for (const selector of selectors) {
      const locator = root.locator(selector);
      const count = await locator.count().catch(() => 0);
      for (let index = 0; index < Math.min(count, 8); index += 1) {
        const candidate = locator.nth(index);
        if (!await candidate.isVisible({ timeout: 200 }).catch(() => false)) {
          continue;
        }
        const box = await candidate.boundingBox().catch(() => null);
        const enabled = await candidate.isEnabled({ timeout: 200 }).catch(() => true);
        const metadata = await candidate.evaluate((node) => {
          const style = window.getComputedStyle(node);
          return {
            text: String(node.innerText || node.textContent || "").replace(/\s+/g, " ").trim(),
            className: String(node.className || ""),
            ariaLabel: String(node.getAttribute("aria-label") || ""),
            disabled: Boolean(node.disabled || node.getAttribute("disabled")),
            pointerEvents: style.pointerEvents,
            opacity: Number.parseFloat(style.opacity || "1"),
          };
        }).catch(() => ({
          text: "",
          className: "",
          ariaLabel: "",
          disabled: false,
          pointerEvents: "",
          opacity: 1,
        }));
        const text = normalizeText(metadata.text || metadata.ariaLabel || "");
        if (!text.includes("发布")) {
          continue;
        }
        if (!enabled || metadata.disabled || metadata.pointerEvents === "none" || metadata.opacity === 0) {
          continue;
        }
        let score = 0;
        if (/^发布$/.test(text)) score += 100;
        if (selector.includes("publish-footer")) score += 80;
        if (selector.includes("footer-right")) score += 70;
        if (selector.includes("vui_button--blue") || String(metadata.className || "").includes("vui_button--blue")) {
          score += 50;
        }
        if (label === "preferredRoot") score += 20;
        if (box) {
          const centerX = box.x + box.width / 2;
          const centerY = box.y + box.height / 2;
          if (centerX > viewport.width * 0.55) score += 30;
          if (centerY > viewport.height * 0.55) score += 30;
          if (box.width >= 48 && box.height >= 24) score += 10;
        }
        candidates.push({
          locator: candidate,
          selector,
          rootLabel: label,
          index,
          text,
          className: String(metadata.className || ""),
          box,
          score,
        });
      }
    }
  }
  candidates.sort((left, right) => right.score - left.score);
  return candidates;
}

function summarizePublishButtonCandidates(candidates) {
  return candidates.slice(0, 10).map((candidate) => ({
    selector: candidate.selector,
    root: candidate.rootLabel,
    index: candidate.index,
    text: candidate.text,
    className: candidate.className,
    box: candidate.box,
    score: candidate.score,
  }));
}

async function clickFinalPublishCandidateWithRetries(root, page, candidate, maxAttempts = 3) {
  const attempts = [];
  let clicked = false;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const beforeUrl = page.url();
    const beforeVisible = await candidate.locator.isVisible({ timeout: 300 }).catch(() => false);
    const clickedNow = await activateLocatorAggressively(root, candidate.locator, page);
    clicked = clicked || clickedNow;
    await page.waitForTimeout(2200);
    const afterUrl = page.url();
    const afterVisible = await candidate.locator.isVisible({ timeout: 300 }).catch(() => false);
    const signals = await collectPageSignals(page);
    const detected = await detectSurface(page);
    attempts.push({
      attempt,
      clicked: clickedNow,
      before_url: beforeUrl,
      after_url: afterUrl,
      before_visible: beforeVisible,
      after_visible: afterVisible,
      surface: detected.surface,
      publish_success_seen: signals.publishSuccessSeen,
      validation_message: signals.validationMessage,
      manual_clearance_required: signals.manualClearanceRequired,
      daily_submission_limit_reached: signals.dailySubmissionLimitReached,
    });
    if (
      isPublicArticleUrl(afterUrl)
      || signals.publishSuccessSeen
      || signals.validationMessage
      || signals.manualClearanceRequired
      || signals.dailySubmissionLimitReached
      || detected.surface === "published"
      || detected.surface === "blocked"
      || detected.surface === "daily-limit"
    ) {
      break;
    }
    if (!afterVisible && clickedNow) {
      break;
    }
  }
  return {
    clicked,
    attempts,
  };
}

async function clickFinalPublish(root, page) {
  // B站第一次点击“发布”后会打开右侧“发布设置”面板；真正提交需要再点面板底部的蓝色发布按钮。
  await page.waitForTimeout(1500);

  const candidates = await collectPublishButtonCandidates(page, root);
  if (candidates.length) {
    const selected = candidates[0];
    const clickResult = await clickFinalPublishCandidateWithRetries(root, page, selected, 3);
    return {
      clicked: clickResult.clicked,
      selector: `${selected.rootLabel}:${selected.selector}[${selected.index}]`,
      reason: clickResult.clicked ? "" : "final_publish_button_click_failed",
      attempts: clickResult.attempts,
      diagnostics: summarizePublishButtonCandidates(candidates),
    };
  }

  const roots = [page, root, ...page.frames()].filter(Boolean);
  const rolePublish = await clickLastVisibleRoleButton(
    roots,
    /^发布$/,
    page,
    "role=button[name=/^发布$/]",
    8000,
  );
  if (rolePublish.clicked) {
    return {
      clicked: true,
      selector: rolePublish.selector,
      reason: "",
      attempts: [],
      diagnostics: [],
    };
  }

  const match = await firstVisibleLocatorAcrossFrames(page, [
    "[role='dialog'] button:has-text('确认发布')",
    "[role='dialog'] button:has-text('确认投稿')",
    "[role='dialog'] button:has-text('发布')",
    "[role='dialog'] eva3-button:has-text('发布')",
    ".dialog button:has-text('确认发布')",
    ".dialog button:has-text('发布')",
    ".publish-settings button:has-text('发布')",
    ".publish-settings button:has-text('确认发布')",
    ".publish-settings eva3-button:has-text('发布')",
    "eva3-button:has-text('确认发布')",
    "eva3-button:has-text('立即发布')",
    "eva3-button:has-text('发布')",
    "[class*='publish'] [class*='button']:has-text('发布')",
    "[class*='submit']:has-text('发布')",
    "[class*='btn']:has-text('发布')",
    "button:has-text('确认发布')",
    "button:has-text('立即发布')",
  ], { timeout: 5000 });
  if (!match) {
    await page.waitForTimeout(2500);
    const signals = await collectPageSignals(page);
    const detected = await detectSurface(page);
    if (
      signals.publishSuccessSeen
      || signals.dailySubmissionLimitReached
      || signals.manualClearanceRequired
      || detected.surface === "published"
      || detected.surface === "daily-limit"
      || detected.surface === "blocked"
    ) {
      return {
        clicked: true,
        selector: "implicit_publish_transition",
        reason: "",
        attempts: [],
        diagnostics: [],
      };
    }
    return {
      clicked: false,
      selector: "",
      reason: "final_publish_button_missing",
      attempts: [],
      diagnostics: [],
    };
  }
  const clicked = await clickLocatorRobust(match.root || page, match.locator, page);
  return {
    clicked,
    selector: match.selector,
    reason: clicked ? "" : "final_publish_button_click_failed",
    attempts: [],
    diagnostics: [],
  };
}

function normalizeComparableText(value) {
  return String(value || "")
    .replace(/\s+/g, "")
    .replace(/[“”"'`·•:：]/g, "")
    .trim();
}

function resolveCandidateUrl(item) {
  const direct = [
    item.url,
    item.view_url,
    item.pre_view_url,
    item.preview_url,
    item.article_url,
    item.read_url,
    item.jump_url,
    item.share_url,
  ].find((value) => typeof value === "string" && value.trim());
  if (direct) {
    return String(direct).trim();
  }
  const dynId = item.dyn_id || item.dynamic_id || item.opus_id || "";
  if (/^\d+$/.test(String(dynId || "").trim())) {
    return `https://www.bilibili.com/opus/${String(dynId).trim()}`;
  }
  const rawId = item.cvid || item.cv || item.rid || item.article_id || item.id || item.articleId || "";
  const textId = String(rawId || "").trim();
  if (/^\d+$/.test(textId)) {
    return `https://www.bilibili.com/read/cv${textId}`;
  }
  return "";
}

function flattenArticleItems(payload) {
  if (Array.isArray(payload)) {
    return payload;
  }
  if (!payload || typeof payload !== "object") {
    return [];
  }
  const sources = [
    payload.articles,
    payload.article_list,
    payload.list,
    payload.items,
    payload.data,
  ];
  for (const source of sources) {
    if (Array.isArray(source)) {
      return source;
    }
    if (source && typeof source === "object") {
      const nested = flattenArticleItems(source);
      if (nested.length) {
        return nested;
      }
    }
  }
  return [];
}

async function resolvePublishedArticleUrlFromPage(page) {
  const links = await page.locator("a[href]").evaluateAll((nodes) => nodes
    .map((node) => {
      const raw = String(node.getAttribute("href") || node.href || "").trim();
      if (!raw) {
        return "";
      }
      try {
        return new URL(raw, window.location.href).toString();
      } catch {
        return raw;
      }
    })
    .filter((value) => PUBLIC_URL_PATTERN.test(value))
    .slice(0, 12)).catch(() => []);
  const uniqueLinks = [...new Set(Array.isArray(links) ? links : [])];
  if (uniqueLinks.length) {
    return {
      found: true,
      url: uniqueLinks[0],
      title: "",
      reviewStatus: "",
      source: "page_anchor_href",
    };
  }
  const bodyUrl = await page.locator("body").evaluate((node) => {
    const text = String(node?.innerText || node?.textContent || "");
    const match = text.match(/https:\/\/www\.bilibili\.com\/(?:read\/cv\d+|opus\/\d+)\/?/i);
    return match ? match[0] : "";
  }).catch(() => "");
  if (bodyUrl) {
    return {
      found: true,
      url: bodyUrl,
      title: "",
      reviewStatus: "",
      source: "page_text_url",
    };
  }
  return {
    found: false,
    url: "",
    title: "",
    reviewStatus: "",
    source: "page_link_missing",
  };
}

async function resolvePublishedArticleUrl(page, articleTitle) {
  const normalizedTitle = normalizeComparableText(articleTitle);
  if (!normalizedTitle) {
    return {
      found: false,
      url: "",
      title: "",
      reviewStatus: "",
      source: "missing_title",
    };
  }
  const cookieHeader = buildCookieHeader(await page.context().cookies().catch(() => []));
  const items = [];
  const lookupErrors = [];
  for (const lookupUrl of [OPUS_CREATION_LIST_URL, ARTICLE_LIST_URL]) {
    const response = await fetchProbe(lookupUrl, cookieHeader, DEFAULT_EDITOR_URL);
    if (response.api_code !== 0) {
      lookupErrors.push(response.api_message || "article_list_lookup_failed");
      continue;
    }
    items.push(...flattenArticleItems(response.data));
  }
  if (!items.length) {
    return {
      found: false,
      url: "",
      title: "",
      reviewStatus: "",
      source: lookupErrors[0] || "creative_article_list_no_items",
    };
  }
  let best = null;
  for (const item of items) {
    if (!item || typeof item !== "object") {
      continue;
    }
    const title = normalizeText(item.title || item.article_title || item.name || item.subject || "");
    const normalized = normalizeComparableText(title);
    if (!normalized) {
      continue;
    }
    const matches = normalized === normalizedTitle
      || normalized.includes(normalizedTitle)
      || normalizedTitle.includes(normalized);
    if (!matches) {
      continue;
    }
    const url = resolveCandidateUrl(item);
    if (!url) {
      continue;
    }
    const filterGroup = item.filter_group && typeof item.filter_group === "object" ? item.filter_group : {};
    const reviewStatus = normalizeText(item.state_desc || item.status_desc || item.state || item.status || filterGroup.reason || filterGroup.filter_type || "");
    best = {
      found: true,
      url,
      title,
      reviewStatus,
      source: "creative_article_list_match",
    };
    if (normalized === normalizedTitle) {
      break;
    }
  }
  return best || {
    found: false,
    url: "",
    title: "",
    reviewStatus: "",
    source: "creative_article_list_no_match",
  };
}

async function resolvePublishedUrl(runtime, args, stateFile, timeoutMs, payload) {
  const { context, page, profileDir, authMaterialSource } = runtime;
  const title = normalizeText(payload?.title || payload?.draft?.title || payload?.article?.title || "");
  if (!title) {
    throw new Error("payload_missing_title");
  }
  await checkpointProgress(args, "resolve_published_url_lookup", {
    title,
    profile_dir: profileDir,
  });
  await page.goto(DEFAULT_EDITOR_URL, { waitUntil: "domcontentloaded", timeout: timeoutMs }).catch(() => null);
  await page.waitForTimeout(1200);
  const lookup = await resolvePublishedArticleUrl(page, title);
  const evidence = await capturePageEvidence(page, args, "resolve-published-url", {
    title,
    published_article_url: lookup.url || "",
    published_review_status: lookup.reviewStatus || "",
    publish_resolution_source: lookup.source || "",
  });
  const { stateSaved, stateSaveError } = await saveSessionStateSafely(context, stateFile);
  return {
    status: lookup.found ? "ok" : "blocked",
    mode: "resolve-published-url",
    live_ready: lookup.found,
    final_url: lookup.url || page.url(),
    page_title: lookup.title || await page.title().catch(() => ""),
    state_file: stateFile,
    state_file_written: stateSaved,
    state_file_write_error: stateSaveError,
    browser_profile_dir: profileDir,
    auth_material_source: authMaterialSource,
    published_article_url: lookup.url || "",
    published_review_status: lookup.reviewStatus || "",
    publish_resolution_source: lookup.source || "",
    final_blocker: lookup.found ? "" : lookup.source,
    evidence: {
      dir: evidenceDirFromArgs(args),
      snapshots: [evidence].filter(Boolean),
    },
  };
}

async function waitForPublishResult(runtime, page, timeoutMs, articleTitle) {
  const deadline = Date.now() + Math.max(timeoutMs, 60000);
  let successSeen = false;
  let lastSignals = await collectPageSignals(page);
  let attempts = 0;
  while (Date.now() < deadline) {
    attempts += 1;
    await page.waitForTimeout(1500);
    const currentUrl = page.url();
    if (isPublicArticleUrl(currentUrl)) {
      return {
        confirmed: true,
        publishedArticleUrl: currentUrl,
        reviewStatus: "",
        source: "current_page_url",
        finalBlocker: "",
        validationMessage: "",
      };
    }
    const pageResolved = await resolvePublishedArticleUrlFromPage(page);
    if (pageResolved.found && pageResolved.url) {
      return {
        confirmed: true,
        publishedArticleUrl: pageResolved.url,
        reviewStatus: pageResolved.reviewStatus || "",
        source: pageResolved.source,
        finalBlocker: "",
        validationMessage: "",
      };
    }
    lastSignals = await collectPageSignals(page);
    if (lastSignals.dailySubmissionLimitReached) {
      return {
        confirmed: false,
        publishedArticleUrl: "",
        reviewStatus: "",
        source: "daily_submission_limit_reached",
        finalBlocker: "daily_submission_limit_reached",
        validationMessage: lastSignals.dailySubmissionLimitMarker || "",
      };
    }
    if (lastSignals.validationMessage) {
      return {
        confirmed: false,
        publishedArticleUrl: "",
        reviewStatus: "",
        source: "publish_validation_message",
        finalBlocker: `publish_validation_failed:${lastSignals.validationMessage}`,
        validationMessage: lastSignals.validationMessage,
      };
    }
    if (lastSignals.publishSuccessSeen) {
      successSeen = true;
      // 发布成功后，额外等待并检查文章列表
      await page.waitForTimeout(2000);
      const resolved = await resolvePublishedArticleUrl(page, articleTitle);
      if (resolved.found && resolved.url) {
        return {
          confirmed: true,
          publishedArticleUrl: resolved.url,
          reviewStatus: resolved.reviewStatus || "",
          source: "success_marker_list_resolve",
          finalBlocker: "",
          validationMessage: "",
        };
      }
      const editorRoot = resolveEditorFrame(page) || page;
      const viewButton = (
        await firstVisibleLocator(page, [
          "button:has-text('点击去看')",
          "button:has-text('点击查看')",
          "button:has-text('立即查看')",
          "button:has-text('查看')",
        ], { timeout: 500 })
      ) || await firstVisibleLocator(editorRoot, [
        "button:has-text('点击去看')",
        "button:has-text('点击查看')",
        "button:has-text('立即查看')",
        "button:has-text('查看')",
      ], { timeout: 500 });
      if (viewButton) {
        await clickLocatorRobust(page, viewButton.locator, page);
        await page.waitForTimeout(1200);
        const clickedUrl = page.url();
        if (isPublicArticleUrl(clickedUrl)) {
          return {
            confirmed: true,
            publishedArticleUrl: clickedUrl,
            reviewStatus: "",
            source: "success_dialog_view_button",
            finalBlocker: "",
            validationMessage: "",
          };
        }
      }
      return {
        confirmed: true,
        publishedArticleUrl: "",
        reviewStatus: "review_submitted",
        source: "success_dialog_review_submitted",
        finalBlocker: "",
        validationMessage: "",
      };
    }
    if (lastSignals.manualClearanceRequired) {
      return {
        confirmed: false,
        publishedArticleUrl: "",
        reviewStatus: "",
        source: "manual_clearance_required",
        finalBlocker: "manual_clearance_required_after_publish_click",
        validationMessage: "",
      };
    }
    const resolved = await resolvePublishedArticleUrl(page, articleTitle);
    if (resolved.found && resolved.url) {
      return {
        confirmed: true,
        publishedArticleUrl: resolved.url,
        reviewStatus: resolved.reviewStatus || "",
        source: resolved.source,
        finalBlocker: "",
        validationMessage: "",
      };
    }
  }
  return {
    confirmed: false,
    publishedArticleUrl: "",
    reviewStatus: "",
    source: successSeen ? "success_seen_url_missing" : "timeout",
    finalBlocker: successSeen
      ? "publish_success_seen_but_public_url_not_resolved"
      : "timeout_waiting_for_publish_result",
    validationMessage: lastSignals.validationMessage || "",
  };
}

async function prepareArticle(runtime, args, stateFile, timeoutMs, payload, submit, saveDraft) {
  const { context, page, profileDir, authMaterialSource } = runtime;
  const draft = payload?.draft && typeof payload.draft === "object" ? payload.draft : {};
  const title = normalizeText(draft.title || payload?.article?.title || "");
  const actionNetworkTrace = [];
  const recordNetworkEvent = (event) => {
    if (actionNetworkTrace.length >= 80) {
      return;
    }
    const url = String(event.url || "");
    if (!/bilibili|member|creative|article|upload|draft|submit|publish/i.test(url)) {
      return;
    }
    actionNetworkTrace.push({
      at: new Date().toISOString(),
      ...event,
      url: url.slice(0, 500),
    });
  };
  const onRequest = (request) => {
    const event = {
      type: "request",
      method: request.method(),
      url: request.url(),
      resource_type: request.resourceType(),
    };
    if (/\/x\/dynamic\/feed\/create\/opus|\/x\/article|creative|draft|submit|publish/i.test(request.url())) {
      const postData = request.postData() || "";
      if (postData) {
        event.post_data_length = postData.length;
        event.post_data_excerpt = postData.slice(0, 1200);
      }
    }
    recordNetworkEvent(event);
  };
  const onResponse = async (response) => {
    const request = response.request();
    const url = response.url();
    const event = {
      type: "response",
      method: request.method(),
      url,
      status: response.status(),
      resource_type: request.resourceType(),
    };
    if (/\/x\/article|creative|draft|submit|publish/i.test(url)) {
      const contentType = String(response.headers()["content-type"] || "");
      if (contentType.includes("json") || contentType.includes("text")) {
        event.body_excerpt = (await response.text().catch(() => "")).slice(0, 1000);
      }
    }
    recordNetworkEvent(event);
  };
  const onRequestFailed = (request) => {
    recordNetworkEvent({
      type: "requestfailed",
      method: request.method(),
      url: request.url(),
      resource_type: request.resourceType(),
      failure: request.failure()?.errorText || "",
    });
  };
  page.on("request", onRequest);
  page.on("response", onResponse);
  page.on("requestfailed", onRequestFailed);
  await checkpointProgress(args, "prepare_article_open_editor", {
    editor_url: DEFAULT_EDITOR_URL,
    profile_dir: profileDir,
    submit_requested: submit,
    save_draft_requested: saveDraft,
  });
  const detected = await openEditor(page, timeoutMs);
  const signals = await collectPageSignals(page);
  if (detected.surface !== "editor") {
    page.off("request", onRequest);
    page.off("response", onResponse);
    page.off("requestfailed", onRequestFailed);
    const blocker = detected.surface === "login"
      ? "session_invalid_or_missing"
      : detected.surface === "daily-limit"
        ? "daily_submission_limit_reached"
      : detected.surface === "blocked"
        ? "manual_clearance_required"
        : "editor_surface_not_reached";
    const evidence = await capturePageEvidence(page, args, "prepare-article-blocked", {
      surface: detected.surface,
      final_blocker: blocker,
    });
    return {
      status: "blocked",
      mode: "prepare-article",
      surface: detected.surface,
      final_url: page.url(),
      page_title: await page.title().catch(() => ""),
      state_file: stateFile,
      browser_profile_dir: profileDir,
      auth_material_source: authMaterialSource,
      manual_clearance_required: signals.manualClearanceRequired,
      final_blocker: blocker,
      reason: blocker,
      prepare_ready: false,
      draft_saved: false,
      publish_confirmed: false,
      published_article_url: "",
      evidence: {
        dir: evidenceDirFromArgs(args),
        snapshots: [evidence].filter(Boolean),
      },
    };
  }

  const editorRoot = resolveEditorFrame(page) || page;

  const titleResult = await fillTitle(editorRoot, page, title);
  const bodyResult = await fillBody(editorRoot, page, draft);
  const abstractResult = await fillAbstract(editorRoot, page, draft.abstract || "");
  const tagResult = await applyTags(editorRoot, page, draft.tags || []);
  const coverResult = await uploadCoverImage(editorRoot, page, draft);
  const originalResult = await ensureOriginalDeclaration(editorRoot, page, draft);
  const aiDeclarationResult = await ensureAiAssistedDeclaration(editorRoot, page, draft);
  const topicResult = await selectTopic(editorRoot, page, draft);
  const collectionResult = await selectCollection(editorRoot, page, draft);
  await editorRoot.waitForTimeout(1000);
  const preparedEvidence = await capturePageEvidence(page, args, "prepare-article-ready", {
    title_filled: titleResult.filled,
    title_written: titleResult.written_title || "",
    title_truncated: Boolean(titleResult.truncated),
    body_filled: bodyResult.filled,
    body_mode: bodyResult.mode || "",
    body_reason: bodyResult.reason || "",
    body_import_observed_text_length: bodyResult.import_observed_text_length ?? null,
    body_import_observed_root_text_length: bodyResult.import_observed_root_text_length ?? null,
    body_import_expected_text_length: bodyResult.import_expected_text_length ?? null,
    body_import_has_tail_probe: bodyResult.import_has_tail_probe ?? null,
    body_import_has_enough_body: bodyResult.import_has_enough_body ?? null,
    body_import_has_reference: bodyResult.import_has_reference ?? null,
    abstract_filled: abstractResult.filled,
    tags_applied: tagResult.appliedTags,
    cover_uploaded: coverResult.uploaded,
    original_checked: originalResult.checked,
    ai_declaration_checked: aiDeclarationResult.checked,
    topic_selected: topicResult.chosenTopic,
    collection_selected: collectionResult.chosenCollection,
  });
  actionNetworkTrace.length = 0;

  let finalBlocker = "";
  if (!titleResult.filled) {
    finalBlocker = titleResult.reason || "title_fill_failed";
  } else if (!bodyResult.filled) {
    finalBlocker = bodyResult.reason || "editor_html_insert_failed";
  }

  let draftSaved = false;
  let draftButton = { clicked: false, selector: "", reason: "" };
  let draftConfirmation = { confirmed: false, reason: "" };
  if (!finalBlocker && saveDraft) {
    draftButton = await clickDraftButton(editorRoot, page);
    if (!draftButton.clicked) {
      finalBlocker = draftButton.reason || "draft_button_missing";
    } else {
      draftConfirmation = await confirmDraftSaved(editorRoot, timeoutMs);
      draftSaved = draftConfirmation.confirmed;
      if (!draftSaved) {
        finalBlocker = draftConfirmation.reason || "draft_save_not_confirmed";
      }
    }
  }

  let publishButton = { clicked: false, selector: "", reason: "" };
  let finalPublish = { clicked: false, selector: "", reason: "" };
  let publishResult = {
    confirmed: false,
    publishedArticleUrl: "",
    reviewStatus: "",
    source: "",
    finalBlocker: "",
    validationMessage: "",
  };
  if (!finalBlocker && submit) {
    if (!coverResult.uploaded && coverResult.blocking !== false) {
      finalBlocker = coverResult.reason || "cover_upload_not_confirmed";
    } else if (!originalResult.checked) {
      finalBlocker = originalResult.reason || "original_declaration_not_confirmed";
    } else if (!aiDeclarationResult.checked) {
      finalBlocker = aiDeclarationResult.reason || "ai_declaration_not_confirmed";
    } else if (!collectionResult.selected) {
      finalBlocker = collectionResult.reason || "collection_selection_not_confirmed";
    } else {
      publishButton = await clickPrimaryPublish(editorRoot, page);
      if (!publishButton.clicked) {
        finalBlocker = publishButton.reason || "publish_button_missing";
      } else {
        await editorRoot.waitForTimeout(1200);
        finalPublish = await clickFinalPublish(editorRoot, page);
        if (finalPublish.clicked) {
          await editorRoot.waitForTimeout(800);
        }
        publishResult = await waitForPublishResult(runtime, page, timeoutMs, title);
        finalBlocker = publishResult.finalBlocker || (finalPublish.clicked ? "" : finalPublish.reason);
      }
    }
  }

  const { stateSaved, stateSaveError } = await saveSessionStateSafely(context, stateFile);
  page.off("request", onRequest);
  page.off("response", onResponse);
  page.off("requestfailed", onRequestFailed);
  const finalEvidence = await capturePageEvidence(page, args, finalBlocker ? "prepare-article-blocked" : "prepare-article-finished", {
    final_blocker: finalBlocker,
    draft_saved: draftSaved,
    publish_confirmed: publishResult.confirmed,
    published_article_url: publishResult.publishedArticleUrl,
    publish_button_selector: publishButton.selector,
    final_publish_selector: finalPublish.selector,
    final_publish_reason: finalPublish.reason,
    final_publish_attempts: finalPublish.attempts || [],
    final_publish_diagnostics: finalPublish.diagnostics || [],
    action_network_trace: actionNetworkTrace,
  });
  return {
    status: finalBlocker ? "blocked" : "ok",
    mode: "prepare-article",
    surface: (await detectSurface(page)).surface,
    final_url: publishResult.publishedArticleUrl || page.url(),
    page_title: await page.title().catch(() => ""),
    state_file: stateFile,
    state_file_written: stateSaved,
    state_file_write_error: stateSaveError,
    browser_profile_dir: profileDir,
    auth_material_source: authMaterialSource,
    title_filled: titleResult.filled,
    title_selector: titleResult.selector,
    title_written: titleResult.written_title || "",
    title_truncated: Boolean(titleResult.truncated),
    body_filled: bodyResult.filled,
    body_selector: bodyResult.selector,
    body_mode: bodyResult.mode || "",
    body_reason: bodyResult.reason || "",
    body_import_observed_text_length: bodyResult.import_observed_text_length ?? null,
    body_import_observed_root_text_length: bodyResult.import_observed_root_text_length ?? null,
    body_import_expected_text_length: bodyResult.import_expected_text_length ?? null,
    body_import_has_tail_probe: bodyResult.import_has_tail_probe ?? null,
    body_import_has_enough_body: bodyResult.import_has_enough_body ?? null,
    body_import_has_reference: bodyResult.import_has_reference ?? null,
    abstract_filled: abstractResult.filled,
    abstract_selector: abstractResult.selector,
    tags_applied: tagResult.applied,
    tag_selector: tagResult.selector,
    applied_tags: tagResult.appliedTags,
    cover_uploaded: coverResult.uploaded,
    cover_upload_reason: coverResult.reason,
    cover_input_index: coverResult.selected_input?.index ?? null,
    original_declaration_checked: originalResult.checked,
    original_declaration_reason: originalResult.reason,
    ai_declaration_checked: aiDeclarationResult.checked,
    ai_declaration_reason: aiDeclarationResult.reason,
    selected_topic: topicResult.chosenTopic,
    topic_reason: topicResult.reason,
    selected_collection: collectionResult.chosenCollection,
    collection_reason: collectionResult.reason,
    draft_saved: draftSaved,
    draft_button_selector: draftButton.selector,
    draft_save_reason: draftConfirmation.reason || draftButton.reason || "",
    publish_button_selector: publishButton.selector,
    final_publish_selector: finalPublish.selector,
    final_publish_reason: finalPublish.reason,
    final_publish_attempts: finalPublish.attempts || [],
    final_publish_diagnostics: finalPublish.diagnostics || [],
    action_network_trace: actionNetworkTrace,
    publish_confirmed: publishResult.confirmed,
    published_article_url: publishResult.publishedArticleUrl,
    published_review_status: publishResult.reviewStatus,
    publish_resolution_source: publishResult.source,
    validation_message: publishResult.validationMessage,
    manual_clearance_required: signals.manualClearanceRequired,
    prepare_ready: titleResult.filled && bodyResult.filled,
    final_blocker: finalBlocker,
    reason: finalBlocker,
    evidence: {
      dir: evidenceDirFromArgs(args),
      snapshots: [preparedEvidence, finalEvidence].filter(Boolean),
    },
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const action = String(args.action || "check-session");
  const stateFile = String(args["state-file"] || "").trim();
  const timeoutMs = Number.parseInt(String(args["timeout-ms"] || "45000"), 10) || 45000;
  const headless = parseBool(args.headless, action === "check-session");
  const payloadFile = String(args["payload-file"] || "").trim();
  const submit = parseBool(args.submit, false);
  const saveDraft = parseBool(args["save-draft"], false);

  let runtime = null;
  try {
    runtime = await launchBilibiliContext({
      headless,
      stateFile,
      preferPersistent: true,
      allowFreshPersistentProfile: action === "bootstrap-session",
    });
    runtime.page.on("dialog", (dialog) => {
      dialog.dismiss().catch(() => null);
    });

    let result;
    if (action === "bootstrap-session") {
      result = await bootstrapSession(runtime, args, stateFile, timeoutMs);
    } else if (action === "check-session") {
      result = await checkSession(runtime, args, stateFile, timeoutMs);
    } else if (action === "prepare-article") {
      const payload = await loadJsonFile(payloadFile);
      result = await prepareArticle(runtime, args, stateFile, timeoutMs, payload, submit, saveDraft);
    } else if (action === "resolve-published-url") {
      const payload = await loadJsonFile(payloadFile);
      result = await resolvePublishedUrl(runtime, args, stateFile, timeoutMs, payload);
    } else {
      throw new Error(`unsupported_action:${action}`);
    }

    await checkpointResult(args, result);
    process.exitCode = result.status === "ok" ? 0 : 1;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const finalUrl = runtime && runtime.page && typeof runtime.page.url === "function"
      ? runtime.page.url()
      : "";
    let pageTitle = "";
    if (runtime && runtime.page && typeof runtime.page.title === "function") {
      pageTitle = await runtime.page.title().catch(() => "");
    }
    const payload = {
      status: "error",
      platform: "B站专栏",
      mode: action,
      final_url: finalUrl,
      page_title: pageTitle || "",
      reason: message,
      final_blocker: message,
    };
    await checkpointResult(args, payload);
    process.exitCode = 1;
  } finally {
    await closeRuntime(runtime);
  }
}

main().catch((error) => {
  process.stderr.write(`${String(error?.stack || error)}\n`);
  process.exitCode = 1;
});
