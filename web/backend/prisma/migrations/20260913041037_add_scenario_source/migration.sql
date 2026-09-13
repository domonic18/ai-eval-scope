-- DropForeignKey
ALTER TABLE "defaults_assets" DROP CONSTRAINT "defaults_assets_scenario_id_fkey";

-- AlterTable
ALTER TABLE "scenarios" ADD COLUMN     "source" TEXT NOT NULL DEFAULT 'official';

-- AddForeignKey
ALTER TABLE "defaults_assets" ADD CONSTRAINT "defaults_assets_scenario_id_fkey" FOREIGN KEY ("scenario_id") REFERENCES "scenarios"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- Backfill：存量补缺注册场景标记为 auto_ingest（arch/09 §7.5 方向1）。
-- 判据（泛化，不硬编码 id）：defaults 由 ingest:auto 创建，或除 auto-ingest defaults 外无任何正式资产。
UPDATE "scenarios" s SET "source" = 'auto_ingest'
WHERE (
  EXISTS (SELECT 1 FROM "defaults_assets" d WHERE d."scenario_id" = s."id" AND d."created_by" = 'ingest:auto')
  OR (
    NOT EXISTS (SELECT 1 FROM "scenario_packages" p WHERE p."scenario_id" = s."id")
    AND NOT EXISTS (SELECT 1 FROM "rule_set_assets" r WHERE r."scenario_id" = s."id")
    AND NOT EXISTS (SELECT 1 FROM "prompt_template_assets" pt WHERE pt."scenario_id" = s."id")
    AND NOT EXISTS (SELECT 1 FROM "dataset_assets" da WHERE da."scenario_id" = s."id")
    AND NOT EXISTS (SELECT 1 FROM "sut_config_assets" sc WHERE sc."scenario_id" = s."id")
    AND NOT EXISTS (SELECT 1 FROM "task_set_assets" ts WHERE ts."scenario_id" = s."id")
    AND NOT EXISTS (SELECT 1 FROM "inferencer_assets" inf WHERE inf."scenario_id" = s."id")
  )
);
