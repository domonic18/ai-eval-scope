-- AlterTable
ALTER TABLE "users" ADD COLUMN     "last_login_at" TIMESTAMP(3);

-- CreateTable
CREATE TABLE "org_invitations" (
    "id" TEXT NOT NULL,
    "org_id" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "role" TEXT NOT NULL DEFAULT 'member',
    "invited_by" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'pending',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "resent_at" TIMESTAMP(3),

    CONSTRAINT "org_invitations_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "org_invitations_org_id_status_idx" ON "org_invitations"("org_id", "status");

-- CreateIndex
CREATE INDEX "org_invitations_email_status_idx" ON "org_invitations"("email", "status");

-- AddForeignKey
ALTER TABLE "org_invitations" ADD CONSTRAINT "org_invitations_org_id_fkey" FOREIGN KEY ("org_id") REFERENCES "organizations"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "org_invitations" ADD CONSTRAINT "org_invitations_invited_by_fkey" FOREIGN KEY ("invited_by") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;
