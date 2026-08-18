-- S3-2: 场景级 defaults（指标定义 + 聚合策略）版本化
-- 与 rule_set_assets 同构；修复「defaults 编辑即上线」：发布产生不可变新版本，草稿不入库。
-- 不做向后兼容：迁移后删除 scenarios 上的两个 JSONB 列。

-- 1. 建 defaults_assets 表
CREATE TABLE "defaults_assets" (
    "id" TEXT NOT NULL,
    "scenario_id" TEXT NOT NULL,
    "asset_id" TEXT NOT NULL,
    "version" TEXT NOT NULL,
    "labels" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "content_hash" TEXT NOT NULL,
    "content" JSONB NOT NULL,
    "created_by" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "defaults_assets_pkey" PRIMARY KEY ("id")
);

-- 版本不可变基石：(scenario_id, asset_id, version) 唯一
CREATE UNIQUE INDEX "defaults_assets_scenario_id_asset_id_version_key"
    ON "defaults_assets" ("scenario_id", "asset_id", "version");

-- 外键：scenario 删除时级联
ALTER TABLE "defaults_assets"
    ADD CONSTRAINT "defaults_assets_scenario_id_fkey"
    FOREIGN KEY ("scenario_id") REFERENCES "scenarios" ("id") ON DELETE CASCADE;

-- 2. 回填：现有 scenarios 两个 JSONB 列 → defaults_assets v1.0.0（assetId=default, labels=[latest,production]）
--    content = { metric_definitions, aggregation_policy }（snake，对齐 GET /defaults 返回结构）
INSERT INTO "defaults_assets" ("id", "scenario_id", "asset_id", "version", "labels", "content_hash", "content", "created_by")
SELECT
    gen_random_uuid(),
    "id",
    'default',
    '1.0.0',
    ARRAY['latest', 'production']::TEXT[],
    'sha256:migrated-defaults-v1',
    jsonb_build_object(
        'metric_definitions', COALESCE("default_metric_definitions", '[]'::jsonb),
        'aggregation_policy', "default_aggregation_policy"
    ),
    'migrate-script'
FROM "scenarios"
WHERE "default_metric_definitions" IS NOT NULL OR "default_aggregation_policy" IS NOT NULL;

-- 3. 删除 scenarios 旧 JSONB 列（不做向后兼容）
ALTER TABLE "scenarios" DROP COLUMN "default_metric_definitions";
ALTER TABLE "scenarios" DROP COLUMN "default_aggregation_policy";
