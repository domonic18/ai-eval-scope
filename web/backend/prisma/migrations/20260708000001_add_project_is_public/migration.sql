-- 项目公开开关（docs/arch/12 §3.5）：
-- 公开后该项目运行/样本详情页免登录可读，并可被第三方 iframe 嵌入。
-- @default false 兼容历史项目（默认不公开，行为不变）。
ALTER TABLE "projects" ADD COLUMN IF NOT EXISTS "is_public" BOOLEAN NOT NULL DEFAULT false;
