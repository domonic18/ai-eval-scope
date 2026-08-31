-- eval_jobs.rule_set_id 列默认值 quality → vision：
-- 对齐 courseware 包清单 default_rule_set: coursework-vision（HTTP 提交未传 rule_set_id 时
-- 的默认档位，含多模态视觉评估）。列 default 仅兜底未显式指定列的插入路径，
-- 运行时回退链在 executor runner：job.rule_set_id → manifest.default_rule_set → manifest.id。
ALTER TABLE "eval_jobs" ALTER COLUMN "rule_set_id" SET DEFAULT 'coursework-vision';
