import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import process from "node:process";

const LOCK_FILENAMES = ["SingletonLock", "SingletonSocket", "SingletonCookie"];
const DEFAULT_STALE_AFTER_MS = 5 * 60 * 1000;

function parseLockTarget(target) {
  const raw = String(target || "").trim();
  const match = raw.match(/^(.*)-(\d+)$/);
  if (!match) {
    return { host: "", pid: 0 };
  }
  return { host: match[1], pid: Number.parseInt(match[2], 10) || 0 };
}

function processExists(pid) {
  if (!pid) {
    return false;
  }
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function safeReadlink(filePath) {
  try {
    return await fs.readlink(filePath);
  } catch {
    return "";
  }
}

async function isOldEnough(filePath, staleAfterMs) {
  try {
    const stat = await fs.lstat(filePath);
    return Date.now() - stat.mtimeMs >= staleAfterMs;
  } catch {
    return false;
  }
}

async function safeRemove(filePath) {
  try {
    await fs.rm(filePath, { force: true, recursive: false });
  } catch {
    // Best effort only. Browser launch will surface the real blocker if removal fails.
  }
}

export async function clearStaleChromiumSingletonLocks(profileDir, options = {}) {
  if (String(process.env.AIMAGICIAN_CLEAR_STALE_PROFILE_LOCKS || "true").toLowerCase() === "false") {
    return { removed: [], reason: "disabled" };
  }
  const staleAfterMs = Number.parseInt(
    String(options.staleAfterMs || process.env.AIMAGICIAN_PROFILE_LOCK_STALE_AFTER_MS || DEFAULT_STALE_AFTER_MS),
    10,
  ) || DEFAULT_STALE_AFTER_MS;
  const lockPath = path.join(profileDir, "SingletonLock");
  const target = await safeReadlink(lockPath);
  if (!target) {
    return { removed: [], reason: "no_lock" };
  }
  const { host, pid } = parseLockTarget(target);
  const currentHost = os.hostname();
  const oldEnough = await isOldEnough(lockPath, staleAfterMs);
  const sameHost = !host || host === currentHost;
  const livePid = sameHost && processExists(pid);

  if (livePid || !oldEnough) {
    return {
      removed: [],
      reason: livePid ? "active_pid" : "lock_not_stale",
      lock_target: target,
      current_host: currentHost,
    };
  }

  const removed = [];
  for (const name of LOCK_FILENAMES) {
    const filePath = path.join(profileDir, name);
    await safeRemove(filePath);
    removed.push(name);
  }
  return {
    removed,
    reason: "stale_lock_removed",
    lock_target: target,
    current_host: currentHost,
  };
}
