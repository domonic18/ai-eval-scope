-- 评测执行任务表（gateway 合并至 Web；executor 消费）。
-- 见 docs/arch/14执行拆分与网关合并方案.md。
-- 由 Web 写入（queued），SCF executor 消费（running → completed/failed）。

-- CreateTable
CREATE TABLE IF NOT EXISTS "eval_jobs" (
    "job_id"               TEXT        NOT NULL,
    "project_id"           TEXT        NOT NULL,
    "org_id"               TEXT        NOT NULL,
    "api_key_id"           TEXT        NOT NULL,
    "status"               TEXT        NOT NULL DEFAULT 'queued',
    "input_kind"           TEXT        NOT NULL,
    "scope"                TEXT        NOT NULL,
    "input_object_key"     TEXT        NOT NULL,
    "input_presigned_url"  TEXT,
    "rule_set_id"          TEXT        NOT NULL DEFAULT 'coursework-quality',
    "task_id"              TEXT,
    "task_title"           TEXT,
    "task_subject"         TEXT,
    "run_id"               TEXT,
    "web_run_url"          TEXT,
    "scf_request_id"       TEXT,
    "metrics"              JSONB,
    "error"                JSONB,
    "created_at"           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "started_at"           TIMESTAMPTZ,
    "finished_at"          TIMESTAMPTZ,
    CONSTRAINT "eval_jobs_pkey" PRIMARY KEY ("job_id")
);

-- CreateIndex
CREATE INDEX IF NOT EXISTS "eval_jobs_status_idx" ON "eval_jobs"("status");
CREATE INDEX IF NOT EXISTS "eval_jobs_project_id_created_at_idx" ON "eval_jobs"("project_id", "created_at" DESC);
