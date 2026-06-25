-- ============================================================
-- Agent Eval 可观测平台 — 数据库初始化 SQL（postgres 首次起栈自动执行）
-- ============================================================
-- 用途：经 docker-compose 挂载到 postgres 的 docker-entrypoint-initdb.d，
--       在数据目录为空（首次 initdb）时由官方 postgres 镜像自动执行，创建全部业务表。
-- 来源：由 web/backend/prisma/migrations/*/migration.sql 按时间戳顺序拼接（即
--       `prisma migrate dev --create-only` 产物，符合《数据库迁移规范》「不得手写裸 DDL」）。
-- 维护：schema 变更时，先 `prisma migrate dev --create-only` 生成新 migration.sql，
--       手动执行后将该文件内容追加到本文件末尾，并补对应 _prisma_migrations 种子行。
-- 注意：web 容器 CMD 不再执行 prisma migrate deploy；表结构以本文件为运行期来源。
-- ============================================================

-- CreateTable
CREATE TABLE "users" (
    "id" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "password_hash" TEXT,
    "name" TEXT,
    "auth_type" TEXT NOT NULL DEFAULT 'password',
    "sso_provider" TEXT,
    "sso_name_id" TEXT,
    "sso_attributes" JSONB,
    "last_sso_login_at" TIMESTAMP(3),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "users_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "organizations" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "slug" TEXT NOT NULL,
    "created_by" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "organizations_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "org_memberships" (
    "org_id" TEXT NOT NULL,
    "user_id" TEXT NOT NULL,
    "role" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "org_memberships_pkey" PRIMARY KEY ("org_id","user_id")
);

-- CreateTable
CREATE TABLE "projects" (
    "id" TEXT NOT NULL,
    "org_id" TEXT NOT NULL,
    "slug" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "default_rule_set" TEXT,
    "default_task_set" TEXT,
    "retention_days" INTEGER,
    "created_by" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "archived_at" TIMESTAMP(3),

    CONSTRAINT "projects_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "api_keys" (
    "id" TEXT NOT NULL,
    "project_id" TEXT NOT NULL,
    "public_key" TEXT NOT NULL,
    "secret_hash" TEXT NOT NULL,
    "secret_encrypted" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "scopes" TEXT[] DEFAULT ARRAY['ingest']::TEXT[],
    "expires_at" TIMESTAMP(3),
    "last_used_at" TIMESTAMP(3),
    "last_ip" TEXT,
    "call_count" BIGINT NOT NULL DEFAULT 0,
    "created_by" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "revoked_at" TIMESTAMP(3),

    CONSTRAINT "api_keys_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "runs" (
    "id" TEXT NOT NULL,
    "project_id" TEXT NOT NULL,
    "external_run_id" TEXT NOT NULL,
    "mode" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'completed',
    "total_samples" INTEGER NOT NULL DEFAULT 0,
    "dr" DOUBLE PRECISION NOT NULL,
    "cpr" DOUBLE PRECISION NOT NULL,
    "avg_reward" DOUBLE PRECISION NOT NULL,
    "cond_r" DOUBLE PRECISION NOT NULL,
    "avg_time_ms" DOUBLE PRECISION NOT NULL,
    "rule_set_version" TEXT,
    "sut_version" TEXT,
    "langfuse_trace_id" TEXT,
    "langfuse_host" TEXT,
    "failure_breakdown" JSONB,
    "thresholds" JSONB,
    "source_client" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "finished_at" TIMESTAMP(3),

    CONSTRAINT "runs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "samples" (
    "id" TEXT NOT NULL,
    "run_id" TEXT NOT NULL,
    "project_id" TEXT NOT NULL,
    "external_sample_id" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "s_format" DOUBLE PRECISION NOT NULL,
    "s_common" DOUBLE PRECISION NOT NULL,
    "s_soft" DOUBLE PRECISION NOT NULL,
    "s_pref" DOUBLE PRECISION NOT NULL,
    "reward" DOUBLE PRECISION NOT NULL,
    "total_duration_ms" DOUBLE PRECISION NOT NULL,
    "llm_calls" INTEGER NOT NULL DEFAULT 0,
    "token_usage" INTEGER NOT NULL DEFAULT 0,
    "extra" JSONB,

    CONSTRAINT "samples_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "constraint_results" (
    "id" TEXT NOT NULL,
    "sample_id" TEXT NOT NULL,
    "project_id" TEXT NOT NULL,
    "constraint_id" TEXT NOT NULL,
    "rule_id" TEXT,
    "name" TEXT NOT NULL,
    "tier" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "passed" BOOLEAN NOT NULL,
    "score" DOUBLE PRECISION NOT NULL,
    "raw_score" DOUBLE PRECISION,
    "reason" TEXT NOT NULL,
    "duration_ms" DOUBLE PRECISION NOT NULL,
    "judge_provider" TEXT,
    "judge_model" TEXT,
    "judge_artifact_id" TEXT,
    "details" JSONB,
    "module_results" JSONB,

    CONSTRAINT "constraint_results_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "dimension_scores" (
    "id" TEXT NOT NULL,
    "sample_id" TEXT NOT NULL,
    "dimension_id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "weight" DOUBLE PRECISION NOT NULL,
    "score" DOUBLE PRECISION NOT NULL,
    "status" TEXT NOT NULL,

    CONSTRAINT "dimension_scores_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "artifacts" (
    "id" TEXT NOT NULL,
    "project_id" TEXT NOT NULL,
    "run_id" TEXT NOT NULL,
    "sample_id" TEXT,
    "kind" TEXT NOT NULL,
    "object_key" TEXT NOT NULL,
    "storage" TEXT NOT NULL,
    "content_type" TEXT NOT NULL,
    "size_bytes" BIGINT NOT NULL,
    "md5" TEXT,
    "original_name" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "artifacts_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "audit_logs" (
    "id" BIGSERIAL NOT NULL,
    "org_id" TEXT,
    "actor_user_id" TEXT,
    "action" TEXT NOT NULL,
    "target_type" TEXT,
    "target_id" TEXT,
    "metadata" JSONB,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "audit_logs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ingest_events" (
    "id" BIGSERIAL NOT NULL,
    "project_id" TEXT NOT NULL,
    "event_id" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "received_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ingest_events_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "users_email_key" ON "users"("email");
CREATE UNIQUE INDEX "users_sso_name_id_key" ON "users"("sso_name_id");

-- CreateIndex
CREATE UNIQUE INDEX "organizations_slug_key" ON "organizations"("slug");

-- CreateIndex
CREATE UNIQUE INDEX "projects_org_id_slug_key" ON "projects"("org_id", "slug");

-- CreateIndex
CREATE UNIQUE INDEX "api_keys_public_key_key" ON "api_keys"("public_key");

-- CreateIndex
CREATE INDEX "api_keys_project_id_idx" ON "api_keys"("project_id");

-- CreateIndex
CREATE INDEX "runs_project_id_created_at_idx" ON "runs"("project_id", "created_at" DESC);

-- CreateIndex
CREATE UNIQUE INDEX "runs_project_id_external_run_id_key" ON "runs"("project_id", "external_run_id");

-- CreateIndex
CREATE INDEX "samples_project_id_external_sample_id_idx" ON "samples"("project_id", "external_sample_id");

-- CreateIndex
CREATE UNIQUE INDEX "samples_run_id_external_sample_id_key" ON "samples"("run_id", "external_sample_id");

-- CreateIndex
CREATE INDEX "constraint_results_sample_id_idx" ON "constraint_results"("sample_id");

-- CreateIndex
CREATE INDEX "constraint_results_project_id_constraint_id_idx" ON "constraint_results"("project_id", "constraint_id");

-- CreateIndex
CREATE INDEX "dimension_scores_sample_id_idx" ON "dimension_scores"("sample_id");

-- CreateIndex
CREATE INDEX "artifacts_run_id_idx" ON "artifacts"("run_id");

-- CreateIndex
CREATE INDEX "artifacts_sample_id_idx" ON "artifacts"("sample_id");

-- CreateIndex
CREATE INDEX "audit_logs_org_id_created_at_idx" ON "audit_logs"("org_id", "created_at" DESC);

-- CreateIndex
CREATE INDEX "ingest_events_project_id_received_at_idx" ON "ingest_events"("project_id", "received_at");

-- CreateIndex
CREATE UNIQUE INDEX "ingest_events_project_id_event_id_key" ON "ingest_events"("project_id", "event_id");

-- AddForeignKey
ALTER TABLE "org_memberships" ADD CONSTRAINT "org_memberships_org_id_fkey" FOREIGN KEY ("org_id") REFERENCES "organizations"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "org_memberships" ADD CONSTRAINT "org_memberships_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "projects" ADD CONSTRAINT "projects_org_id_fkey" FOREIGN KEY ("org_id") REFERENCES "organizations"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "api_keys" ADD CONSTRAINT "api_keys_project_id_fkey" FOREIGN KEY ("project_id") REFERENCES "projects"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "runs" ADD CONSTRAINT "runs_project_id_fkey" FOREIGN KEY ("project_id") REFERENCES "projects"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "samples" ADD CONSTRAINT "samples_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "runs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "constraint_results" ADD CONSTRAINT "constraint_results_sample_id_fkey" FOREIGN KEY ("sample_id") REFERENCES "samples"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "artifacts" ADD CONSTRAINT "artifacts_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "runs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "artifacts" ADD CONSTRAINT "artifacts_sample_id_fkey" FOREIGN KEY ("sample_id") REFERENCES "samples"("id") ON DELETE CASCADE ON UPDATE CASCADE;


-- AddForeignKey
ALTER TABLE "artifacts" ADD CONSTRAINT "artifacts_project_id_fkey" FOREIGN KEY ("project_id") REFERENCES "projects"("id") ON DELETE CASCADE ON UPDATE CASCADE;


-- ============================================================
-- _prisma_migrations：标记上述迁移为「已应用」（等价 prisma migrate resolve --applied）
-- 目的：保持 prisma migrate status 一致，避免日后误跑 migrate deploy 重复建表；
--       checksum 为各 migration.sql 的 sha256（实测值）。
-- ============================================================

CREATE TABLE "_prisma_migrations" (
    "id" varchar(36) NOT NULL,
    "checksum" varchar(64) NOT NULL,
    "finished_at" timestamptz(3),
    "migration_name" varchar(255) NOT NULL,
    "logs" text,
    "rolled_back_at" timestamptz(3),
    "started_at" timestamptz(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "applied_steps_count" integer NOT NULL DEFAULT 1,

    CONSTRAINT "_prisma_migrations_pkey" PRIMARY KEY ("id")
);

INSERT INTO "_prisma_migrations" ("id", "checksum", "migration_name", "started_at", "finished_at", "applied_steps_count") VALUES ('8153ea7d-d31f-4029-abfb-825890edabab', '0dae02807e9f14e5d33a06cb9c9e0476b9ec315bc0cc9f3ee1cd3a92c4394084', '20260616234815_init', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1);
INSERT INTO "_prisma_migrations" ("id", "checksum", "migration_name", "started_at", "finished_at", "applied_steps_count") VALUES ('172d9060-eec1-4c82-8fed-c89f09f0f2c2', '6bfc6053b7367bad331dba789823df8e54d34a7ed1f8b95430ccd1715c594347', '20260617040341_add_artifact_project_relation', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1);
INSERT INTO "_prisma_migrations" ("id", "checksum", "migration_name", "started_at", "finished_at", "applied_steps_count") VALUES ('9021dc0d-2cd6-489d-8b29-0bc171eae78b', 'db0c9e6ed01668474bb8c707d46a854642b06b021bc0552bbe681445d8cf3156', '20260625000000_add_user_sso_fields', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1);
