-- 0002: jobs 表加调用方可设的任务字段（task_id/task_title/task_subject）。
-- 背景：task_id 不填时 builder 回退为物化目录名（单页恒为 "contents"），
--       导致 run 内 sample_id 恒为 contents；加列后调用方可经 HTTP 覆盖。
-- 幂等：IF NOT EXISTS，可重复执行。

ALTER TABLE gateway.jobs
    ADD COLUMN IF NOT EXISTS task_id text,
    ADD COLUMN IF NOT EXISTS task_title text,
    ADD COLUMN IF NOT EXISTS task_subject text;
