-- Webhook 投递历史表（每次 attempt 一行）
CREATE TABLE "webhook_deliveries" (
    "id" TEXT NOT NULL,
    "project_id" TEXT NOT NULL,
    "job_id" TEXT,
    "event" TEXT NOT NULL,
    "url" TEXT NOT NULL,
    "attempt" INTEGER NOT NULL,
    "success" BOOLEAN NOT NULL DEFAULT false,
    "status_code" INTEGER,
    "error" TEXT,
    "duration_ms" INTEGER,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "webhook_deliveries_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "webhook_deliveries_project_id_created_at_idx" ON "webhook_deliveries"("project_id", "created_at");

-- AddForeignKey
ALTER TABLE "webhook_deliveries" ADD CONSTRAINT "webhook_deliveries_project_id_fkey" FOREIGN KEY ("project_id") REFERENCES "projects"("id") ON DELETE CASCADE ON UPDATE CASCADE;
