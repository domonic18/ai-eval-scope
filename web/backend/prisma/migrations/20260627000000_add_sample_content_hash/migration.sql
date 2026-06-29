-- 样本内容指纹列（docs/arch/13 §5）
-- content_hash 记录被评估内容的版本指纹（SHA256 前 8 位），用于溯源/版本标记/同名异内容检测；
-- 不参与唯一键（[runId, externalSampleId] 保持），externalSampleId 为稳定的逻辑课件标识。
ALTER TABLE "samples" ADD COLUMN IF NOT EXISTS "content_hash" TEXT;
