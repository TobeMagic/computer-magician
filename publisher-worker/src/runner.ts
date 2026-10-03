import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";

import type { PublisherWorkerJob } from "./db.js";

export type RunnerResult = Record<string, unknown>;

function asText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function asBoolText(value: unknown, fallback: boolean): string {
  if (value === undefined || value === null || value === "") {
    return fallback ? "true" : "false";
  }
  return String(value).toLowerCase() === "true" || value === true ? "true" : "false";
}

function argPair(args: string[], key: string, value: unknown): void {
  const text = asText(value);
  if (text) {
    args.push(key, text);
  }
}

function usableSecretText(value: unknown): string {
  const text = asText(value);
  if (!text || text === "[REDACTED]" || /^\*+$/.test(text)) {
    return "";
  }
  return text;
}

async function readTextFile(filePath: unknown): Promise<string> {
  const target = asText(filePath);
  if (!target) {
    return "";
  }
  try {
    return (await fs.readFile(target, "utf8")).trim();
  } catch {
    return "";
  }
}

async function secretFromArtifact(artifact: Record<string, unknown>, valueKey: string, fileKey: string): Promise<string> {
  const fromFile = usableSecretText(await readTextFile(artifact[fileKey]));
  return fromFile || usableSecretText(artifact[valueKey]);
}

async function readJsonObject(filePath: string): Promise<Record<string, unknown>> {
  if (!filePath) {
    return {};
  }
  try {
    const raw = await fs.readFile(filePath, "utf8");
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function objectFromText(raw: string): Record<string, unknown> {
  const text = String(raw || "").trim();
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end < start) {
    return {};
  }
  try {
    const parsed = JSON.parse(text.slice(start, end + 1));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

export async function runPublisherWorkerJob(job: PublisherWorkerJob): Promise<RunnerResult> {
  const artifact = job.artifact_json || {};
  const runner = asText(artifact.compatibility_runner);
  if (!runner) {
    return {
      status: "blocked",
      failure_code: "publisher_worker_runner_missing",
      failure_message: "Publisher worker job is missing compatibility_runner.",
      platform: job.platform,
    };
  }
  const outputPath = asText(artifact.output_json);
  const args = [
    runner,
    "--action",
    job.action,
    "--timeout-ms",
    String(Math.max(1000, Number(job.timeout_seconds || 900) * 1000)),
    "--headless",
    asBoolText(artifact.headless, true),
  ];
  argPair(args, "--state-file", artifact.state_file);
  argPair(args, "--payload-file", artifact.payload_json);
  argPair(args, "--output-file", artifact.output_json);
  argPair(args, "--progress-file", artifact.progress_json);
  argPair(args, "--evidence-dir", artifact.evidence_dir);
  if (artifact.submit === true || String(artifact.submit).toLowerCase() === "true") {
    args.push("--submit", "true");
  }
  if (artifact.save_draft === true || String(artifact.save_draft).toLowerCase() === "true") {
    args.push("--save-draft", "true");
  }
  if (job.platform === "CSDN") {
    argPair(args, "--fan-broadcast-audience", artifact.fan_broadcast_audience || "active");
  }
  if (job.platform === "51CTO" && artifact.publish_wait_ms) {
    argPair(args, "--publish-wait-ms", artifact.publish_wait_ms);
  }
  const phoneNumber = await secretFromArtifact(artifact, "phone_number", "phone_number_file");
  argPair(args, "--login-mode", artifact.login_mode);
  argPair(args, "--phone-number", phoneNumber);
  argPair(args, "--sms-code-file", artifact.sms_code_file);

  const cwd = path.dirname(runner);
  const childResult = await spawnNode(args, cwd, Number(job.timeout_seconds || 900) + 180);
  const outputResult = await readJsonObject(outputPath);
  const parsedStdout = objectFromText(childResult.stdout);
  const result = Object.keys(outputResult).length ? outputResult : parsedStdout;
  const finalResult: RunnerResult = Object.keys(result).length
    ? result
    : {
        status: "blocked",
        failure_code: "publisher_worker_output_missing",
        failure_message: "Publisher worker compatibility runner did not produce JSON output.",
      };
  finalResult.returncode = childResult.code;
  if (childResult.stderr) {
    finalResult.stderr_tail = childResult.stderr.slice(-1200);
  }
  if (childResult.stdout) {
    finalResult.stdout_tail = childResult.stdout.slice(-1200);
  }
  if (childResult.code !== 0 && !["blocked", "failed", "error", "waiting_for_human"].includes(String(finalResult.status || "").toLowerCase())) {
    finalResult.status = "blocked";
    finalResult.failure_code = String(finalResult.failure_code || "publisher_worker_exit_nonzero");
    finalResult.failure_message = String(finalResult.failure_message || "Publisher worker compatibility runner exited with a non-zero code.");
  }
  return finalResult;
}

function spawnNode(args: string[], cwd: string, timeoutSeconds: number): Promise<{ code: number | null; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    const child = spawn(process.env.AIMAGICIAN_NODE_BINARY || "node", args, {
      cwd,
      env: process.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      stderr += `\nPublisher worker timed out after ${timeoutSeconds} seconds.`;
    }, Math.max(1, timeoutSeconds) * 1000);
    child.stdout.on("data", (chunk) => {
      stdout += String(chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      resolve({ code: 1, stdout, stderr: `${stderr}\n${error.message}` });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code, stdout, stderr });
    });
  });
}
