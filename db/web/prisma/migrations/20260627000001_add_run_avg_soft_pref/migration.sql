-- 运行级分项指标（docs/arch/07）：内容质量分 avg_soft / 用户偏好分 avg_pref
-- 独立于 Reward 的细分指标，@default 0 兼容历史 run。
ALTER TABLE "runs" ADD COLUMN IF NOT EXISTS "avg_soft" DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE "runs" ADD COLUMN IF NOT EXISTS "avg_pref" DOUBLE PRECISION NOT NULL DEFAULT 0;
