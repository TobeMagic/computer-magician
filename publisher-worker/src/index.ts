import process from "node:process";

import { claimNextPublisherJob, completePublisherJob, createPool, failPublisherJob } from "./db.js";
import { runPublisherWorkerJob } from "./runner.js";

function envNumber(name: string, fallback: number): number {
  const raw = Number(process.env[name] || "");
  return Number.isFinite(raw) && raw > 0 ? raw : fallback;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function main(): Promise<void> {
  const workerId = process.env.AIMAGICIAN_PUBLISHER_WORKER_ID || process.env.AIMAGICIAN_WORKER_ID || "publisher-worker";
  const pollIntervalMs = envNumber("AIMAGICIAN_PUBLISHER_WORKER_POLL_INTERVAL_MS", 2000);
  const maxJobs = Math.floor(envNumber("AIMAGICIAN_PUBLISHER_WORKER_MAX_JOBS", 0));
  const pool = createPool();
  let stopped = false;
  let executed = 0;
  process.on("SIGTERM", () => {
    stopped = true;
  });
  process.on("SIGINT", () => {
    stopped = true;
  });

  console.log(JSON.stringify({ event: "publisher_worker.started", worker_id: workerId, poll_interval_ms: pollIntervalMs }));
  while (!stopped) {
    const job = await claimNextPublisherJob(pool, workerId);
    if (!job) {
      await sleep(pollIntervalMs);
      continue;
    }
    console.log(JSON.stringify({ event: "publisher_worker.job_claimed", worker_id: workerId, job_id: job.id, platform: job.platform, action: job.action }));
    try {
      const result = await runPublisherWorkerJob(job);
      await completePublisherJob(pool, job.id, result);
      console.log(JSON.stringify({ event: "publisher_worker.job_completed", worker_id: workerId, job_id: job.id, status: result.status || "ok" }));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      await failPublisherJob(pool, job.id, "publisher_worker_unhandled_error", message, {
        status: "blocked",
        failure_code: "publisher_worker_unhandled_error",
        failure_message: message,
      });
      console.error(JSON.stringify({ event: "publisher_worker.job_failed", worker_id: workerId, job_id: job.id, error: message }));
    }
    executed += 1;
    if (maxJobs > 0 && executed >= maxJobs) {
      stopped = true;
    }
  }
  await pool.end();
  console.log(JSON.stringify({ event: "publisher_worker.stopped", worker_id: workerId, executed_jobs: executed }));
}

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(JSON.stringify({ event: "publisher_worker.fatal", error: message }));
  process.exit(1);
});
