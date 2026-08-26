-- W3（arch/16 §2.4）：平台 Secrets——org 级通用凭证 KV（GitHub Secrets 式，
-- 值加密、写后不可读）；executor 经 /api/public/secrets 拉取注入 env。

-- CreateTable
CREATE TABLE "secrets" (
    "id" TEXT NOT NULL,
    "org_id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "value_encrypted" TEXT NOT NULL,
    "created_by" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "secrets_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "secrets_org_id_name_key" ON "secrets"("org_id", "name");

-- AddForeignKey
ALTER TABLE "secrets" ADD CONSTRAINT "secrets_org_id_fkey"
    FOREIGN KEY ("org_id") REFERENCES "organizations"("id") ON DELETE CASCADE ON UPDATE CASCADE;
