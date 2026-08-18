-- AlterTable
ALTER TABLE "eval_jobs" ALTER COLUMN "rule_set_id" DROP DEFAULT,
ALTER COLUMN "created_at" SET DATA TYPE TIMESTAMP(3),
ALTER COLUMN "started_at" SET DATA TYPE TIMESTAMP(3),
ALTER COLUMN "finished_at" SET DATA TYPE TIMESTAMP(3);

-- AlterTable
ALTER TABLE "scenarios" ADD COLUMN     "default_metric_definitions" JSONB;
