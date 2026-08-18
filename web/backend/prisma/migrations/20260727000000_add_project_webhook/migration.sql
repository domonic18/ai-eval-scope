-- Webhook 回调配置（docs/arch/12）：项目级 webhook URL + 加密 secret
ALTER TABLE "projects" ADD COLUMN     "webhook_secret_encrypted" TEXT,
ADD COLUMN     "webhook_url" TEXT;
