-- LlmModel 配置表（docs/arch/15 LLM 配置与 AI 生成）
CREATE TABLE "llm_models" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "provider" TEXT NOT NULL,
    "base_url" TEXT,
    "api_key_encrypted" TEXT NOT NULL,
    "model_name" TEXT NOT NULL,
    "is_active" BOOLEAN NOT NULL DEFAULT true,
    "is_default" BOOLEAN NOT NULL DEFAULT false,
    "extra" JSONB,
    "last_tested_at" TIMESTAMP(3),
    "last_test_status" TEXT,
    "last_test_error" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "llm_models_pkey" PRIMARY KEY ("id")
);

-- 全局默认唯一：is_default=true 至多一行
CREATE UNIQUE INDEX "llm_models_is_default_unique" ON "llm_models" ("is_default") WHERE "is_default" = true;

-- 活跃模型按协议检索
CREATE INDEX "llm_models_provider_is_active_idx" ON "llm_models" ("provider") WHERE "is_active" = true;
