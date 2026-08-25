-- W1（arch/16 §2.1）：任务集资产表——考卷内嵌场景包，随包同步（scenario 级，
-- 与 rule_set/dataset 等资产同构）；sut_configs/ 复用既有 sut_config_assets 表。

-- CreateTable
CREATE TABLE "task_set_assets" (
    "id" TEXT NOT NULL,
    "scenario_id" TEXT NOT NULL,
    "package_id" TEXT,
    "asset_id" TEXT NOT NULL,
    "version" TEXT NOT NULL,
    "labels" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "content_hash" TEXT NOT NULL,
    "content" JSONB NOT NULL,
    "created_by" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "task_set_assets_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "task_set_assets_scenario_id_asset_id_version_key"
    ON "task_set_assets"("scenario_id", "asset_id", "version");

-- AddForeignKey
ALTER TABLE "task_set_assets" ADD CONSTRAINT "task_set_assets_scenario_id_fkey"
    FOREIGN KEY ("scenario_id") REFERENCES "scenarios"("id") ON DELETE CASCADE ON UPDATE CASCADE;
