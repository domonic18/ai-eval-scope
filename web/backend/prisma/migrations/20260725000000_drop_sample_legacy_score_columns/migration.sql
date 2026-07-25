-- 删除 samples 表遗留的 courseware s_* 标量列
-- 场景化后样本指标由 metrics JSONB 取代（key=metric_id）；events 已不再发送这些字段。
ALTER TABLE "samples" DROP COLUMN "s_common",
DROP COLUMN "s_format",
DROP COLUMN "s_pref",
DROP COLUMN "s_soft";
