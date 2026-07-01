-- 0003: jobs 表加 api_key_id（提交者 API Key id）。
-- 回传时按此查第三方 token，让评估结果落到提交者（第三方）的项目（方案 docs/arch/13 §5）。
-- 系统未正式上线，清空旧 jobs（无 api_key_id 的历史数据，一次性切换）。

DELETE FROM gateway.jobs;

ALTER TABLE gateway.jobs ADD COLUMN api_key_id TEXT NOT NULL;

CREATE INDEX IF NOT EXISTS idx_jobs_api_key_id ON gateway.jobs (api_key_id);
