-- LLM③（arch/16 §6.2-四）：LlmModel 增加角色列——云端形态按角色（text|vision|agent）
-- 供 executor 经 /api/public/llm-config 拉取；存量行回填 text。

-- AlterTable
ALTER TABLE "llm_models" ADD COLUMN "role" TEXT NOT NULL DEFAULT 'text';
