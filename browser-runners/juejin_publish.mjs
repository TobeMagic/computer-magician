import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { clearStaleChromiumSingletonLocks } from "./profile_lock.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DEFAULT_PROFILE_DIR = path.resolve(__dirname, "credentials/juejin-browser-profile");
const DEFAULT_SMS_CODE_FILE = process.env.JUEJIN_SMS_CODE_FILE
  || path.resolve(__dirname, "credentials/juejin-sms-code.txt");
const DEFAULT_EDITOR_URL = process.env.JUEJIN_EDITOR_URL || "https://juejin.cn/editor/drafts/new?v=2";
const DEFAULT_LOCALE = process.env.JUEJIN_BROWSER_LOCALE || "zh-CN";
const DEFAULT_TIMEZONE = process.env.JUEJIN_BROWSER_TIMEZONE || "Asia/Shanghai";
const DEFAULT_USER_AGENT = process.env.JUEJIN_BROWSER_USER_AGENT
  || "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36";
const JUEJIN_USERNAME = (
  process.env.JUEJIN_USERNAME
  || process.env.JUEJIN_PHONE
  || process.env.AIMAGICIAN_PLATFORM_LOGIN_PHONE
  || ""
).trim();
const JUEJIN_PHONE = (
  process.env.JUEJIN_PHONE
  || process.env.JUEJIN_USERNAME
  || process.env.AIMAGICIAN_PLATFORM_LOGIN_PHONE
  || ""
).trim();
const JUEJIN_PASSWORD = (process.env.JUEJIN_PASSWORD || "").trim();
const MANUAL_CLEARANCE_MARKERS = [
  "安全验证",
  "请完成验证",
  "验证后继续",
  "拖动滑块",
  "滑块验证",
  "滑动验证",
  "拼图验证",
  "人机验证",
  "异常访问",
  "账号异常",
  "身份验证",
  "实名认证",
];
const REVIEW_PENDING_MARKERS = ["审核中", "发布成功", "提交成功"];
const VALIDATION_MARKERS = [
  "至少添加一个标签",
  "你还能添加",
  "请添加标签",
  "请选择文章封面",
  "请选择分类",
  "请填写摘要",
  "请填写标题",
];

function trimText(value) {
  return String(value || "").trim();
}

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
    return String(await fs.readFile(targetPath, "utf8") || "").trim();
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

function sanitizeFileStem(value) {
  return String(value || "")
    .trim()
    .replace(/[^a-z0-9._-]+/gi, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 80) || "juejin";
}

function evidenceDirFromArgs(args) {
  const raw = String(args["evidence-dir"] || "").trim();
  return raw ? path.resolve(raw) : "";
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
  const bodyText = await page.locator("body").innerText().catch(() => "");
  const payload = {
    label,
    url: page.url(),
    page_title: await page.title().catch(() => ""),
    body_excerpt: bodyText.slice(0, 4000),
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
  if (!page || page.isClosed()) {
    return {
      bodyExcerpt: "",
      manualClearanceRequired: false,
      manualClearanceMarker: "",
      reviewStatus: "",
      publishSuccessSeen: false,
      validationMessage: "",
    };
  }
  const bodyText = await page.locator("body").innerText().catch(() => "");
  const manualClearanceMarker = MANUAL_CLEARANCE_MARKERS.find((marker) => bodyText.includes(marker)) || "";
  const reviewStatus = bodyText.includes("审核中")
    ? "审核中"
    : (bodyText.includes("已发布") ? "已发布" : "");
  const validationMessage = VALIDATION_MARKERS.find((marker) => bodyText.includes(marker)) || "";
  return {
    bodyExcerpt: bodyText.slice(0, 4000),
    manualClearanceRequired: Boolean(manualClearanceMarker),
    manualClearanceMarker,
    reviewStatus,
    publishSuccessSeen: REVIEW_PENDING_MARKERS.some((marker) => bodyText.includes(marker)),
    validationMessage,
  };
}

async function readFirstVisibleText(page, selectors) {
  const match = await firstVisibleLocator(page, selectors);
  if (!match) {
    return { selector: "", text: "" };
  }
  const text = String(await match.locator.innerText().catch(() => "") || "").trim();
  return { selector: match.selector, text };
}

async function readFirstVisibleControlState(page, selectors) {
  const match = await firstVisibleLocator(page, selectors);
  if (!match) {
    return {
      selector: "",
      text: "",
      disabled: false,
      ariaDisabled: "",
      className: "",
    };
  }
  const snapshot = await match.locator.evaluate((node) => {
    const htmlNode = /** @type {HTMLElement} */ (node);
    const inputNode = node instanceof HTMLButtonElement || node instanceof HTMLInputElement
      ? node
      : null;
    return {
      text: (htmlNode.innerText || htmlNode.textContent || "").trim(),
      disabled: Boolean(inputNode?.disabled),
      ariaDisabled: htmlNode.getAttribute("aria-disabled") || "",
      className: htmlNode.getAttribute("class") || "",
    };
  }).catch(() => ({
    text: "",
    disabled: false,
    ariaDisabled: "",
    className: "",
  }));
  return {
    selector: match.selector,
    text: String(snapshot.text || "").trim(),
    disabled: Boolean(snapshot.disabled),
    ariaDisabled: String(snapshot.ariaDisabled || ""),
    className: String(snapshot.className || ""),
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
  return process.env.JUEJIN_BROWSER_PROFILE_DIR || DEFAULT_PROFILE_DIR;
}

async function launchJuejinContext(options) {
  const {
    headless,
    stateFile,
    preferPersistent = false,
    allowFreshPersistentProfile = false,
    preferStorageState = false,
  } = options;
  const profileDir = browserProfileDir();
  const persistentRequested = preferPersistent && parseBool(process.env.JUEJIN_PERSISTENT_BROWSER, true);
  const profileReady = await directoryHasEntries(profileDir);
  const stateFileReady = stateFile ? await pathExists(stateFile) : false;
  const persistent = persistentRequested
    && (!preferStorageState || !stateFileReady)
    && (profileReady || allowFreshPersistentProfile || !stateFileReady);
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
      profileReady,
      stateFileReady,
      authMaterialSource: profileReady ? "browser_profile" : "fresh_browser_profile",
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
  if (stateFileReady) {
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
        domain: ".juejin.cn",
        path: "/",
        httpOnly: false,
        secure: true,
        sameSite: "Lax",
      });
    }
    return cookies;
  }

  for (const name of ["sessionid", "sessionid_ss", "sid_guard"]) {
    cookies.push({
      name,
      value: raw,
      domain: ".juejin.cn",
      path: "/",
      httpOnly: false,
      secure: true,
      sameSite: "Lax",
    });
  }
  return cookies;
}

async function injectSessionCookies(context) {
  const cookies = parseSessionCookies(process.env.JUEJIN_SESSION || "");
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

async function detectSurface(page) {
  const url = page.url();
  const title = await page.title().catch(() => "");
  const signals = await collectPageSignals(page);

  const loginMatch = await firstVisibleLocator(page, [
    "text=登录掘金",
    "text=验证码登录 / 注册",
    "text=密码登录",
    "input[placeholder='请输入手机号']",
  ]);
  if (url.includes("/login") || loginMatch) {
    return {
      surface: "login",
      url,
      title,
      matched_selector: loginMatch?.selector || "",
    };
  }

  const editorMatch = await firstVisibleLocator(page, [
    "textarea[placeholder*='输入文章标题']",
    "input[placeholder*='输入文章标题']",
    "input[class*='title']",
    "div[contenteditable='true']",
    ".ProseMirror",
    ".editor-title-input",
    ".title-input",
  ]);
  if (url.includes("/editor/") || editorMatch) {
    return {
      surface: "editor",
      url,
      title,
      matched_selector: editorMatch?.selector || "",
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

  return {
    surface: "unknown",
    url,
    title,
    matched_selector: "",
  };
}

function maskUsername(username) {
  const raw = String(username || "").trim();
  if (!raw) {
    return "";
  }
  if (raw.length <= 4) {
    return `${raw[0] || "*"}***`;
  }
  return `${raw.slice(0, 3)}****${raw.slice(-2)}`;
}

async function clickIfVisible(page, selectors, options = {}) {
  for (const selector of selectors) {
    const locator = page.locator(selector).first();
    try {
      if (await locator.isVisible({ timeout: options.timeout || 800 })) {
        await locator.click({ force: true, timeout: options.timeout || 3000 });
        return selector;
      }
    } catch {
      continue;
    }
  }
  return "";
}

async function dismissTransientPrompts(page) {
  const clicked = [];
  for (const _ of [0, 1, 2]) {
    const selector = await clickIfVisible(page, [
      "button:has-text('我知道了')",
      ".risk-button:has-text('我知道了')",
      "span:has-text('我知道了')",
      "button:has-text('知道了')",
    ]);
    if (!selector) {
      break;
    }
    clicked.push(selector);
    await page.waitForTimeout(600);
  }
  return clicked;
}

function resolveSmsCodeFile(args) {
  const raw = String(args["sms-code-file"] || process.env.JUEJIN_SMS_CODE_FILE || DEFAULT_SMS_CODE_FILE).trim();
  return path.isAbsolute(raw) ? raw : path.resolve(AIMAGICIAN_ROOT, raw);
}

async function resetSmsCodeFile(smsCodeFile) {
  if (!smsCodeFile) {
    return false;
  }
  await fs.mkdir(path.dirname(smsCodeFile), { recursive: true });
  await fs.writeFile(smsCodeFile, "", "utf8");
  return true;
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

async function ensureAgreementChecked(page) {
  const checkbox = page.locator("input.checkbox-input[type='checkbox']").first();
  try {
    if (!(await checkbox.count())) {
      return false;
    }
    if (!(await checkbox.isChecked())) {
      await checkbox.check({ force: true });
      await page.waitForTimeout(300);
    }
    return await checkbox.isChecked();
  } catch {
    try {
      await checkbox.click({ force: true, timeout: 2000 });
      await page.waitForTimeout(300);
      return await checkbox.isChecked();
    } catch {
      return false;
    }
  }
}

async function switchToPasswordLogin(page) {
  const clicked = await clickIfVisible(page, [
    "span:has-text('密码登录')",
    "text=密码登录",
  ]);
  if (clicked) {
    await page.waitForTimeout(1200);
  }
  return Boolean(clicked);
}

async function switchToSmsLogin(page) {
  const clicked = await clickIfVisible(page, [
    "span:has-text('验证码登录 / 注册')",
    "text=验证码登录 / 注册",
    "span:has-text('验证码登录')",
    "text=验证码登录",
  ]);
  if (clicked) {
    await page.waitForTimeout(1200);
  }
  return Boolean(clicked);
}

async function attemptSmsLogin(page, args, timeoutMs) {
  if (!JUEJIN_PHONE) {
    return {
      attempted: false,
      submitted: false,
      reason: "phone_number_missing",
      phone_masked: "",
      agreement_checked: false,
      sms_code_file: resolveSmsCodeFile(args),
      sms_code_applied: false,
      send_code_selector: "",
      send_code_text_after_click: "",
      send_code_disabled_before_click: false,
      send_code_disabled_after_click: false,
      code_selector: "",
      risk_marker_after_click: "",
      body_excerpt_after_click: "",
    };
  }

  await dismissTransientPrompts(page);
  const switchedToSms = await switchToSmsLogin(page);
  await dismissTransientPrompts(page);

  const phoneMatch = await firstVisibleLocator(page, [
    "input[placeholder='请输入手机号']",
    "input[placeholder*='手机号']",
    "input[type='tel']",
  ]);
  if (!phoneMatch) {
    return {
      attempted: true,
      submitted: false,
      reason: "sms_phone_input_not_found",
      phone_masked: maskUsername(JUEJIN_PHONE),
      agreement_checked: false,
      sms_code_file: resolveSmsCodeFile(args),
      sms_code_applied: false,
      send_code_selector: "",
      send_code_text_after_click: "",
      send_code_disabled_before_click: false,
      send_code_disabled_after_click: false,
      code_selector: "",
      risk_marker_after_click: "",
      body_excerpt_after_click: "",
      switched_to_sms: switchedToSms,
    };
  }
  await phoneMatch.locator.fill("");
  await phoneMatch.locator.fill(JUEJIN_PHONE);
  const agreementChecked = await ensureAgreementChecked(page);
  const sendCodeStateBeforeClick = await readFirstVisibleControlState(page, [
    "button:has-text('获取验证码')",
    "[role='button']:has-text('获取验证码')",
    "text=获取验证码",
    "div:has-text('获取验证码')",
    "span:has-text('获取验证码')",
  ]);

  const sendCodeSelector = await clickIfVisible(page, [
    "button:has-text('获取验证码')",
    "[role='button']:has-text('获取验证码')",
    "text=获取验证码",
    "div:has-text('获取验证码')",
    "span:has-text('获取验证码')",
  ], { timeout: 3000 });
  if (!sendCodeSelector) {
    return {
      attempted: true,
      submitted: false,
      reason: "sms_send_code_control_not_found",
      phone_masked: maskUsername(JUEJIN_PHONE),
      agreement_checked: agreementChecked,
      sms_code_file: resolveSmsCodeFile(args),
      sms_code_applied: false,
      send_code_selector: "",
      send_code_text_after_click: "",
      send_code_disabled_before_click: sendCodeStateBeforeClick.disabled || sendCodeStateBeforeClick.ariaDisabled === "true",
      send_code_disabled_after_click: false,
      code_selector: "",
      risk_marker_after_click: "",
      body_excerpt_after_click: "",
      switched_to_sms: switchedToSms,
    };
  }

  await page.waitForTimeout(1200);
  const signals = await collectPageSignals(page);
  const sendCodeStateAfterClick = await readFirstVisibleControlState(page, [
    "button:has-text('重新发送')",
    "[role='button']:has-text('重新发送')",
    "button:has-text('秒后重发')",
    "[role='button']:has-text('秒后重发')",
    "button:has-text('获取验证码')",
    "[role='button']:has-text('获取验证码')",
    "text=重新发送",
  ]);
  if (signals.manualClearanceRequired) {
    return {
      attempted: true,
      submitted: false,
      reason: "manual_clearance_required",
      phone_masked: maskUsername(JUEJIN_PHONE),
      agreement_checked: agreementChecked,
      sms_code_file: resolveSmsCodeFile(args),
      sms_code_applied: false,
      send_code_selector: sendCodeSelector,
      send_code_text_after_click: sendCodeStateAfterClick.text,
      send_code_disabled_before_click: sendCodeStateBeforeClick.disabled || sendCodeStateBeforeClick.ariaDisabled === "true",
      send_code_disabled_after_click: sendCodeStateAfterClick.disabled || sendCodeStateAfterClick.ariaDisabled === "true",
      code_selector: "",
      risk_marker_after_click: trimText(signals.manualClearanceMarker || ""),
      body_excerpt_after_click: signals.bodyExcerpt,
      switched_to_sms: switchedToSms,
    };
  }

  const smsCodeFile = resolveSmsCodeFile(args);
  await resetSmsCodeFile(smsCodeFile);
  await checkpointProgress(args, "bootstrap_wait_sms_code", {
    phone_number: maskUsername(JUEJIN_PHONE),
    sms_code_file: smsCodeFile,
    send_code_selector: sendCodeSelector,
    send_code_text_after_click: sendCodeStateAfterClick.text,
    send_code_disabled_before_click: sendCodeStateBeforeClick.disabled || sendCodeStateBeforeClick.ariaDisabled === "true",
    send_code_disabled_after_click: sendCodeStateAfterClick.disabled || sendCodeStateAfterClick.ariaDisabled === "true",
    agreement_checked: agreementChecked,
    risk_marker_after_click: trimText(signals.manualClearanceMarker || ""),
    body_excerpt_after_click: signals.bodyExcerpt,
    switched_to_sms: switchedToSms,
  });
  const smsCode = await waitForSmsCodeFile(smsCodeFile, timeoutMs);
  if (!smsCode) {
    return {
      attempted: true,
      submitted: false,
      reason: "sms_code_required",
      phone_masked: maskUsername(JUEJIN_PHONE),
      agreement_checked: agreementChecked,
      sms_code_file: smsCodeFile,
      sms_code_applied: false,
      send_code_selector: sendCodeSelector,
      send_code_text_after_click: sendCodeStateAfterClick.text,
      send_code_disabled_before_click: sendCodeStateBeforeClick.disabled || sendCodeStateBeforeClick.ariaDisabled === "true",
      send_code_disabled_after_click: sendCodeStateAfterClick.disabled || sendCodeStateAfterClick.ariaDisabled === "true",
      code_selector: "",
      risk_marker_after_click: trimText(signals.manualClearanceMarker || ""),
      body_excerpt_after_click: signals.bodyExcerpt,
      switched_to_sms: switchedToSms,
    };
  }

  const codeMatch = await firstVisibleLocator(page, [
    "input[placeholder='请输入验证码']",
    "input[placeholder*='验证码']",
    "input[maxlength='6']",
  ]);
  if (!codeMatch) {
    return {
      attempted: true,
      submitted: false,
      reason: "sms_code_input_not_found",
      phone_masked: maskUsername(JUEJIN_PHONE),
      agreement_checked: agreementChecked,
      sms_code_file: smsCodeFile,
      sms_code_applied: false,
      send_code_selector: sendCodeSelector,
      send_code_text_after_click: sendCodeStateAfterClick.text,
      send_code_disabled_before_click: sendCodeStateBeforeClick.disabled || sendCodeStateBeforeClick.ariaDisabled === "true",
      send_code_disabled_after_click: sendCodeStateAfterClick.disabled || sendCodeStateAfterClick.ariaDisabled === "true",
      code_selector: "",
      risk_marker_after_click: trimText(signals.manualClearanceMarker || ""),
      body_excerpt_after_click: signals.bodyExcerpt,
      switched_to_sms: switchedToSms,
    };
  }
  await codeMatch.locator.fill("");
  await codeMatch.locator.fill(smsCode);
  const loginButton = page.locator("button.btn-login").first();
  await loginButton.click({ timeout: 5000 });
  await page.waitForTimeout(3000);
  return {
    attempted: true,
    submitted: true,
    reason: "",
    phone_masked: maskUsername(JUEJIN_PHONE),
    agreement_checked: agreementChecked,
    sms_code_file: smsCodeFile,
    sms_code_applied: true,
    send_code_selector: sendCodeSelector,
    send_code_text_after_click: sendCodeStateAfterClick.text,
    send_code_disabled_before_click: sendCodeStateBeforeClick.disabled || sendCodeStateBeforeClick.ariaDisabled === "true",
    send_code_disabled_after_click: sendCodeStateAfterClick.disabled || sendCodeStateAfterClick.ariaDisabled === "true",
    code_selector: codeMatch.selector,
    risk_marker_after_click: trimText(signals.manualClearanceMarker || ""),
    body_excerpt_after_click: signals.bodyExcerpt,
    switched_to_sms: switchedToSms,
  };
}

async function attemptPasswordLogin(page, args) {
  if (!JUEJIN_USERNAME || !JUEJIN_PASSWORD) {
    return {
      attempted: false,
      submitted: false,
      reason: "credentials_missing",
      username_masked: "",
      agreement_checked: false,
      dismissed_prompts: [],
    };
  }

  await dismissTransientPrompts(page);
  const switchedToPassword = await switchToPasswordLogin(page);
  await dismissTransientPrompts(page);

  const accountInput = page.locator("input[name='loginPhoneOrEmail']").first();
  const passwordInput = page.locator("input[name='loginPassword']").first();
  await accountInput.waitFor({ state: "visible", timeout: 5000 });
  await accountInput.fill("");
  await accountInput.fill(JUEJIN_USERNAME);
  await passwordInput.waitFor({ state: "visible", timeout: 5000 });
  await passwordInput.fill("");
  await passwordInput.fill(JUEJIN_PASSWORD);
  const agreementChecked = await ensureAgreementChecked(page);

  await checkpointProgress(args, "submitting_password_login", {
    username_masked: maskUsername(JUEJIN_USERNAME),
    switched_to_password: switchedToPassword,
    agreement_checked: agreementChecked,
  });

  const loginButton = page.locator("button.btn-login").first();
  await loginButton.click({ timeout: 5000 });
  await page.waitForTimeout(3000);
  const dismissedPrompts = await dismissTransientPrompts(page);
  return {
    attempted: true,
    submitted: true,
    reason: "",
    username_masked: maskUsername(JUEJIN_USERNAME),
    switched_to_password: switchedToPassword,
    agreement_checked: agreementChecked,
    dismissed_prompts: dismissedPrompts,
  };
}

async function saveSessionState(context, stateFile) {
  if (!stateFile) {
    return false;
  }
  await fs.mkdir(path.dirname(stateFile), { recursive: true });
  await context.storageState({ path: stateFile });
  return true;
}

async function saveSessionStateSafely(context, stateFile) {
  let stateSaved = false;
  let stateSaveError = "";
  try {
    stateSaved = await saveSessionState(context, stateFile);
  } catch (error) {
    stateSaveError = String(error?.message || error);
  }
  return { stateSaved, stateSaveError };
}

async function openEditor(page, timeoutMs) {
  await page.goto(DEFAULT_EDITOR_URL, {
    waitUntil: "domcontentloaded",
    timeout: timeoutMs,
  });
  await page.waitForTimeout(3000);
}

function normalizeMultilineText(value) {
  return String(value || "").replace(/\r\n/g, "\n").trim();
}

async function ensureEditorSurface(page, timeoutMs) {
  let detected = await detectSurface(page);
  if (detected.surface === "editor") {
    return detected;
  }
  await openEditor(page, timeoutMs);
  detected = await detectSurface(page);
  if (detected.surface !== "editor") {
    throw new Error(`expected_editor_surface:${detected.surface || "unknown"}`);
  }
  return detected;
}

async function fillEditorTitle(page, title) {
  const locator = page.locator([
    "input.title-input",
    "input[placeholder*='输入文章标题']",
    "textarea[placeholder*='输入文章标题']",
    ".editor-title-input",
  ].join(",")).first();
  await locator.waitFor({ state: "visible", timeout: 8000 });
  await locator.click({ clickCount: 3 });
  await locator.fill(title);
  await page.waitForTimeout(500);
  return true;
}

async function findEditorMarkdownTextarea(page) {
  const textareas = page.locator("textarea");
  const count = await textareas.count();
  for (let index = count - 1; index >= 0; index -= 1) {
    const locator = textareas.nth(index);
    const visible = await locator.isVisible().catch(() => false);
    if (!visible) {
      continue;
    }
    const placeholder = String(await locator.getAttribute("placeholder").catch(() => "") || "");
    const className = String(await locator.getAttribute("class").catch(() => "") || "");
    if (className.includes("byte-input__textarea")) {
      continue;
    }
    if (placeholder.includes("摘要") || placeholder.includes("概述")) {
      continue;
    }
    return locator;
  }
  return null;
}

async function fillEditorMarkdown(page, markdown) {
  const locator = await findEditorMarkdownTextarea(page);
  if (!locator) {
    throw new Error("editor_markdown_textarea_not_found");
  }
  await locator.fill(markdown);
  await page.waitForTimeout(1000);
  return true;
}

async function clickExactButton(page, label, timeout = 8000) {
  const button = page.getByRole("button", { name: new RegExp(`^${label}$`) }).first();
  await button.waitFor({ state: "visible", timeout });
  await button.click({ timeout });
  return label;
}

async function closePublishDropdowns(page) {
  await page.keyboard.press("Escape").catch(() => null);
  await page.waitForTimeout(300);
  const summary = page.locator("textarea.byte-input__textarea").first();
  if (await summary.isVisible().catch(() => false)) {
    await summary.click({ force: true, timeout: 2000 }).catch(() => null);
    await page.keyboard.press("Escape").catch(() => null);
    await page.waitForTimeout(300);
  }
}

async function clickConfirmPublishButton(page, timeout = 10000) {
  const deadline = Date.now() + timeout;
  let lastError = "";
  while (Date.now() < deadline) {
    await closePublishDropdowns(page);
    const candidates = [
      page.getByRole("button", { name: /^确定并发布$/ }).first(),
      page.locator("button:has-text('确定并发布')").last(),
      page.getByText("确定并发布", { exact: true }).last(),
    ];
    for (const button of candidates) {
      const visible = await button.isVisible().catch(() => false);
      if (!visible) {
        continue;
      }
      try {
        await button.click({ force: true, timeout: 3000 });
        await page.waitForTimeout(1800);
        const stillVisible = await page
          .locator("button:has-text('确定并发布')")
          .first()
          .isVisible()
          .catch(() => false);
        const signals = await collectPageSignals(page).catch(() => ({}));
        if (
          !stillVisible
          || signals.validationMessage
          || signals.publishSuccessSeen
          || signals.reviewStatus
          || signals.manualClearanceRequired
        ) {
          return "确定并发布";
        }
        const domClicked = await page.evaluate(() => {
          const buttons = Array.from(document.querySelectorAll("button"));
          const candidates = buttons.filter((button) => String(button.textContent || "").trim() === "确定并发布");
          const target = candidates[candidates.length - 1];
          if (!target) {
            return false;
          }
          target.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
          target.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true }));
          target.click();
          return true;
        }).catch(() => false);
        if (domClicked) {
          await page.waitForTimeout(1800);
          const stillVisibleAfterDomClick = await page
            .locator("button:has-text('确定并发布')")
            .first()
            .isVisible()
            .catch(() => false);
          const signalsAfterDomClick = await collectPageSignals(page).catch(() => ({}));
          if (
            !stillVisibleAfterDomClick
            || signalsAfterDomClick.validationMessage
            || signalsAfterDomClick.publishSuccessSeen
            || signalsAfterDomClick.reviewStatus
            || signalsAfterDomClick.manualClearanceRequired
          ) {
            return "确定并发布";
          }
        }
        await page.keyboard.press("Enter").catch(() => null);
        await page.waitForTimeout(1200);
        const stillVisibleAfterEnter = await page
          .locator("button:has-text('确定并发布')")
          .first()
          .isVisible()
          .catch(() => false);
        if (!stillVisibleAfterEnter) {
          return "确定并发布";
        }
        lastError = "confirm_button_still_visible_after_click";
      } catch (error) {
        lastError = String(error?.message || error || "");
      }
    }
    await page.waitForTimeout(600);
  }
  throw new Error(`confirm_publish_button_not_clicked:${lastError}`);
}

async function openPublishDialog(page) {
  await clickExactButton(page, "发布");
  const dialogReady = await firstVisibleLocator(page, [
    "textarea.byte-input__textarea",
    "button:has-text('确定并发布')",
    "button:has-text('发布文章')",
    "div:has-text('发布文章')",
  ]);
  if (!dialogReady) {
    throw new Error("publish_dialog_not_opened");
  }
  await page.waitForTimeout(800);
  return true;
}

async function fillPublishSummary(page, summary) {
  const locator = page.locator("textarea.byte-input__textarea").first();
  await locator.waitFor({ state: "visible", timeout: 8000 });
  await locator.fill("");
  await locator.fill(summary.slice(0, 100));
  await page.waitForTimeout(300);
  return true;
}

async function chooseCategory(page, categoryHint) {
  const label = String(categoryHint || "").trim();
  if (!label) {
    return { applied: false, label: "" };
  }
  const target = page.getByText(label, { exact: true }).first();
  try {
    await target.waitFor({ state: "visible", timeout: 5000 });
    await target.click({ timeout: 3000 });
    await page.waitForTimeout(500);
    return { applied: true, label };
  } catch {
    return { applied: false, label };
  }
}

function buildTagSearchTerms(tags, payload) {
  const candidates = [];
  const seen = new Set();
  const add = (value) => {
    const normalized = String(value || "").trim();
    if (!normalized || seen.has(normalized)) {
      return;
    }
    seen.add(normalized);
    candidates.push(normalized);
  };

  const baseTags = Array.isArray(tags)
    ? tags.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  for (const tag of baseTags) {
    add(tag);
  }

  const combined = [
    payload?.title || "",
    payload?.summary || payload?.brief_content || "",
    payload?.category_hint || "",
    payload?.category || "",
    ...baseTags,
  ].join(" ");

  if (combined.includes("开源")) {
    add("开源");
  }
  if (combined.includes("硬件") || combined.includes("固件") || combined.includes("路由器")) {
    add("物联网");
  }
  if (combined.includes("人工智能") || combined.includes("AI") || combined.includes("智能体")) {
    add("人工智能");
    add("AI编程");
  }
  if (combined.includes("前端") || combined.includes("React") || combined.includes("Vue")) {
    add("前端");
  }
  if (combined.includes("后端") || combined.includes("Python") || combined.includes("Node")) {
    add("后端");
  }
  if (combined.includes("编程") || combined.includes("代码")) {
    add("编程语言");
  }
  add("开源");
  add("人工智能");
  add("后端");
  add("前端");
  return candidates.slice(0, 12);
}

async function selectTagOption(page, tagContainer, input, searchTerm, selected) {
  await tagContainer.locator(".byte-select__wrap").first().click({ force: true, timeout: 3000 });
  await input.fill("");
  await input.fill(searchTerm);
  await page.waitForTimeout(900);

  const options = page.locator(".tag-select-add-margin .byte-select-option");
  const count = await options.count();
  let best = null;
  const needle = normalizeComparableText(searchTerm);

  for (let index = 0; index < count; index += 1) {
    const option = options.nth(index);
    const visible = await option.isVisible().catch(() => false);
    if (!visible) {
      continue;
    }
    const optionText = String(await option.innerText().catch(() => "") || "").trim();
    if (!optionText || selected.has(optionText)) {
      continue;
    }
    const normalized = normalizeComparableText(optionText);
    const score = normalized === needle
      ? 3
      : (normalized.includes(needle) || needle.includes(normalized) ? 2 : 1);
    if (!best || score > best.score) {
      best = { option, optionText, score };
    }
  }

  if (!best) {
    return { applied: false, searchTerm, optionText: "" };
  }

  await best.option.click({ timeout: 3000 });
  await page.waitForTimeout(600);
  const actualTags = await readAppliedTagChips(tagContainer);
  const confirmed = actualTags.some((tag) => normalizeComparableText(tag) === normalizeComparableText(best.optionText));
  return {
    applied: confirmed,
    searchTerm,
    optionText: confirmed ? best.optionText : "",
  };
}

async function readAppliedTagChips(tagContainer) {
  const rawTags = await tagContainer.locator(".byte-select__tag").evaluateAll((nodes) => nodes.map((node) => {
    const text = String(node.textContent || "").replace(/\s+/g, " ").replace(/[×xX]$/g, "").trim();
    return text;
  })).catch(() => []);
  const tags = [];
  const seen = new Set();
  for (const raw of rawTags) {
    const tag = String(raw || "").replace(/你还能添加\s*\d+\s*个标签/g, "").trim();
    if (!tag || seen.has(tag)) {
      continue;
    }
    seen.add(tag);
    tags.push(tag);
  }
  return tags;
}

async function applyTags(page, tags, payload) {
  const tagContainer = page.locator(".form-item").filter({ hasText: "添加标签" }).first();
  const input = tagContainer.locator("input.byte-select__input").first();
  await input.waitFor({ state: "visible", timeout: 8000 });

  let applied = await readAppliedTagChips(tagContainer);
  const selected = new Set(applied);
  const searchTerms = buildTagSearchTerms(tags, payload);
  for (const searchTerm of searchTerms) {
    if (applied.length >= 3) {
      break;
    }
    try {
      const result = await selectTagOption(page, tagContainer, input, searchTerm, selected);
      if (!result.applied || !result.optionText) {
        continue;
      }
      applied = await readAppliedTagChips(tagContainer);
      for (const tag of applied) {
        selected.add(tag);
      }
    } catch {
      continue;
    }
  }
  await closePublishDropdowns(page);
  return applied.slice(0, 3);
}

async function resolveBannerUploadFile(payload) {
  const bannerAsset = payload?.banner_asset && typeof payload.banner_asset === "object"
    ? payload.banner_asset
    : {};
  const sourcePath = String(bannerAsset.source_path || "").trim();
  if (sourcePath) {
    await fs.access(sourcePath);
    return { filePath: sourcePath, temporary: false };
  }

  const directUrl = String(
    bannerAsset.direct_url || payload?.cover_image_url || payload?.banner_image_url || ""
  ).trim();
  if (!directUrl) {
    return { filePath: "", temporary: false };
  }

  const response = await fetch(directUrl);
  if (!response.ok) {
    throw new Error(`banner_download_failed:${response.status}`);
  }
  const bytes = Buffer.from(await response.arrayBuffer());
  const extension = path.extname(new URL(directUrl).pathname) || ".png";
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "oc-juejin-banner-"));
  const filePath = path.join(tempDir, `banner${extension}`);
  await fs.writeFile(filePath, bytes);
  return { filePath, temporary: true };
}

async function uploadBanner(page, payload) {
  const upload = await resolveBannerUploadFile(payload);
  if (!upload.filePath) {
    return {
      uploaded: false,
      reason: "missing_banner_asset",
      filePath: "",
    };
  }

  const input = page.locator("input[type='file']").first();
  await input.setInputFiles(upload.filePath);
  await page.waitForTimeout(4000);
  const bodyText = await page.locator("body").innerText().catch(() => "");
  const uploadButtonVisible = bodyText.includes("上传封面");
  const reuploadVisible = Boolean(await firstVisibleLocator(page, [
    "text=重新上传",
    "text=更换封面",
    "text=裁剪封面",
    "text=封面设置",
  ]));
  if (upload.temporary) {
    await fs.unlink(upload.filePath).catch(() => null);
    await fs.rmdir(path.dirname(upload.filePath)).catch(() => null);
  }
  const uploaded = reuploadVisible || !uploadButtonVisible;
  return {
    uploaded,
    reason: uploaded ? "" : "upload_button_still_visible",
    filePath: upload.filePath,
  };
}

async function extractPublishedArticleLink(page) {
  if (!page || page.isClosed()) {
    return null;
  }
  const currentUrl = page.url();
  if (isResolvedArticleUrl(currentUrl)) {
    return {
      href: currentUrl,
      text: await page.title().catch(() => ""),
      source: "current_page_url",
    };
  }
  return page.evaluate(() => {
    const isResolvedArticleUrl = (url) => /^https:\/\/juejin\.cn\/(?:post|spost)\/[A-Za-z0-9]+(?:[/?#].*)?$/i.test(String(url || "").trim());
    const anchors = Array.from(document.querySelectorAll("a[href*='/post/'], a[href*='/spost/']"));
    if (!anchors.length) {
      return null;
    }
    const preferred = anchors.find((anchor) => /查看文章|查看全文|阅读全文|去看看/.test(anchor.textContent || "") && isResolvedArticleUrl(anchor.href || ""))
      || anchors.find((anchor) => isResolvedArticleUrl(anchor.href || ""));
    if (!preferred) {
      return null;
    }
    return {
      href: preferred.href || "",
      text: String(preferred.textContent || "").trim(),
      source: "publish_surface_link",
    };
  }).catch(() => null);
}

function normalizeComparableText(value) {
  return String(value || "")
    .replace(/\s+/g, "")
    .replace(/[“”"'`·•]/g, "")
    .trim();
}

function decodeSlardarUserId(rawValue) {
  const raw = String(rawValue || "").trim();
  if (!raw) {
    return "";
  }
  const candidates = [raw];
  try {
    candidates.unshift(decodeURIComponent(raw));
  } catch {}
  for (const candidate of candidates) {
    try {
      const decoded = Buffer.from(candidate, "base64").toString("utf8");
      const parsed = JSON.parse(decoded);
      const userId = String(parsed?.userId || "").trim();
      if (/^\d+$/.test(userId)) {
        return userId;
      }
    } catch {}
  }
  return "";
}

async function resolveCurrentUserIds(page) {
  return page.evaluate((decodeSource) => {
    const parseSlardar = (rawValue) => {
      const raw = String(rawValue || "").trim();
      if (!raw) {
        return "";
      }
      const candidates = [raw];
      try {
        candidates.unshift(decodeURIComponent(raw));
      } catch {}
      for (const candidate of candidates) {
        try {
          const decoded = atob(candidate);
          const parsed = JSON.parse(decoded);
          const userId = String(parsed?.userId || "").trim();
          if (/^\d+$/.test(userId)) {
            return userId;
          }
        } catch {}
      }
      return "";
    };

    const ids = [];
    const push = (value) => {
      const text = String(value || "").trim();
      if (/^\d+$/.test(text) && !ids.includes(text)) {
        ids.push(text);
      }
    };

    push(localStorage.getItem("user_first_visit_dispatch_coupon") || "");
    push(parseSlardar(localStorage.getItem("SLARDAR2608") || ""));
    push(parseSlardar(localStorage.getItem("SLARDARpassport_account_api") || ""));

    const userAnchors = Array.from(document.querySelectorAll("a[href*='/user/']"));
    for (const anchor of userAnchors) {
      const href = anchor.getAttribute("href") || "";
      const match = href.match(/\/user\/(\d+)/);
      if (match) {
        push(match[1]);
      }
    }
    return ids;
  }, decodeSlardarUserId.toString()).catch(() => []);
}

async function resolvePublishedArticleUrl(runtime, referencePage, articleTitle, timeoutMs) {
  const directLink = await extractPublishedArticleLink(referencePage);
  const normalizedTitle = normalizeComparableText(articleTitle);
  if (directLink?.href && isResolvedArticleUrl(directLink.href)) {
    const directTitle = normalizeComparableText(directLink.text || "");
    const directTitleMatches = normalizedTitle
      && directTitle
      && (
        directTitle === normalizedTitle
        || directTitle.includes(normalizedTitle)
        || normalizedTitle.includes(directTitle)
      );
    if (directTitleMatches) {
      return {
        found: true,
        url: directLink.href,
        title: directLink.text || articleTitle,
        reviewStatus: "",
        userId: "",
        source: directLink.source || "publish_surface_link",
      };
    }
  }

  if (!normalizedTitle) {
    return {
      found: false,
      url: "",
      title: "",
      reviewStatus: "",
      userId: "",
      source: "missing_title",
    };
  }
  const userIds = await resolveCurrentUserIds(referencePage);
  if (!Array.isArray(userIds) || !userIds.length) {
    return {
      found: false,
      url: "",
      title: "",
      reviewStatus: "",
      userId: "",
      source: "missing_user_id",
    };
  }

  const deadline = Date.now() + Math.max(timeoutMs, 20000);
  while (Date.now() < deadline) {
    for (const userId of userIds) {
      const lookupPage = await runtime.context.newPage();
      try {
        const postsUrl = `https://juejin.cn/user/${userId}/posts`;
        await lookupPage.goto(postsUrl, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => null);
        await new Promise((resolve) => setTimeout(resolve, 1800));
        const match = await lookupPage.evaluate((expectedTitle) => {
          const normalize = (value) => String(value || "")
            .replace(/\s+/g, "")
            .replace(/[“”"'`·•]/g, "")
            .trim();
          const cards = Array.from(document.querySelectorAll("a[href*='/post/'], a[href*='/spost/']"));
          const titleNeedle = normalize(expectedTitle);
          for (const anchor of cards) {
            const text = String(anchor.textContent || "").trim();
            const href = anchor.href || "";
            if (!href) {
              continue;
            }
            const normalizedText = normalize(text);
            if (!normalizedText) {
              continue;
            }
            if (normalizedText === titleNeedle || normalizedText.includes(titleNeedle) || titleNeedle.includes(normalizedText)) {
              const articleCard = anchor.closest(".entry-list .item, .entry-list .entry-list-item, .entry-list-item, .article-item, li, .item");
              const cardText = String(articleCard?.textContent || "").trim();
              const reviewStatus = cardText.includes("审核中")
                ? "审核中"
                : (cardText.includes("已发布") ? "已发布" : "");
              return {
                href,
                text,
                reviewStatus,
              };
            }
          }
          return null;
        }, articleTitle).catch(() => null);
        if (match?.href) {
          return {
            found: true,
            url: match.href,
            title: match.text || articleTitle,
            reviewStatus: match.reviewStatus || "",
            userId,
            source: "user_posts_exact_match",
          };
        }
      } finally {
        await lookupPage.close().catch(() => null);
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }

  return {
    found: false,
    url: "",
    title: "",
    reviewStatus: "",
    userId: userIds[0] || "",
    source: "user_posts_lookup_failed",
  };
}

function isResolvedArticleUrl(url) {
  return /^https:\/\/juejin\.cn\/(?:post|spost)\/[A-Za-z0-9]+(?:[/?#].*)?$/i.test(String(url || "").trim());
}

function isGenericPublishedSurface(url) {
  const normalized = String(url || "").trim();
  return normalized === "https://juejin.cn/"
    || normalized === "https://juejin.cn/published"
    || normalized.startsWith("https://juejin.cn/published?");
}

async function waitForPublishedArticle(runtime, page, timeoutMs, articleTitle = "") {
  const deadline = Date.now() + Math.max(timeoutMs, 45000);
  let genericSuccessSeen = false;
  let lastSignals = {
    bodyExcerpt: "",
    manualClearanceRequired: false,
    manualClearanceMarker: "",
    reviewStatus: "",
    publishSuccessSeen: false,
    validationMessage: "",
  };
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    const pages = runtime.context.pages();
    for (const candidate of [...pages].reverse()) {
      const url = candidate.url();
      if (isResolvedArticleUrl(url)) {
        return {
          confirmed: true,
          url,
          title: await candidate.title().catch(() => ""),
          pageCount: pages.length,
          reviewStatus: "",
          source: "resolved_page_url",
        };
      }
      const linked = await extractPublishedArticleLink(candidate);
      if (linked?.href && isResolvedArticleUrl(linked.href)) {
        return {
          confirmed: true,
          url: linked.href,
          title: linked.text || await candidate.title().catch(() => ""),
          pageCount: pages.length,
          reviewStatus: "",
          source: linked.source || "publish_surface_link",
        };
      }
      if (isGenericPublishedSurface(url)) {
        genericSuccessSeen = true;
      }
    }
    const currentUrl = page.isClosed() ? "" : page.url();
    if (isResolvedArticleUrl(currentUrl)) {
      return {
        confirmed: true,
        url: currentUrl,
        title: await page.title().catch(() => ""),
        pageCount: pages.length,
        reviewStatus: "",
        source: "resolved_current_url",
      };
    }
    const currentLink = await extractPublishedArticleLink(page);
    if (currentLink?.href && isResolvedArticleUrl(currentLink.href)) {
      return {
        confirmed: true,
        url: currentLink.href,
        title: currentLink.text || await page.title().catch(() => ""),
        pageCount: pages.length,
        reviewStatus: "",
        source: currentLink.source || "publish_surface_link",
      };
    }
    if (isGenericPublishedSurface(currentUrl)) {
      genericSuccessSeen = true;
    }
    if (!page.isClosed()) {
      lastSignals = await collectPageSignals(page);
      if (lastSignals.validationMessage) {
        return {
          confirmed: false,
          url: currentUrl,
          title: await page.title().catch(() => ""),
          pageCount: pages.length,
          validationMessage: lastSignals.validationMessage,
          reviewStatus: lastSignals.reviewStatus,
          manualClearanceRequired: lastSignals.manualClearanceRequired,
          finalBlocker: `publish_validation_failed:${lastSignals.validationMessage}`,
          source: "validation_message",
          bodyExcerpt: lastSignals.bodyExcerpt,
        };
      }
      if (lastSignals.manualClearanceRequired) {
        return {
          confirmed: false,
          url: currentUrl,
          title: await page.title().catch(() => ""),
          pageCount: pages.length,
          validationMessage: "",
          reviewStatus: lastSignals.reviewStatus,
          manualClearanceRequired: true,
          finalBlocker: "platform_clearance_required_after_publish_click",
          source: "manual_clearance_required",
          bodyExcerpt: lastSignals.bodyExcerpt,
        };
      }
      if (lastSignals.publishSuccessSeen || lastSignals.reviewStatus) {
        genericSuccessSeen = true;
      }
    }
    if (genericSuccessSeen || articleTitle) {
      const lookup = await resolvePublishedArticleUrl(runtime, page, articleTitle, 12000);
      if (lookup.found && lookup.url) {
        return {
          confirmed: true,
          url: lookup.url,
          title: lookup.title || articleTitle,
          pageCount: pages.length,
          reviewStatus: lookup.reviewStatus || "",
          source: lookup.source,
        };
      }
    }
  }
  const finalUrl = page.isClosed() ? "" : page.url();
  const finalTitle = page.isClosed() ? "" : await page.title().catch(() => "");
  let finalBlocker = "timeout_waiting_for_publish_result";
  if (lastSignals.manualClearanceRequired) {
    finalBlocker = "platform_clearance_required_after_publish_click";
  } else if (lastSignals.reviewStatus === "审核中") {
    finalBlocker = "published_review_pending_public_url_unavailable";
  } else if (genericSuccessSeen) {
    finalBlocker = "publish_success_seen_but_public_url_not_resolved";
  }
  return {
    confirmed: false,
    url: finalUrl,
    title: finalTitle,
    pageCount: runtime.context.pages().length,
    validationMessage: lastSignals.validationMessage || "",
    reviewStatus: lastSignals.reviewStatus || "",
    manualClearanceRequired: lastSignals.manualClearanceRequired,
    finalBlocker,
    source: genericSuccessSeen ? "generic_success_without_article_url" : "timeout",
    bodyExcerpt: lastSignals.bodyExcerpt,
  };
}

async function prepareArticle(runtime, args, stateFile, timeoutMs, payload, submit) {
  const { context, page, profileDir, authMaterialSource } = runtime;
  if (!payload || typeof payload !== "object") {
    throw new Error("missing_publish_payload");
  }

  const title = String(payload.title || "").trim();
  const markdown = normalizeMultilineText(payload.markdown || "");
  if (!title || !markdown) {
    throw new Error("payload_missing_title_or_markdown");
  }

  const cookieResult = await injectSessionCookies(context);
  await checkpointProgress(args, "prepare_article_navigate", {
    editor_url: DEFAULT_EDITOR_URL,
    profile_dir: profileDir,
    session_cookie_applied: cookieResult.applied,
  });
  const detected = await ensureEditorSurface(page, timeoutMs);
  await checkpointProgress(args, "prepare_article_fill_editor", {
    editor_url: detected.url,
    title,
  });

  await fillEditorTitle(page, title);
  await fillEditorMarkdown(page, markdown);
  await page.waitForTimeout(1200);

  await checkpointProgress(args, "prepare_article_open_publish_dialog", {
    title,
  });
  await openPublishDialog(page);

  const summary = String(payload.brief_content || payload.summary || "").trim();
  if (summary) {
    await fillPublishSummary(page, summary);
  }
  const category = await chooseCategory(page, payload.category_hint || payload.category || "");
  const tagsApplied = await applyTags(page, payload.tags, payload);
  const bannerUpload = await uploadBanner(page, payload);
  const draftUrl = page.url();
  const preSubmitEvidence = await capturePageEvidence(page, args, "publish-modal-ready", {
    title,
    category_applied: category.applied,
    tags_applied: tagsApplied,
    banner_uploaded: bannerUpload.uploaded,
  });
  let publishConfirmed = false;
  let publishValidationReason = "";
  let publishedArticleUrl = "";
  let publishedPageTitle = "";
  let publishedReviewStatus = "";
  let publishResolutionSource = "";
  let manualClearanceRequired = false;
  let finalBlocker = "";
  let postSubmitEvidence = null;

  if (submit) {
    await checkpointProgress(args, "prepare_article_submit_publish", {
      title,
      category_applied: category.applied,
      tags_applied: tagsApplied,
      banner_uploaded: bannerUpload.uploaded,
    });
    let confirmError = null;
    try {
      await clickConfirmPublishButton(page, 12000);
    } catch (err) {
      confirmError = err;
    }
    if (confirmError) {
      const pageText = await page.locator("body").innerText().catch(() => "");
      if (pageText.includes("审核中") || pageText.includes("发布成功") || pageText.includes("提交成功") || pageText.includes("已发布")) {
        confirmError = null;
      }
    }
    const publishResult = await waitForPublishedArticle(runtime, page, timeoutMs, title);
    publishConfirmed = publishResult.confirmed;
    publishValidationReason = publishResult.confirmed
      ? ""
      : String(
        publishResult.finalBlocker
        || publishResult.validationMessage
        || "publish_url_not_resolved"
      );
    publishedArticleUrl = publishResult.url || "";
    publishedPageTitle = publishResult.title || "";
    publishedReviewStatus = String(publishResult.reviewStatus || "");
    publishResolutionSource = String(publishResult.source || "");
    manualClearanceRequired = Boolean(publishResult.manualClearanceRequired);
    finalBlocker = publishResult.confirmed ? "" : publishValidationReason;
    postSubmitEvidence = await capturePageEvidence(page, args, "publish-result", {
      title,
      publish_confirmed: publishConfirmed,
      final_blocker: finalBlocker,
      published_article_url: publishedArticleUrl,
      published_review_status: publishedReviewStatus,
      publish_resolution_source: publishResolutionSource,
    });
  }

  const { stateSaved, stateSaveError } = await saveSessionStateSafely(context, stateFile);
  return {
    status: submit && !publishConfirmed ? "blocked" : "ok",
    mode: "prepare-article",
    draft_url: draftUrl,
    final_url: publishedArticleUrl || page.url(),
    page_title: publishedPageTitle || await page.title().catch(() => ""),
    state_file: stateFile,
    state_file_written: stateSaved,
    state_file_write_error: stateSaveError,
    browser_profile_dir: profileDir,
    publish_modal_opened: true,
    title_filled: true,
    markdown_filled: true,
    summary_filled: Boolean(summary),
    category_applied: category.applied,
    category_label: category.label,
    tags_applied: tagsApplied,
    banner_uploaded: bannerUpload.uploaded,
    banner_upload_reason: bannerUpload.reason || "",
    publish_requested: submit,
    publish_confirmed: publishConfirmed,
    publish_validation_reason: publishValidationReason,
    published_article_url: publishedArticleUrl,
    published_review_status: publishedReviewStatus,
    publish_resolution_source: publishResolutionSource,
    session_cookie_applied: cookieResult.applied,
    session_cookie_names: cookieResult.names,
    auth_material_source: authMaterialSource,
    manual_clearance_required: manualClearanceRequired,
    final_blocker: finalBlocker,
    evidence: {
      dir: evidenceDirFromArgs(args),
      snapshots: [preSubmitEvidence, postSubmitEvidence].filter(Boolean),
    },
  };
}

async function resolvePublishedUrl(runtime, args, stateFile, timeoutMs, payload) {
  const { context, page, profileDir, authMaterialSource } = runtime;
  const title = String(payload?.title || "").trim();
  if (!title) {
    throw new Error("payload_missing_title");
  }

  const cookieResult = await injectSessionCookies(context);
  await checkpointProgress(args, "resolve_published_url_lookup", {
    title,
    profile_dir: profileDir,
    session_cookie_applied: cookieResult.applied,
  });
  await page.goto("https://juejin.cn/", { waitUntil: "domcontentloaded", timeout: timeoutMs }).catch(() => null);
  await new Promise((resolve) => setTimeout(resolve, 1200));
  const lookup = await resolvePublishedArticleUrl(runtime, page, title, timeoutMs);
  const signals = await collectPageSignals(page);
  const evidence = await capturePageEvidence(page, args, "resolve-published-url", {
    title,
    published_article_url: lookup.url || "",
    publish_resolution_source: lookup.source || "",
  });
  const { stateSaved, stateSaveError } = await saveSessionStateSafely(context, stateFile);
  const finalBlocker = lookup.found
    ? ""
    : (signals.manualClearanceRequired ? "manual_clearance_required" : (lookup.source || "published_article_not_found"));

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
    published_article_url: lookup.url || "",
    published_review_status: lookup.reviewStatus || "",
    publish_resolution_source: lookup.source || "",
    matched_user_id: lookup.userId || "",
    reason: finalBlocker,
    final_blocker: finalBlocker,
    manual_clearance_required: signals.manualClearanceRequired,
    session_cookie_applied: cookieResult.applied,
    session_cookie_names: cookieResult.names,
    auth_material_source: authMaterialSource,
    evidence,
  };
}

async function checkSession(runtime, args, stateFile, timeoutMs) {
  const { context, page, profileDir, authMaterialSource } = runtime;
  const cookieResult = await injectSessionCookies(context);
  await checkpointProgress(args, "check_session_navigate", {
    editor_url: DEFAULT_EDITOR_URL,
    session_cookie_applied: cookieResult.applied,
    profile_dir: profileDir,
  });
  await openEditor(page, timeoutMs);
  const detected = await detectSurface(page);
  const signals = await collectPageSignals(page);
  const { stateSaved, stateSaveError } = detected.surface === "editor"
    ? await saveSessionStateSafely(context, stateFile)
    : { stateSaved: false, stateSaveError: "" };
  const liveReady = detected.surface === "editor";
  const reason = liveReady
    ? ""
    : ((detected.surface === "blocked" || signals.manualClearanceRequired)
      ? "manual_clearance_required"
      : "session_invalid_or_missing");
  const evidence = await capturePageEvidence(page, args, "check-session", {
    surface: detected.surface,
    final_blocker: reason,
  });

  return {
    status: liveReady ? "ok" : "blocked",
    mode: "check-session",
    live_ready: liveReady,
    logged_in: liveReady,
    reason,
    final_url: detected.url,
    page_title: detected.title,
    matched_selector: detected.matched_selector,
    editor_url: DEFAULT_EDITOR_URL,
    state_file: stateFile,
    state_file_written: stateSaved,
    state_file_write_error: stateSaveError,
    browser_profile_dir: profileDir,
    session_cookie_applied: cookieResult.applied,
    session_cookie_names: cookieResult.names,
    auth_material_source: authMaterialSource,
    manual_clearance_required: detected.manual_clearance_required || signals.manualClearanceRequired,
    final_blocker: reason,
    body_excerpt: signals.bodyExcerpt,
    surface: detected.surface,
    evidence,
  };
}

async function bootstrapSession(runtime, args, stateFile, timeoutMs) {
  const { context, page, profileDir, authMaterialSource } = runtime;
  const loginMode = String(args["login-mode"] || process.env.JUEJIN_LOGIN_MODE || "sms").trim().toLowerCase();
  const cookieResult = await injectSessionCookies(context);
  await checkpointProgress(args, "bootstrap_navigate", {
    editor_url: DEFAULT_EDITOR_URL,
    session_cookie_applied: cookieResult.applied,
    profile_dir: profileDir,
  });
  await openEditor(page, timeoutMs);

  let detected = await detectSurface(page);
  if (detected.surface === "editor") {
    const { stateSaved, stateSaveError } = await saveSessionStateSafely(context, stateFile);
    const evidence = await capturePageEvidence(page, args, "bootstrap-session-ready", {
      reused_existing_session: true,
    });
    return {
      status: "ok",
      mode: "bootstrap-session",
      live_ready: true,
      logged_in: true,
      reused_existing_session: true,
      final_url: detected.url,
      page_title: detected.title,
      matched_selector: detected.matched_selector,
      state_file: stateFile,
      state_file_written: stateSaved,
      state_file_write_error: stateSaveError,
      browser_profile_dir: profileDir,
      session_cookie_applied: cookieResult.applied,
      session_cookie_names: cookieResult.names,
      auth_material_source: authMaterialSource,
      evidence,
    };
  }

  let credentialLogin = {
    attempted: false,
    submitted: false,
    reason: "not-needed",
    username_masked: "",
    switched_to_password: false,
    switched_to_sms: false,
    phone_masked: "",
    agreement_checked: false,
    sms_code_file: resolveSmsCodeFile(args),
    sms_code_applied: false,
    send_code_selector: "",
    code_selector: "",
    dismissed_prompts: [],
  };
  if (detected.surface === "login") {
    credentialLogin = loginMode === "sms"
      ? await attemptSmsLogin(page, args, timeoutMs)
      : await attemptPasswordLogin(page, args);
    await page.waitForTimeout(1500);
    detected = await detectSurface(page);
  }

  await checkpointProgress(args, loginMode === "sms" ? "waiting_for_sms_login" : "waiting_for_manual_login", {
    current_url: detected.url,
    page_title: detected.title,
    surface: detected.surface,
    login_mode: loginMode,
    credential_login_attempted: credentialLogin.attempted,
    credential_login_submitted: credentialLogin.submitted,
    credential_login_reason: credentialLogin.reason,
    credential_login_username: credentialLogin.username_masked,
    sms_code_file: credentialLogin.sms_code_file,
    sms_code_applied: credentialLogin.sms_code_applied,
  });

  const deadline = Date.now() + Math.max(timeoutMs, 90000);
  let lastSignals = await collectPageSignals(page);
  while (Date.now() < deadline) {
    await page.waitForTimeout(1000);
    await dismissTransientPrompts(page);
    detected = await detectSurface(page);
    lastSignals = await collectPageSignals(page);
    if (detected.surface === "editor") {
      const { stateSaved, stateSaveError } = await saveSessionStateSafely(context, stateFile);
      const evidence = await capturePageEvidence(page, args, "bootstrap-session-ready", {
        reused_existing_session: false,
      });
      return {
        status: "ok",
        mode: "bootstrap-session",
        live_ready: true,
        logged_in: true,
        reused_existing_session: false,
        final_url: detected.url,
        page_title: detected.title,
        matched_selector: detected.matched_selector,
        state_file: stateFile,
        state_file_written: stateSaved,
        state_file_write_error: stateSaveError,
        browser_profile_dir: profileDir,
        session_cookie_applied: cookieResult.applied,
        session_cookie_names: cookieResult.names,
        auth_material_source: authMaterialSource,
        credential_login: credentialLogin,
        login_mode: loginMode,
        sms_code_file: credentialLogin.sms_code_file,
        sms_code_applied: credentialLogin.sms_code_applied,
        evidence,
      };
    }
    if (detected.surface === "blocked" || lastSignals.manualClearanceRequired) {
      const evidence = await capturePageEvidence(page, args, "bootstrap-session-blocked", {
        final_blocker: "manual_clearance_required",
        manual_clearance_marker: lastSignals.manualClearanceMarker,
      });
      return {
        status: "blocked",
        mode: "bootstrap-session",
        live_ready: false,
        logged_in: false,
        reason: "manual_clearance_required",
        final_blocker: "manual_clearance_required",
        final_url: detected.url,
        page_title: detected.title,
        matched_selector: detected.matched_selector || lastSignals.manualClearanceMarker,
        state_file: stateFile,
        state_file_written: false,
        browser_profile_dir: profileDir,
        session_cookie_applied: cookieResult.applied,
        session_cookie_names: cookieResult.names,
        auth_material_source: authMaterialSource,
        credential_login: credentialLogin,
        login_mode: loginMode,
        sms_code_file: credentialLogin.sms_code_file,
        sms_code_applied: credentialLogin.sms_code_applied,
        manual_clearance_required: true,
        body_excerpt: lastSignals.bodyExcerpt,
        evidence,
      };
    }
  }

  let reason = "manual_login_not_completed";
  if (loginMode === "sms" && credentialLogin.reason === "sms_code_required") {
    reason = "sms_code_required";
  } else if (credentialLogin.reason === "credentials_missing") {
    reason = "credentials_missing_or_manual_login_required";
  } else if (credentialLogin.reason && credentialLogin.reason !== "not-needed") {
    reason = credentialLogin.reason;
  } else if (credentialLogin.submitted) {
    reason = "manual_clearance_required";
  } else if (detected.surface !== "login") {
    reason = "session_invalid_or_missing";
  }
  const evidence = await capturePageEvidence(page, args, "bootstrap-session-timeout", {
    final_blocker: reason,
    surface: detected.surface,
  });
  return {
    status: "blocked",
    mode: "bootstrap-session",
    live_ready: false,
    logged_in: false,
    reason,
    final_blocker: reason,
    final_url: detected.url,
    page_title: detected.title,
    matched_selector: detected.matched_selector,
    state_file: stateFile,
    state_file_written: false,
    browser_profile_dir: profileDir,
    session_cookie_applied: cookieResult.applied,
    session_cookie_names: cookieResult.names,
    auth_material_source: authMaterialSource,
    credential_login: credentialLogin,
    login_mode: loginMode,
    sms_code_file: credentialLogin.sms_code_file,
    sms_code_applied: credentialLogin.sms_code_applied,
    manual_clearance_required: reason === "manual_clearance_required",
    body_excerpt: lastSignals.bodyExcerpt,
    evidence,
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const action = args.action || "check-session";
  const timeoutMs = Number.parseInt(args["timeout-ms"] || "45000", 10);
  const headless = parseBool(args.headless, action === "check-session");
  const stateFile = args["state-file"] || "";
  const payload = await loadJsonFile(args["payload-file"] || "");
  const submit = parseBool(args.submit, false);

  const runtime = await launchJuejinContext({
    headless,
    stateFile,
    preferPersistent: true,
    allowFreshPersistentProfile: action === "bootstrap-session",
    preferStorageState: action !== "bootstrap-session",
  });

  let result;
  try {
    if (action === "bootstrap-session") {
      result = await bootstrapSession(runtime, args, stateFile, timeoutMs);
    } else if (action === "check-session") {
      result = await checkSession(runtime, args, stateFile, timeoutMs);
    } else if (action === "prepare-article") {
      result = await prepareArticle(runtime, args, stateFile, timeoutMs, payload, submit);
    } else if (action === "resolve-published-url") {
      result = await resolvePublishedUrl(runtime, args, stateFile, timeoutMs, payload);
    } else {
      result = {
        status: "error",
        reason: `unsupported_action:${action}`,
      };
    }
  } catch (error) {
    result = {
      status: "error",
      reason: String(error?.message || error),
      final_url: runtime.page?.url?.() || "",
    };
  } finally {
    await closeRuntime(runtime);
  }

  await checkpointResult(args, result);
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  if (result.status === "error") {
    process.exitCode = 1;
  }
}

main().catch((error) => {
  const message = String(error?.stack || error);
  process.stderr.write(`${message}\n`);
  process.exitCode = 1;
});
