-- 新增 runs.summary_report JSONB（评估器 LLM 生成的人话版摘要报告）
ALTER TABLE "runs" ADD COLUMN "summary_report" JSONB;
