-- P5-8 阶段C：删除 Run 的遗留一等指标列（dr/cpr/avg_reward/avg_soft/avg_pref/cond_r/avg_time_ms）
-- 指标已迁移到 metrics JSONB（Phase 3-5），查询层与前端均走 metrics，无遗留列依赖
ALTER TABLE "runs" DROP COLUMN "dr",
                     DROP COLUMN "cpr",
                     DROP COLUMN "avg_reward",
                     DROP COLUMN "avg_soft",
                     DROP COLUMN "avg_pref",
                     DROP COLUMN "cond_r",
                     DROP COLUMN "avg_time_ms";
