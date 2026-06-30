-- eval-gateway 数据库初始化（幂等）
-- 在共享 PG 的独立 schema `gateway` 中建 jobs 表，与 web 的 public schema 隔离。

CREATE SCHEMA IF NOT EXISTS gateway;

CREATE TABLE IF NOT EXISTS gateway.jobs (
    job_id        text PRIMARY KEY,
    project_id    text NOT NULL,
    org_id        text NOT NULL,
    status        text NOT NULL DEFAULT 'queued',
    input_kind    text NOT NULL,
    scope         text NOT NULL,
    input_ref     text NOT NULL,
    rule_set_id   text NOT NULL DEFAULT 'coursework-default',
    run_id        text,
    web_run_url   text,
    metrics       jsonb,
    error         jsonb,
    created_at    timestamptz NOT NULL DEFAULT now(),
    started_at    timestamptz,
    finished_at   timestamptz
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON gateway.jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_project_created ON gateway.jobs (project_id, created_at DESC);
