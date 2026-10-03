import pg from "pg";

const { Pool } = pg;

export type PublisherWorkerJob = {
  id: string;
  parent_job_id: string;
  article_id: string | null;
  run_id: string | null;
  platform: string;
  action: string;
  status: string;
  timeout_seconds: number;
  payload_json: Record<string, unknown>;
  artifact_json: Record<string, unknown>;
};

export function databaseUrl(): string {
  const raw = process.env.AIMAGICIAN_DATABASE_URL || "";
  if (!raw.trim()) {
    throw new Error("AIMAGICIAN_DATABASE_URL is required for publisher-worker");
  }
  return raw.replace("postgresql+psycopg://", "postgresql://");
}

export function createPool(): pg.Pool {
  return new Pool({ connectionString: databaseUrl() });
}

export async function claimNextPublisherJob(pool: pg.Pool, workerId: string): Promise<PublisherWorkerJob | null> {
  const client = await pool.connect();
  try {
    await client.query("begin");
    await client.query(
      `
      update publisher_worker_jobs
      set status = case
            when attempt_count >= max_attempts then 'failed'
            else 'queued'
          end,
          claimed_by = null,
          claimed_at = null,
          started_at = null,
          failure_code = 'publisher_worker_lease_expired',
          failure_message = case
            when attempt_count >= max_attempts
              then 'Publisher worker lease expired and max attempts were exhausted'
            else 'Publisher worker lease expired and was requeued'
          end,
          finished_at = case
            when attempt_count >= max_attempts then now()
            else null
          end,
          updated_at = now()
      where status = 'running'
        and coalesce(started_at, claimed_at, updated_at) + ((timeout_seconds + 30) * interval '1 second') < now()
      `,
    );
    const result = await client.query<PublisherWorkerJob>(
      `
      select *
      from publisher_worker_jobs
      where status = 'queued'
      order by priority asc, created_at asc
      for update skip locked
      limit 1
      `,
    );
    const row = result.rows[0];
    if (!row) {
      await client.query("commit");
      return null;
    }
    await client.query(
      `
      update publisher_worker_jobs
      set status = 'running',
          claimed_by = $2,
          claimed_at = now(),
          started_at = now(),
          attempt_count = attempt_count + 1,
          updated_at = now()
      where id = $1
      `,
      [row.id, workerId],
    );
    await client.query("commit");
    return { ...row, status: "running" };
  } catch (error) {
    await client.query("rollback").catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}

const HUMAN_CHECKPOINT_TOKENS = [
  "session_invalid",
  "session_invalid_or_missing",
  "waiting_for_human",
  "manual_required",
  "manual_clearance",
  "captcha",
  "sms_code",
];

export function classifyPublisherResult(result: Record<string, unknown>): {
  status: string;
  failureCode: string | null;
  failureMessage: string | null;
} {
  const status = String(result.status || "").trim().toLowerCase();
  const failureCode = String(result.failure_code || result.reason || "").trim() || null;
  const failureMessage = String(result.failure_message || result.reason || result.next_action || "").trim() || null;
  const blob = [status, failureCode, failureMessage, String(result.final_blocker || "")].join(" ").toLowerCase();
  if (status === "waiting_for_human" || status === "manual_required" || HUMAN_CHECKPOINT_TOKENS.some((token) => blob.includes(token))) {
    return {
      status: "waiting_for_human",
      failureCode: failureCode || "human_checkpoint_required",
      failureMessage: failureMessage || "Human action required",
    };
  }
  if (status === "ok" || status === "success" || status === "succeeded") {
    return { status: "succeeded", failureCode: null, failureMessage: null };
  }
  if (status === "blocked" || status === "failed" || status === "error" || failureCode) {
    return {
      status: "failed",
      failureCode: failureCode || "publisher_worker_blocked",
      failureMessage: failureMessage || "Publisher worker returned a non-success status",
    };
  }
  return { status: "succeeded", failureCode: null, failureMessage: null };
}

export async function completePublisherJob(pool: pg.Pool, jobId: string, result: Record<string, unknown>): Promise<void> {
  const classified = classifyPublisherResult(result);
  await pool.query(
    `
    update publisher_worker_jobs
    set status = $2,
        result_json = $3::jsonb,
        failure_code = $4,
        failure_message = $5,
        finished_at = now(),
        updated_at = now()
    where id = $1
    `,
    [jobId, classified.status, JSON.stringify(result), classified.failureCode, classified.failureMessage],
  );
}

export async function failPublisherJob(
  pool: pg.Pool,
  jobId: string,
  failureCode: string,
  failureMessage: string,
  result: Record<string, unknown> = {},
): Promise<void> {
  await pool.query(
    `
    update publisher_worker_jobs
    set status = 'failed',
        result_json = $4::jsonb,
        failure_code = $2,
        failure_message = $3,
        finished_at = now(),
        updated_at = now()
    where id = $1
    `,
    [jobId, failureCode, failureMessage, JSON.stringify(result)],
  );
}
