-- S2-D: eval_jobs 增加 package_ref（场景包引用 scenario/package:label）。
-- 缺失视为历史 job，executor 拒绝执行（对齐 docs/plan/03）。nullable，向后兼容。
ALTER TABLE "eval_jobs" ADD COLUMN "package_ref" TEXT;
