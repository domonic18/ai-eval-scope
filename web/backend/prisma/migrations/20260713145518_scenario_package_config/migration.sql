-- 注：本迁移仅含 Phase 3 场景化配置的变更（projects/runs/samples + 8 张新表）。
-- eval_jobs 的既有 drift（rule_set_id DEFAULT / 时间戳精度）不在本期范围，已从自动生成结果中剔除。

-- AlterTable
ALTER TABLE "projects" ADD COLUMN     "default_package" TEXT,
ADD COLUMN     "default_scenario" TEXT;

-- AlterTable
ALTER TABLE "runs" ADD COLUMN     "metrics" JSONB,
ADD COLUMN     "package_id" TEXT,
ADD COLUMN     "package_version" TEXT,
ADD COLUMN     "run_config_snapshot_id" TEXT,
ADD COLUMN     "scenario_id" TEXT,
ALTER COLUMN "dr" DROP NOT NULL,
ALTER COLUMN "cpr" DROP NOT NULL,
ALTER COLUMN "avg_reward" DROP NOT NULL,
ALTER COLUMN "cond_r" DROP NOT NULL,
ALTER COLUMN "avg_time_ms" DROP NOT NULL,
ALTER COLUMN "avg_soft" DROP NOT NULL,
ALTER COLUMN "avg_soft" DROP DEFAULT,
ALTER COLUMN "avg_pref" DROP NOT NULL,
ALTER COLUMN "avg_pref" DROP DEFAULT;

-- AlterTable
ALTER TABLE "samples" ADD COLUMN     "metrics" JSONB,
ALTER COLUMN "s_format" DROP NOT NULL,
ALTER COLUMN "s_common" DROP NOT NULL,
ALTER COLUMN "s_soft" DROP NOT NULL,
ALTER COLUMN "s_pref" DROP NOT NULL,
ALTER COLUMN "reward" DROP NOT NULL,
ALTER COLUMN "total_duration_ms" DROP NOT NULL;

-- CreateTable
CREATE TABLE "scenarios" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "scenarios_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "scenario_packages" (
    "id" TEXT NOT NULL,
    "scenario_id" TEXT NOT NULL,
    "asset_id" TEXT NOT NULL,
    "version" TEXT NOT NULL,
    "labels" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "content_hash" TEXT NOT NULL,
    "content" JSONB NOT NULL,
    "created_by" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "scenario_packages_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "rule_set_assets" (
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

    CONSTRAINT "rule_set_assets_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "prompt_template_assets" (
    "id" TEXT NOT NULL,
    "scenario_id" TEXT NOT NULL,
    "package_id" TEXT,
    "asset_id" TEXT NOT NULL,
    "namespace" TEXT NOT NULL,
    "version" TEXT NOT NULL,
    "labels" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "content_hash" TEXT NOT NULL,
    "content" JSONB NOT NULL,
    "created_by" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "prompt_template_assets_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "dataset_assets" (
    "id" TEXT NOT NULL,
    "scenario_id" TEXT NOT NULL,
    "package_id" TEXT,
    "asset_id" TEXT NOT NULL,
    "role" TEXT NOT NULL,
    "version" TEXT NOT NULL,
    "labels" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "backend_type" TEXT NOT NULL,
    "backend_config" JSONB NOT NULL,
    "content_hash" TEXT NOT NULL,
    "content" JSONB NOT NULL,
    "created_by" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "dataset_assets_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "sut_config_assets" (
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

    CONSTRAINT "sut_config_assets_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "inferencer_assets" (
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

    CONSTRAINT "inferencer_assets_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "run_config_snapshots" (
    "id" TEXT NOT NULL,
    "scenario_id" TEXT NOT NULL,
    "package_id" TEXT NOT NULL,
    "package_version" TEXT NOT NULL,
    "content" JSONB NOT NULL,
    "content_hash" TEXT NOT NULL,
    "object_key" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "run_config_snapshots_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "scenario_packages_scenario_id_asset_id_version_key" ON "scenario_packages"("scenario_id", "asset_id", "version");

-- CreateIndex
CREATE UNIQUE INDEX "rule_set_assets_scenario_id_asset_id_version_key" ON "rule_set_assets"("scenario_id", "asset_id", "version");

-- CreateIndex
CREATE UNIQUE INDEX "prompt_template_assets_scenario_id_namespace_asset_id_versi_key" ON "prompt_template_assets"("scenario_id", "namespace", "asset_id", "version");

-- CreateIndex
CREATE UNIQUE INDEX "dataset_assets_scenario_id_asset_id_version_key" ON "dataset_assets"("scenario_id", "asset_id", "version");

-- CreateIndex
CREATE UNIQUE INDEX "sut_config_assets_scenario_id_asset_id_version_key" ON "sut_config_assets"("scenario_id", "asset_id", "version");

-- CreateIndex
CREATE UNIQUE INDEX "inferencer_assets_scenario_id_asset_id_version_key" ON "inferencer_assets"("scenario_id", "asset_id", "version");

-- CreateIndex
CREATE INDEX "run_config_snapshots_scenario_id_package_id_package_version_idx" ON "run_config_snapshots"("scenario_id", "package_id", "package_version");

-- AddForeignKey
ALTER TABLE "runs" ADD CONSTRAINT "runs_run_config_snapshot_id_fkey" FOREIGN KEY ("run_config_snapshot_id") REFERENCES "run_config_snapshots"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "scenario_packages" ADD CONSTRAINT "scenario_packages_scenario_id_fkey" FOREIGN KEY ("scenario_id") REFERENCES "scenarios"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "rule_set_assets" ADD CONSTRAINT "rule_set_assets_scenario_id_fkey" FOREIGN KEY ("scenario_id") REFERENCES "scenarios"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "prompt_template_assets" ADD CONSTRAINT "prompt_template_assets_scenario_id_fkey" FOREIGN KEY ("scenario_id") REFERENCES "scenarios"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "dataset_assets" ADD CONSTRAINT "dataset_assets_scenario_id_fkey" FOREIGN KEY ("scenario_id") REFERENCES "scenarios"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "sut_config_assets" ADD CONSTRAINT "sut_config_assets_scenario_id_fkey" FOREIGN KEY ("scenario_id") REFERENCES "scenarios"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "inferencer_assets" ADD CONSTRAINT "inferencer_assets_scenario_id_fkey" FOREIGN KEY ("scenario_id") REFERENCES "scenarios"("id") ON DELETE CASCADE ON UPDATE CASCADE;
