-- 一次性切换为单一 Bearer token（系统未正式上线，无历史数据保留）。
-- 旧 PK/SK 字段（public_key/secret_hash/secret_encrypted）→ token_hash/token_encrypted/token_preview。
-- 见 docs/arch/13第三方接入数据归属方案.md §8。

-- 旧 api_keys 数据（PK/SK 格式）在 Bearer 模式下无效，清空
DELETE FROM "api_keys";

DROP INDEX IF EXISTS "api_keys_public_key_key";
ALTER TABLE "api_keys" DROP COLUMN IF EXISTS "public_key";
ALTER TABLE "api_keys" DROP COLUMN IF EXISTS "secret_hash";
ALTER TABLE "api_keys" DROP COLUMN IF EXISTS "secret_encrypted";

ALTER TABLE "api_keys" ADD COLUMN "token_hash" TEXT NOT NULL;
ALTER TABLE "api_keys" ADD COLUMN "token_encrypted" TEXT NOT NULL;
ALTER TABLE "api_keys" ADD COLUMN "token_preview" TEXT NOT NULL;

CREATE UNIQUE INDEX "api_keys_token_hash_key" ON "api_keys"("token_hash");
