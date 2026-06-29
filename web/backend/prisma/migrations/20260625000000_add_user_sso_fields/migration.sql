-- Add SSO (SAML) fields to users; password_hash becomes nullable for SSO users
-- docs/arch/12 §4.2

-- SSO 用户无密码：password_hash 改为可空
ALTER TABLE "users" ALTER COLUMN "password_hash" DROP NOT NULL;

-- SSO 字段
ALTER TABLE "users"
    ADD COLUMN "auth_type"         TEXT NOT NULL DEFAULT 'password',
    ADD COLUMN "sso_provider"      TEXT,
    ADD COLUMN "sso_name_id"       TEXT,
    ADD COLUMN "sso_attributes"    JSONB,
    ADD COLUMN "last_sso_login_at" TIMESTAMP(3);

-- sso_name_id 唯一索引：PostgreSQL 唯一约束天然允许多个 NULL，故 password 用户的 NULL 不冲突
CREATE UNIQUE INDEX "users_sso_name_id_key" ON "users" ("sso_name_id");
